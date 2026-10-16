import json

from flask import Blueprint, request

from db import db_cursor
from routes.helpers import (
    api_error,
    api_ok,
    apply_weekly_level_progression,
    average_numbers,
    build_passage_prediction_trace,
    build_pre_assessment_trace,
    build_teacher_report_summary,
    calculate_gain,
    calculate_normalized_gain,
    calculate_wpm,
    fetch_pending_short_answer,
    fetch_pending_short_answers,
    get_stagnation_details,
    fetch_student_progress,
    fetch_teacher_student_summaries,
    get_program_settings,
    normalize_class_level,
    normalize_text_value,
    normalize_week,
    parse_program_start_date,
    recommendation_for_score,
    require_auth,
    require_role,
    TOTAL_PROGRAM_WEEKS,
)


def _record_audit_log(user_id, student_id, action, details=None):
    with db_cursor(True) as (_, cur):
        cur.execute(
            "INSERT INTO audit_logs (user_id, student_id, action, details) VALUES (%s, %s, %s, %s)",
            (user_id, student_id, action, json.dumps(details or {}, ensure_ascii=False) if details is not None else None),
        )

teacher_bp = Blueprint("teacher_bp", __name__)


@teacher_bp.post("/api/teacher/students/<student_id>/apply-recommendation")
def apply_teacher_recommendation(student_id):
    user, err = require_role("teacher")
    if err:
        return err

    with db_cursor(True) as (_, cur):
        cur.execute("SELECT id FROM students WHERE id=%s", (student_id,))
        if not cur.fetchone():
            return api_error("Student not found.", 404)
        cur.execute("SELECT MAX(week_no) AS week FROM quiz_attempts WHERE student_id=%s", (student_id,))
        latest = cur.fetchone()
        week = int(latest["week"] or 0) if latest else 0
        if not week:
            return api_error("No completed student week is available for recommendation.", 400)
        progression = apply_weekly_level_progression(cur, student_id, week)
        if not progression:
            return api_error("The selected week is not complete or still needs teacher scoring.", 400)
        if progression.get("alreadyApplied"):
            return api_error("This recommendation has already been confirmed for the week.", 409)

    _record_audit_log(user["id"], student_id, "teacher_confirm_recommendation", progression)
    return api_ok({"studentId": student_id, "progression": progression, "message": "Recommendation confirmed."})


@teacher_bp.post("/api/teacher/students/<student_id>/override-level")
def override_student_level(student_id):
    user, err = require_role("teacher")
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    level = normalize_class_level(payload.get("level"))
    reason = normalize_text_value(payload.get("reason") or "", max_length=1000)

    with db_cursor(True) as (_, cur):
        cur.execute("SELECT id FROM students WHERE id=%s", (student_id,))
        if not cur.fetchone():
            return api_error("Student not found.", 404)
        cur.execute("UPDATE students SET class_level=%s WHERE id=%s", (level, student_id))

    _record_audit_log(user["id"], student_id, "teacher_override_level", {"level": level, "reason": reason})
    return api_ok({"studentId": student_id, "classLevel": level, "message": "Student level overridden."})


@teacher_bp.get("/api/teacher/dashboard")
def teacher_dashboard():
    user, err = require_role("teacher")
    if err:
        return err
    del user

    with db_cursor(True) as (_, cur):
        students = fetch_teacher_student_summaries(cur)

        cur.execute(
            """
            SELECT qa.student_id, s.full_name, p.id AS passage_id, p.title,
                   qa.score_pct, qa.short_answer_text, qa.correct_count, qa.total_count,
                   qa.teacher_score, sc.objective_score_pct, sc.short_answer_score_pct,
                   sc.total_score_pct, qa.submitted_at
            FROM quiz_attempts qa
            JOIN (
                SELECT student_id, passage_id, week_no, MAX(id) AS latest_id
                FROM quiz_attempts
                GROUP BY student_id, passage_id, week_no
            ) latest ON latest.latest_id = qa.id
            JOIN students s ON s.id = qa.student_id
            JOIN passages p ON p.id = qa.passage_id
            LEFT JOIN scores sc ON sc.legacy_quiz_attempt_id = qa.id
            ORDER BY qa.submitted_at DESC, qa.id DESC
            LIMIT 6
            """
        )

        submissions = []
        for row in cur.fetchall():
            # compute display fraction (num/denom) using teacher_score when available for short-answer
            correct = int(row.get("correct_count") or 0)
            total = int(row.get("total_count") or 0)
            teacher = row.get("teacher_score")
            has_short = bool(row.get("short_answer_text"))

            num = None
            denom = None
            if has_short and teacher is not None:
                num = correct + int(teacher or 0)
                denom = total + 1
            elif total and total > 0:
                num = correct
                denom = total

            display_score = f"{num}/{denom}" if (num is not None and denom and denom > 0) else None
            percent_score = None
            if display_score:
                try:
                    percent_score = int(round((num / denom) * 100))
                except Exception:
                    percent_score = None

            submissions.append(
                {
                    "studentId": row["student_id"],
                    "studentName": row["full_name"],
                    "passageId": row["passage_id"],
                    "passageTitle": row["title"],
                    "displayScore": display_score,
                    "percentScore": percent_score,
                    "status": "Pending Review" if row.get("short_answer_text") and row.get("teacher_score") is None else "Scored",
                    "submittedAt": row["submitted_at"].isoformat() if row.get("submitted_at") else None,
                }
            )

    level_counts = {"EASY": 0, "MODERATE": 0, "HARD": 0}
    level_students = {"EASY": [], "MODERATE": [], "HARD": []}
    pending_reviews = []
    stagnant_students = []
    recommendation_count = 0
    for student in students:
        level = normalize_class_level(student["classLevel"])
        level_counts[level] += 1
        level_students[level].append(student["name"])
        if student["pendingReviewCount"]:
            pending_reviews.append(student)
        is_stagnant, stagnant_reason = get_stagnation_details(student["progress"])
        if is_stagnant:
            stagnant_students.append(
                {
                    "id": student["id"],
                    "name": student["name"],
                    "grade": student["grade"],
                    "section": student["section"],
                    "stagnantReason": stagnant_reason,
                }
            )
        if len(student["progress"]) >= 2:
            recommendation_count += 1

    return api_ok(
        {
            "levelCounts": level_counts,
            "levelStudents": level_students,
            "recentSubmissions": submissions,
            "pendingReviews": pending_reviews[:3],
            "stagnantStudents": stagnant_students,
            "recommendationCount": recommendation_count,
            "studentCount": len(students),
        }
    )


@teacher_bp.get("/api/teacher/students")
def teacher_students():
    user, err = require_role("teacher")
    if err:
        return err
    del user

    with db_cursor(True) as (_, cur):
        students = fetch_teacher_student_summaries(cur)
    return api_ok({"students": students})


@teacher_bp.get("/api/program/week")
def api_program_week():
    user, err = require_auth()
    if err:
        return err
    if user["role"] not in {"teacher", "student"}:
        return api_error("Insufficient permissions.", 403)
    with db_cursor(True) as (_, cur):
        settings = get_program_settings(cur)
        if not settings:
            return api_error("Program settings not configured.", 500)
    return api_ok({"activeWeek": settings["activeWeek"]})


@teacher_bp.get("/api/program/week/settings")
def api_program_week_settings_get():
    user, err = require_role("teacher")
    if err:
        return err
    del user
    with db_cursor(True) as (_, cur):
        settings = get_program_settings(cur)
        if not settings:
            return api_error("Program settings not configured.", 500)
    return api_ok(settings)


@teacher_bp.put("/api/program/week/settings")
def api_program_week_settings_put():
    user, err = require_role("teacher")
    if err:
        return err

    payload = request.get_json(silent=True)
    if payload is None:
        return api_error("Request body must be valid JSON.", 400)
    if not isinstance(payload, dict):
        return api_error("Request body must be a JSON object.", 400)

    start_date_raw = payload.get("programStartDate")
    override_week_raw = payload.get("manualOverrideWeek")

    parsed_start_date = parse_program_start_date(start_date_raw)
    if start_date_raw not in (None, "") and parsed_start_date is None:
        return api_error("programStartDate must be in YYYY-MM-DD format.", 400)

    manual_override_week = None
    if override_week_raw not in (None, "", "null"):
        try:
            parsed_override = int(override_week_raw)
        except (TypeError, ValueError):
            return api_error("manualOverrideWeek must be a number between 1 and 8, or null.", 400)
        if parsed_override < 1 or parsed_override > TOTAL_PROGRAM_WEEKS:
            return api_error("manualOverrideWeek must be between 1 and 8, or null.", 400)
        manual_override_week = parsed_override

    with db_cursor(True) as (_, cur):
        cur.execute(
            """
            UPDATE program_settings
            SET program_start_date=%s, manual_override_week=%s, updated_by=%s
            WHERE id=1
            """,
            (parsed_start_date, manual_override_week, user["id"]),
        )
        settings = get_program_settings(cur)

    return api_ok(settings)


@teacher_bp.get("/api/teacher/reports/summary")
def teacher_reports_summary():
    user, err = require_role("teacher")
    if err:
        return err
    del user

    active_week = request.args.get("activeWeek")
    with db_cursor(True) as (_, cur):
        if active_week in (None, "", "null"):
            settings = get_program_settings(cur)
            active_week = settings["activeWeek"] if settings else 1
        summary = build_teacher_report_summary(cur, normalize_week(active_week))
    return api_ok(summary)


@teacher_bp.get("/api/teacher/students/<student_id>")
def teacher_student_detail(student_id):
    user, err = require_role("teacher")
    if err:
        return err
    del user

    with db_cursor(True) as (_, cur):
        cur.execute(
            """
            SELECT s.id,s.full_name,s.grade,s.section,s.class_level,s.pre_score,s.pre_assessment_completed,u.email
            FROM students s
            JOIN users u ON u.id=s.user_id
            WHERE s.id=%s
            """,
            (student_id,),
        )
        student = cur.fetchone()
        if not student:
            return api_error("Student not found.", 404)

        progress = fetch_student_progress(cur, student_id)
        pending_short_answer = fetch_pending_short_answer(cur, student_id)

        latest_scored_attempt = None
        cur.execute(
            """
            SELECT qa.id,qa.passage_id,qa.week_no,qa.teacher_score,qa.teacher_feedback,
                   qa.teacher_scored_by,qa.teacher_scored_at,p.title,u.full_name AS scorer_name
            FROM quiz_attempts qa
            JOIN passages p ON p.id = qa.passage_id
            LEFT JOIN students u ON u.user_id = qa.teacher_scored_by
            WHERE qa.student_id=%s
              AND qa.teacher_score IS NOT NULL
            ORDER BY qa.teacher_scored_at DESC, qa.id DESC
            LIMIT 1
            """,
            (student_id,),
        )
        row = cur.fetchone()
        if row:
            latest_scored_attempt = {
                "attemptId": int(row["id"]),
                "passageId": row["passage_id"],
                "passageTitle": row["title"],
                "week": int(row["week_no"]),
                "score": int(row["teacher_score"]),
                "feedback": row.get("teacher_feedback") or "",
                "scoredBy": row.get("scorer_name"),
                "scoredAt": row["teacher_scored_at"].isoformat() if row.get("teacher_scored_at") else None,
            }

    latest = progress[-1] if progress else None
    payload = {
        "student": {
            "id": student["id"],
            "name": student["full_name"],
            "email": student["email"],
            "grade": student["grade"],
            "section": student["section"],
            "classLevel": student["class_level"],
            "preScore": int(student["pre_score"] or 0),
            "preAssessmentCompleted": bool(int(student["pre_assessment_completed"] or 0)),
        },
        "progress": progress,
        "latest": latest,
        "pendingShortAnswer": pending_short_answer,
        "latestScoredAttempt": latest_scored_attempt,
    }
    return api_ok(payload)


@teacher_bp.get("/api/teacher/students/<student_id>/expert-trace")
def teacher_student_expert_trace(student_id):
    user, err = require_role("teacher")
    if err:
        return err
    del user

    with db_cursor(True) as (_, cur):
        cur.execute(
            """
            SELECT s.id,s.full_name,s.grade,s.section,s.class_level,s.pre_score,s.pre_assessment_completed,u.email
            FROM students s
            JOIN users u ON u.id=s.user_id
            WHERE s.id=%s
            """,
            (student_id,),
        )
        student = cur.fetchone()
        if not student:
            return api_error("Student not found.", 404)

        progress = fetch_student_progress(cur, student_id)
        latest = progress[-1] if progress else None
        pre_assessment_trace = build_pre_assessment_trace(student.get("pre_score") or 0)
        current_class_level = normalize_class_level(
            pre_assessment_trace.get("result", {}).get("classLevel")
            or student["class_level"]
        )

        prediction_trace = None
        cur.execute(
            """
            SELECT p.title, p.text
            FROM quiz_attempts qa
            JOIN passages p ON p.id = qa.passage_id
            WHERE qa.student_id=%s
            ORDER BY qa.submitted_at DESC, qa.id DESC
            LIMIT 1
            """,
            (student_id,),
        )
        latest_attempt = cur.fetchone()
        if latest_attempt and (latest_attempt.get("text") or "").strip():
            prediction_trace = build_passage_prediction_trace(latest_attempt.get("text") or "")
            prediction_trace["passage"] = {
                "title": latest_attempt.get("title") or "Latest passage",
            }

        weekly_progress_trace = None
        if latest:
            recommendation, target_level = recommendation_for_score(
                latest.get("score") or 0,
                current_class_level,
            )
            baseline_score = int(student.get("pre_score") or 0) if bool(int(student.get("pre_assessment_completed") or 0)) else None
            latest_score = int(latest.get("score") or 0)
            estimated_wpm = None
            estimated_reading_minutes = None

            cur.execute(
                """
                SELECT p.words, p.est_minutes
                FROM quiz_attempts qa
                JOIN passages p ON p.id = qa.passage_id
                WHERE qa.student_id=%s
                ORDER BY qa.submitted_at DESC, qa.id DESC
                LIMIT 1
                """,
                (student_id,),
            )
            latest_passage = cur.fetchone()
            if latest_passage:
                estimated_reading_minutes = latest_passage.get("est_minutes")
                estimated_wpm = calculate_wpm(
                    latest_passage.get("words") or 0,
                    reading_time_minutes=estimated_reading_minutes,
                )

            gain = calculate_gain(latest_score, baseline_score) if baseline_score is not None else None
            normalized_gain = calculate_normalized_gain(latest_score, baseline_score) if baseline_score is not None else None

            weekly_progress_trace = {
                "week": int(latest.get("week") or 0),
                "averageScore": int(latest.get("score") or 0),
                "previousClassLevel": current_class_level,
                "recommendation": recommendation,
                "nextClassLevel": target_level,
                "applied": bool(int(latest.get("applied") or 0)),
                "growthMetrics": {
                    "baselineScore": baseline_score,
                    "latestScore": latest_score,
                    "weeklyAverageScore": latest_score,
                    "gain": gain,
                    "normalizedGain": normalized_gain,
                    "wpm": estimated_wpm,
                    "estimatedReadingMinutes": estimated_reading_minutes,
                },
            }

        steps = [
            {
                "step": 1,
                "title": "Input",
                "body": f"The teacher begins with Student {student['full_name']}'s pre-assessment score of {int(student['pre_score'] or 0)}. This value is the student's baseline readiness score and is the first piece of information the rule-based system uses to decide where that learner should start in the reading pathway.",
            },
            {
                "step": 2,
                "title": "Normalization",
                "body": "The system checks whether the submitted score is within the valid range of 0 to 100. If it is outside that range, the score is clamped before any class-level decision is made, which keeps the rule engine consistent and prevents invalid scores from producing unreliable results.",
            },
            {
                "step": 3,
                "title": "Threshold Check",
                "body": f"The normalized score is compared against the rule thresholds used by the app. The exact decision applied here is: {pre_assessment_trace['decision']['ruleApplied']}. In practical terms, the system chooses the student’s reading band by deciding whether the score falls into the Easy, Moderate, or Hard range.",
            },
            {
                "step": 4,
                "title": "Final Result",
                "body": f"Once the threshold check is complete, the system assigns the student to the {current_class_level} level. That level becomes the student’s current class placement and is used to guide future passage selection, difficulty balancing, and the next instructional recommendation.",
            },
        ]

        if prediction_trace:
            steps.append(
                {
                    "step": 5,
                    "title": "Passage Prediction Model",
                    "body": (
                        f"The passage classifier reviewed the latest passage text ({prediction_trace['passage']['title']}) and turned it into measurable text features before running the SVM model. It looked at things such as the text length, word count, and cleaned passage content, then used those features to estimate how difficult the passage should be. The model predicted the {prediction_trace['result']['label']} difficulty level with {prediction_trace['result']['confidence']}% confidence, which means it was highly certain about that classification."
                    ),
                }
            )

    payload = {
        "student": {
            "id": student["id"],
            "name": student["full_name"],
            "email": student["email"],
            "grade": student["grade"],
            "section": student["section"],
            "classLevel": current_class_level,
            "preScore": int(student["pre_score"] or 0),
            "preAssessmentCompleted": bool(int(student["pre_assessment_completed"] or 0)),
        },
        "currentClassLevel": current_class_level,
        "preAssessmentTrace": pre_assessment_trace,
        "predictionTrace": prediction_trace,
        "weeklyProgressTrace": weekly_progress_trace,
        "steps": steps,
    }
    return api_ok(payload)


@teacher_bp.get("/api/teacher/students/<student_id>/pending-short-answers")
def teacher_student_pending_short_answers(student_id):
    user, err = require_role("teacher")
    if err:
        return err
    del user

    with db_cursor(True) as (_, cur):
        cur.execute(
            """
            SELECT s.id,s.full_name,s.grade,s.section,s.class_level,u.email
            FROM students s
            JOIN users u ON u.id=s.user_id
            WHERE s.id=%s
            """,
            (student_id,),
        )
        student = cur.fetchone()
        if not student:
            return api_error("Student not found.", 404)

        pending_items = fetch_pending_short_answers(cur, student_id)

    return api_ok(
        {
            "student": {
                "id": student["id"],
                "name": student["full_name"],
                "email": student["email"],
                "grade": student["grade"],
                "section": student["section"],
                "classLevel": student["class_level"],
            },
            "pendingShortAnswers": pending_items,
        }
    )


@teacher_bp.post("/api/teacher/score")
def teacher_score_save():
    user, err = require_role("teacher")
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    student_id = str(payload.get("studentId") or "").strip()
    passage_id = str(payload.get("passageId") or "").strip()
    attempt_id_raw = payload.get("attemptId")
    attempt_id = None
    if attempt_id_raw is not None and str(attempt_id_raw).strip():
        try:
            attempt_id = int(attempt_id_raw)
        except (TypeError, ValueError):
            return api_error("attemptId must be an integer.", 400)

    if not student_id or not passage_id:
        return api_error("studentId and passageId are required.", 400)

    score_raw = payload.get("score")
    try:
        score = int(score_raw)
    except (TypeError, ValueError):
        return api_error("score must be an integer (0 or 1).", 400)

    if score not in (0, 1):
        return api_error("score must be 0 (Incorrect) or 1 (Correct).", 400)

    feedback = normalize_text_value(payload.get("feedback") or "", max_length=2000)

    with db_cursor(True) as (_, cur):
        cur.execute("SELECT id FROM students WHERE id=%s", (student_id,))
        if not cur.fetchone():
            return api_error("Student not found.", 404)

        if attempt_id is None:
            cur.execute(
                """
                SELECT id,week_no
                FROM quiz_attempts
                WHERE student_id=%s AND passage_id=%s AND short_answer_text IS NOT NULL AND teacher_score IS NULL
                ORDER BY submitted_at DESC, id DESC
                LIMIT 1
                """,
                (student_id, passage_id),
            )
        else:
            cur.execute(
                """
                SELECT id,week_no
                FROM quiz_attempts
                WHERE id=%s AND student_id=%s AND passage_id=%s AND short_answer_text IS NOT NULL
                LIMIT 1
                """,
                (attempt_id, student_id, passage_id),
            )
        attempt = cur.fetchone()
        if not attempt:
            return api_error("No short-answer attempt found for this student and passage.", 404)

        cur.execute(
            """
            UPDATE quiz_attempts
            SET teacher_score=%s,
                teacher_feedback=%s,
                teacher_scored_by=%s,
                teacher_scored_at=NOW()
            WHERE id=%s
            """,
            (score, feedback or None, user["id"], attempt["id"]),
        )

        cur.execute(
            """
            SELECT id
            FROM short_answer_responses
            WHERE legacy_quiz_attempt_id=%s
            ORDER BY id DESC
            LIMIT 1
            """,
            (attempt["id"],),
        )
        sar = cur.fetchone()
        if sar:
            cur.execute(
                """
                INSERT INTO short_answer_scores
                  (legacy_quiz_attempt_id, short_answer_response_id, teacher_id, score_binary, feedback, scored_at)
                VALUES (%s,%s,%s,%s,%s,NOW())
                ON DUPLICATE KEY UPDATE
                  teacher_id=VALUES(teacher_id),
                  score_binary=VALUES(score_binary),
                  feedback=VALUES(feedback),
                  scored_at=VALUES(scored_at)
                """,
                (attempt["id"], int(sar["id"]), user["id"], 1 if score == 1 else 0, feedback or None),
            )

        progression = None

        # compute and persist short-answer percent and total percent into scores (when a reading session exists)
        cur.execute("SELECT correct_count,total_count,score_pct,short_answer_text FROM quiz_attempts WHERE id=%s", (attempt["id"],))
        qa_row = cur.fetchone()
        if qa_row:
            correct = int(qa_row.get("correct_count") or 0)
            total = int(qa_row.get("total_count") or 0)
            objective_pct = int(qa_row.get("score_pct") or 0)
            # If we're scoring a short answer, include it as one additional question
            denom = total + 1
            num = correct + (1 if score == 1 else 0)
            short_answer_pct = int(round(((1 if score == 1 else 0) / denom) * 100)) if denom > 0 else None
            total_pct = int(round((num / denom) * 100)) if denom > 0 else None

            # find reading session id for this legacy attempt
            cur.execute("SELECT id FROM reading_sessions WHERE legacy_quiz_attempt_id=%s", (attempt["id"],))
            rs = cur.fetchone()
            if rs and rs.get("id"):
                session_id = int(rs["id"])
                cur.execute(
                    """
                    INSERT INTO scores (legacy_quiz_attempt_id, session_id, objective_score_pct, short_answer_score_pct, total_score_pct, computed_at)
                    VALUES (%s,%s,%s,%s,%s,NOW())
                    ON DUPLICATE KEY UPDATE
                      objective_score_pct=VALUES(objective_score_pct),
                      short_answer_score_pct=VALUES(short_answer_score_pct),
                      total_score_pct=VALUES(total_score_pct),
                      computed_at=VALUES(computed_at)
                    """,
                    (attempt["id"], session_id, objective_pct, short_answer_pct, total_pct),
                )

                progression = apply_weekly_level_progression(cur, student_id, attempt["week_no"])

        cur.execute(
            """
            SELECT qa.id,qa.student_id,qa.passage_id,qa.week_no,qa.teacher_score,qa.teacher_feedback,
                   qa.teacher_scored_at,u.full_name AS scorer_name
            FROM quiz_attempts qa
            LEFT JOIN students u ON u.user_id=qa.teacher_scored_by
            WHERE qa.id=%s
            """,
            (attempt["id"],),
        )
        saved = cur.fetchone()

    _record_audit_log(user["id"], student_id, "teacher_score", {"passageId": passage_id, "attemptId": int(attempt["id"]), "score": int(score), "hasFeedback": bool(feedback)})
    return api_ok(
        {
            "attemptId": int(saved["id"]),
            "studentId": saved["student_id"],
            "passageId": saved["passage_id"],
            "week": int(saved["week_no"]),
            "score": int(saved["teacher_score"]),
            "feedback": saved.get("teacher_feedback") or "",
            "scoredBy": saved.get("scorer_name"),
            "scoredAt": saved["teacher_scored_at"].isoformat() if saved.get("teacher_scored_at") else None,
            "progression": progression,
        }
    )

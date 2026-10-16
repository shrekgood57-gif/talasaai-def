import argparse
from datetime import datetime, timezone
from getpass import getpass
from pathlib import Path
import sys

from werkzeug.security import generate_password_hash

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db import mysql_config
import mysql.connector


TOTAL_PROGRAM_WEEKS = 8


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create students with two non-improving weekly quiz scores."
    )
    parser.add_argument("--email", required=True, help="New student's login email.")
    parser.add_argument("--name", required=True, help="Student's full name.")
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of students to create (default: 1).",
    )
    parser.add_argument("--grade", default="7", help="Student's grade (default: 7).")
    parser.add_argument(
        "--section", default="Stagnant Demo", help="Student's section."
    )
    parser.add_argument(
        "--class-level",
        default="EASY",
        choices=("EASY", "MODERATE", "HARD"),
        help="Must have weekly assignments for the selected weeks (default: EASY).",
    )
    parser.add_argument(
        "--previous-score",
        type=int,
        default=60,
        help="Score for the earlier week, from 0 to 100 (default: 60).",
    )
    parser.add_argument(
        "--latest-score",
        type=int,
        default=55,
        help="Score for the latest week; must not exceed previous score (default: 55).",
    )
    return parser.parse_args()


def validate_args(args):
    email = args.email.strip().lower()
    name = args.name.strip()
    if not email or len(email) > 255:
        raise ValueError("Email must contain 1 to 255 characters.")
    if not name or len(name) > 255:
        raise ValueError("Name must contain 1 to 255 characters.")
    if not args.grade.strip() or len(args.grade.strip()) > 20:
        raise ValueError("Grade must contain 1 to 20 characters.")
    if len(args.section) > 100:
        raise ValueError("Section must be no longer than 100 characters.")
    if args.count < 1:
        raise ValueError("Count must be at least 1.")
    if args.count > 50:
        raise ValueError("Count must not exceed 50.")
    if not 0 <= args.latest_score <= args.previous_score <= 100:
        raise ValueError(
            "Scores must be from 0 to 100, and latest score must not exceed "
            "the previous score."
        )
    return email, name


def get_active_week(cur):
    cur.execute(
        "SELECT program_start_date, manual_override_week "
        "FROM program_settings WHERE id=1"
    )
    settings = cur.fetchone()
    if not settings:
        raise RuntimeError(
            "Program settings are not initialized. Initialize the app database "
            "before running this seed script."
        )

    override_week = settings["manual_override_week"]
    if override_week is not None:
        return min(TOTAL_PROGRAM_WEEKS, max(1, int(override_week)))

    start_date = settings["program_start_date"]
    days_elapsed = (datetime.now(timezone.utc).date() - start_date).days
    return min(TOTAL_PROGRAM_WEEKS, max(1, (days_elapsed // 7) + 1))


def next_student_id(cur):
    cur.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTRING(id,2) AS UNSIGNED)),0) AS max_id "
        "FROM students WHERE id REGEXP '^s[0-9]+$'"
    )
    return f"s{int(cur.fetchone()['max_id'] or 0) + 1}"


def make_student_accounts(cur, base_email, base_name, count):
    local_part, separator, domain = base_email.partition("@")
    if (
        not separator
        or not local_part
        or not domain
        or "@" in domain
        or any(char.isspace() for char in base_email)
    ):
        raise ValueError("Email must be a valid address with a local part and domain.")

    accounts = []
    suffix = 1
    while len(accounts) < count:
        email = (
            base_email
            if suffix == 1
            else f"{local_part}+{suffix}@{domain}"
        )
        name = base_name if suffix == 1 else f"{base_name} {suffix}"
        if len(email) > 255:
            raise ValueError("Generated email address exceeds 255 characters.")
        if len(name) > 255:
            raise ValueError("Generated student name exceeds 255 characters.")

        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if not cur.fetchone():
            accounts.append((name, email))
        suffix += 1

    return accounts


def main():
    args = parse_args()
    email, name = validate_args(args)
    password = getpass("New student's password: ")
    if not password:
        raise ValueError("Password must not be empty.")
    if password != getpass("Confirm password: "):
        raise ValueError("Passwords do not match.")

    conn = mysql.connector.connect(**mysql_config(), autocommit=False)
    cur = conn.cursor(dictionary=True)
    try:
        active_week = get_active_week(cur)
        latest_week = max(active_week, 2)
        previous_week = latest_week - 1
        attempts = []
        fallback_weeks = []
        for week in (previous_week, latest_week):
            cur.execute(
                """
                SELECT wa.passage_id, p.title
                FROM weekly_assignments wa
                JOIN passages p ON p.id=wa.passage_id
                WHERE wa.week_no=%s AND wa.class_level=%s AND p.is_draft=0
                ORDER BY wa.id
                LIMIT 1
                """,
                (week, args.class_level),
            )
            passage = cur.fetchone()
            if not passage:
                cur.execute(
                    """
                    SELECT id AS passage_id, title
                    FROM passages
                    WHERE label=%s AND is_draft=0
                    ORDER BY id
                    LIMIT 1
                    """,
                    (args.class_level,),
                )
                passage = cur.fetchone()
                if not passage:
                    raise RuntimeError(
                        f"No published {args.class_level} passage is available "
                        f"for the Week {week} seed attempt."
                    )
                fallback_weeks.append(week)
            attempts.append((week, passage))

        accounts = make_student_accounts(cur, email, name, args.count)
        created_students = []
        for student_name, student_email in accounts:
            student_id = next_student_id(cur)
            cur.execute(
                """
                INSERT INTO users (email, password_hash, role, is_active)
                VALUES (%s, %s, 'student', 1)
                """,
                (student_email, generate_password_hash(password)),
            )
            user_id = cur.lastrowid
            cur.execute(
                """
                INSERT INTO students
                    (id, user_id, full_name, grade, section, class_level,
                     pre_score, pre_assessment_completed)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
                """,
                (
                    student_id,
                    user_id,
                    student_name,
                    args.grade.strip(),
                    args.section,
                    args.class_level,
                    args.previous_score,
                ),
            )

            for (week, passage), score in zip(
                attempts, (args.previous_score, args.latest_score)
            ):
                cur.execute(
                    """
                    INSERT INTO quiz_attempts
                        (student_id, passage_id, week_no, score_pct,
                         correct_count, total_count)
                    VALUES (%s, %s, %s, %s, %s, 100)
                    """,
                    (student_id, passage["passage_id"], week, score, score),
                )
            created_students.append((student_name, student_id, student_email))

        conn.commit()
        for student_name, student_id, student_email in created_students:
            print(
                f"Created stagnant student {student_name} "
                f"({student_id}, {student_email})."
            )
        print(
            f"Weekly scores: Week {previous_week} {args.previous_score}% "
            f"to Week {latest_week} {args.latest_score}%."
        )
        if fallback_weeks:
            weeks = ", ".join(str(week) for week in fallback_weeks)
            print(
                f"Note: Week {weeks} had no {args.class_level} assignment; "
                "a published passage of that level was used instead."
            )
        print(
            f"All {len(accounts)} students should appear in the teacher report "
            "and dashboard's stagnant-learning alerts."
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, mysql.connector.Error) as exc:
        print(f"Seed failed: {exc}", file=sys.stderr)
        sys.exit(1)

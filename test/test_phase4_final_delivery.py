from contextlib import nullcontext
import unittest
from unittest.mock import patch

from app import app
import routes.teacher_routes as teacher_routes
from scripts.seed_stagnant_student import make_student_accounts


class Phase4FinalDeliveryTests(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def login(self, email, password, role):
        response = self.client.post("/api/auth/login", json={"email": email, "password": password, "role": role})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        return body["data"]["token"]

    def valid_objective_responses(self, token, passage_id):
        response = self.client.get(
            "/api/passages/" + passage_id,
            headers={"X-Auth-Token": token},
        )
        self.assertEqual(response.status_code, 200)
        questions = response.get_json()["data"]["assessment"]["questions"]
        answers = []
        for question in questions:
            value = question["answerIndex"] if question["type"] in {"multiple_choice", "multiple_choice_harder"} else question["answerKey"]
            answers.append({"type": question["type"], "value": value})
        return answers, len(questions)

    def test_stagnant_students_are_in_dashboard_pending_actions_data(self):
        class DashboardCursor:
            def execute(self, query):
                pass

            def fetchall(self):
                return []

        student = {
            "id": "s88",
            "name": "Stagnant Demo",
            "grade": "7",
            "section": "Demo",
            "classLevel": "EASY",
            "pendingReviewCount": 0,
            "progress": [
                {"week": 5, "score": 60},
                {"week": 6, "score": 55},
            ],
        }
        with (
            patch.object(teacher_routes, "require_role", return_value=(None, None)),
            patch.object(
                teacher_routes,
                "db_cursor",
                return_value=nullcontext((None, DashboardCursor())),
            ),
            patch.object(
                teacher_routes,
                "fetch_teacher_student_summaries",
                return_value=[student],
            ),
            app.test_request_context("/api/teacher/dashboard"),
        ):
            response, status = teacher_routes.teacher_dashboard()

        self.assertEqual(status, 200)
        payload = response.get_json()["data"]
        self.assertEqual(
            payload["stagnantStudents"],
            [
                {
                    "id": "s88",
                    "name": "Stagnant Demo",
                    "grade": "7",
                    "section": "Demo",
                    "stagnantReason": "No improvement from Week 5 (60%) to Week 6 (55).",
                }
            ],
        )

    def test_batch_stagnant_student_emails_skip_existing_accounts(self):
        class ExistingEmailCursor:
            def __init__(self):
                self.email = None

            def execute(self, query, params):
                self.email = params[0]

            def fetchone(self):
                return {"id": 1} if self.email in {
                    "stagnant@example.com",
                    "stagnant+2@example.com",
                } else None

        accounts = make_student_accounts(
            ExistingEmailCursor(), "stagnant@example.com", "Stagnant Student", 3
        )
        self.assertEqual(
            accounts,
            [
                ("Stagnant Student 3", "stagnant+3@example.com"),
                ("Stagnant Student 4", "stagnant+4@example.com"),
                ("Stagnant Student 5", "stagnant+5@example.com"),
            ],
        )

    def test_student_login_and_weekly_passages(self):
        token = self.login("juan.delacruz@pnhs.edu", "password123", "student")
        response = self.client.get(
            "/api/student/weekly-passages?week=1",
            headers={"X-Auth-Token": token},
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("passages", body["data"])
        self.assertIsInstance(body["data"]["passages"], list)

    def test_teacher_dashboard_requires_auth(self):
        response = self.client.get("/api/teacher/dashboard")
        self.assertEqual(response.status_code, 401)

        token = self.login("ms.villanueva@pnhs.edu", "teacher123", "teacher")
        response = self.client.get("/api/teacher/dashboard", headers={"X-Auth-Token": token})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("recentSubmissions", body["data"])

    def test_teacher_score_invalid_score_fails(self):
        token = self.login("ms.villanueva@pnhs.edu", "teacher123", "teacher")
        response = self.client.post(
            "/api/teacher/score",
            headers={"X-Auth-Token": token},
            json={"studentId": "s1", "passageId": "p1", "score": 2},
        )
        self.assertEqual(response.status_code, 400)
        body = response.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("score must be", body["error"])

    def test_student_attempts_invalid_passage_fails(self):
        token = self.login("juan.delacruz@pnhs.edu", "password123", "student")
        response = self.client.post(
            "/api/student/attempts",
            headers={"X-Auth-Token": token},
            json={
                "week": 1,
                "passageId": "unknown",
                "score": 100,
                "correct": 3,
                "total": 3,
                "difficulty": 3,
                "shortAnswer": "Test response",
                "readingTime": "5:00",
                "responses": [],
            },
        )
        self.assertEqual(response.status_code, 400)
        body = response.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("Passage is not assigned", body["error"])

    def test_student_attempts_get_returns_latest_result(self):
        token = self.login("juan.delacruz@pnhs.edu", "password123", "student")
        passages_resp = self.client.get(
            "/api/student/weekly-passages?week=1",
            headers={"X-Auth-Token": token},
        )
        self.assertEqual(passages_resp.status_code, 200)
        passages_body = passages_resp.get_json()
        self.assertTrue(passages_body["ok"])
        self.assertGreater(len(passages_body["data"]["passages"]), 0)
        passage_id = passages_body["data"]["passages"][0]["id"]

        response = self.client.post(
            "/api/student/attempts",
            headers={"X-Auth-Token": token},
            json={
                "week": 1,
                "passageId": passage_id,
                "score": 100,
                "correct": 5,
                "total": 5,
                "difficulty": 3,
                "shortAnswer": "",
                "readingTime": "05:00",
                "responses": self.valid_objective_responses(token, passage_id)[0],
            },
        )
        self.assertEqual(response.status_code, 201)

        response = self.client.get(
            "/api/student/attempts?passageId=" + passage_id,
            headers={"X-Auth-Token": token},
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertIsNotNone(body["data"])
        self.assertEqual(body["data"]["score"], 100)
        self.assertEqual(body["data"]["correct"], 5)
        self.assertEqual(body["data"]["total"], 5)

    def test_student_attempt_falls_back_to_reading_session_time(self):
        token = self.login("juan.delacruz@pnhs.edu", "password123", "student")
        passages_resp = self.client.get(
            "/api/student/weekly-passages?week=1",
            headers={"X-Auth-Token": token},
        )
        self.assertEqual(passages_resp.status_code, 200)
        passage_id = passages_resp.get_json()["data"]["passages"][0]["id"]

        reading_time_resp = self.client.post(
            "/api/student/reading-time",
            headers={"X-Auth-Token": token},
            json={
                "week": 1,
                "passageId": passage_id,
                "eventId": "fallback-read-time",
                "readingSeconds": 320,
                "formattedTime": "05:20",
            },
        )
        self.assertEqual(reading_time_resp.status_code, 200)

        response = self.client.post(
            "/api/student/attempts",
            headers={"X-Auth-Token": token},
            json={
                "week": 1,
                "passageId": passage_id,
                "score": 100,
                "correct": 5,
                "total": 5,
                "difficulty": 3,
                "shortAnswer": "",
                "responses": self.valid_objective_responses(token, passage_id)[0],
            },
        )
        self.assertEqual(response.status_code, 201)

        get_response = self.client.get(
            "/api/student/attempts?passageId=" + passage_id,
            headers={"X-Auth-Token": token},
        )
        self.assertEqual(get_response.status_code, 200)
        body = get_response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["readingTime"], "05:20")

    def test_student_attempt_rejects_forged_score(self):
        token = self.login("juan.delacruz@pnhs.edu", "password123", "student")
        passages_resp = self.client.get(
            "/api/student/weekly-passages?week=1",
            headers={"X-Auth-Token": token},
        )
        passage_id = passages_resp.get_json()["data"]["passages"][0]["id"]
        responses, total = self.valid_objective_responses(token, passage_id)
        response = self.client.post(
            "/api/student/attempts",
            headers={"X-Auth-Token": token},
            json={
                "week": 1,
                "passageId": passage_id,
                "score": 99,
                "correct": total,
                "total": total,
                "difficulty": 3,
                "responses": responses,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("does not match", response.get_json()["error"])

    def test_program_week_accessible_by_student(self):
        token = self.login("juan.delacruz@pnhs.edu", "password123", "student")
        response = self.client.get("/api/program/week", headers={"X-Auth-Token": token})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertIn("activeWeek", body["data"])


if __name__ == "__main__":
    unittest.main()

import io
import unittest

from screener import create_app
from screener import ratelimit
from screener.services.gemini import GeminiError

JD = "Python developer with Flask, Docker and AWS experience. Machine learning is a plus."
RESUME = "Python developer. I build Flask APIs and deploy them with Docker on AWS."


class FakeGemini:
    def __init__(self):
        self.prompts = []
        self.fail = False

    def generate_json(self, prompt, schema, system=""):
        self.prompts.append(prompt)
        if self.fail:
            raise GeminiError("Gemini is down.")
        out = {}
        for key, spec in schema["properties"].items():
            out[key] = ["item"] if spec["type"] == "ARRAY" else "text"
        out["unexpected"] = "dropped"
        return out

    def embed(self, text):
        return [1.0, 0.0] if "Python" in text else [0.0, 1.0]


def make_app(with_ai=True, **overrides):
    config = {"TESTING": True, "RATELIMIT_ENABLED": False, "GOOGLE_API_KEY": ""}
    config.update(overrides)
    app = create_app(config)
    if with_ai:
        app.extensions["gemini"] = FakeGemini()
    return app


class RouteTests(unittest.TestCase):
    def setUp(self):
        ratelimit.reset()
        self.app = make_app()
        self.client = self.app.test_client()

    def post_json(self, path, body):
        return self.client.post(path, json=body)

    def test_index_and_health(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        health = self.client.get("/health").get_json()
        self.assertEqual(health["status"], "ok")
        self.assertTrue(health["ai_enabled"])
        self.assertIn("ocr_enabled", health)

    def test_score_resume(self):
        res = self.post_json("/score_resume", {"job_description": JD, "resume_text": RESUME})
        data = res.get_json()
        self.assertEqual(res.status_code, 200)
        self.assertGreater(data["score"], 50)
        self.assertIn("missing_keywords", data)

    def test_score_with_semantic_blends(self):
        res = self.post_json(
            "/score_resume", {"job_description": JD, "resume_text": RESUME, "use_semantic": True}
        )
        data = res.get_json()
        self.assertEqual(data["semantic_score"], 100.0)
        self.assertNotEqual(data["score"], data["keyword_score"])

    def test_bad_bodies_return_400_not_500(self):
        self.assertEqual(self.client.post("/score_resume", data="nope").status_code, 400)
        self.assertEqual(self.post_json("/score_resume", ["list"]).status_code, 400)
        self.assertEqual(self.post_json("/score_resume", {"job_description": JD}).status_code, 400)
        self.assertEqual(
            self.post_json("/score_resume", {"job_description": 5, "resume_text": 6}).status_code, 400
        )

    def test_upload_txt_uppercase_extension(self):
        res = self.client.post(
            "/upload_resume",
            data={"resume_file": (io.BytesIO(b"Python and Docker"), "CV.TXT")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["extracted_text"], "Python and Docker")

    def test_upload_rejects_unsupported_and_missing(self):
        res = self.client.post(
            "/upload_resume",
            data={"resume_file": (io.BytesIO(b"x"), "cv.exe")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.client.post("/upload_resume").status_code, 400)

    def test_analyze_all_returns_clean_schema_and_redacts(self):
        resume = RESUME + " Contact me at secret.person@example.com or +1 415 555 0132."
        res = self.post_json("/analyze_all", {"job_description": JD, "resume_text": resume})
        data = res.get_json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            set(data), {"summary", "strengths", "weaknesses", "questions", "suggestions"}
        )
        sent = self.app.extensions["gemini"].prompts[0]
        self.assertNotIn("secret.person", sent)
        self.assertNotIn("555 0132", sent)
        self.assertEqual(len(self.app.extensions["gemini"].prompts), 1)

    def test_legacy_ai_endpoints_keep_their_shape(self):
        body = {"job_description": JD, "resume_text": RESUME}
        self.assertEqual(
            set(self.post_json("/analyze_resume_ai", body).get_json()),
            {"summary", "strengths", "weaknesses"},
        )
        self.assertEqual(set(self.post_json("/generate_interview_questions", body).get_json()), {"questions"})
        self.assertEqual(set(self.post_json("/suggest_resume_improvements", body).get_json()), {"suggestions"})

    def test_ai_disabled_returns_503(self):
        client = make_app(with_ai=False).test_client()
        res = client.post("/analyze_all", json={"job_description": JD, "resume_text": RESUME})
        self.assertEqual(res.status_code, 503)
        # Keyword scoring still works without a key.
        self.assertEqual(
            client.post("/score_resume", json={"job_description": JD, "resume_text": RESUME}).status_code, 200
        )

    def test_gemini_failure_returns_502_with_safe_message(self):
        self.app.extensions["gemini"].fail = True
        res = self.post_json("/analyze_all", {"job_description": JD, "resume_text": RESUME})
        self.assertEqual(res.status_code, 502)
        self.assertEqual(res.get_json()["error"], "Gemini is down.")

    def test_rank_resumes_orders_and_isolates_errors(self):
        data = {
            "job_description": JD,
            "resume_files": [
                (io.BytesIO(b"Chef and baker"), "weak.txt"),
                (io.BytesIO(RESUME.encode()), "strong.txt"),
                (io.BytesIO(b"x"), "broken.exe"),
            ],
        }
        res = self.client.post("/rank_resumes", data=data, content_type="multipart/form-data")
        results = res.get_json()["results"]
        self.assertEqual(res.status_code, 200)
        self.assertEqual([r["filename"] for r in results], ["strong.txt", "weak.txt", "broken.exe"])
        self.assertEqual(results[0]["rank"], 1)
        self.assertIn("error", results[2])

    def test_rank_requires_inputs(self):
        res = self.client.post("/rank_resumes", data={"job_description": JD}, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 400)

    def test_file_too_large_is_rejected(self):
        app = make_app(MAX_FILE_BYTES=10)
        res = app.test_client().post(
            "/upload_resume",
            data={"resume_file": (io.BytesIO(b"a" * 50), "cv.txt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("5 MB", res.get_json()["error"])

    def test_rate_limit(self):
        app = make_app(RATELIMIT_ENABLED=True, RATELIMIT_AI=(2, 60))
        client = app.test_client()
        body = {"job_description": JD, "resume_text": RESUME}
        codes = [client.post("/analyze_all", json=body).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])


if __name__ == "__main__":
    unittest.main()

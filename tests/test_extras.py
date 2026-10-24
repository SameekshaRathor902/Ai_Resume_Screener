"""Tests for OCR, the Redis rate limiter and the skills vocabulary."""
import io
import os
import tempfile
import unittest

from PIL import Image, ImageDraw, ImageFont

from screener import create_app, ratelimit
from screener.services import skills
from screener.services.parser import NoTextError, ocr_available, ocr_pdf
from screener.services.scoring import score_resume

OCR = ocr_available()


def scanned_pdf(text: str) -> bytes:
    """Make a PDF that contains only an image of text (like a scanned page)."""
    image = Image.new("RGB", (1400, 360), "white")
    ImageDraw.Draw(image).text((40, 120), text, fill="black", font=ImageFont.load_default(size=70))
    buffer = io.BytesIO()
    image.save(buffer, format="PDF")
    return buffer.getvalue()


def make_client(**overrides):
    config = {"TESTING": True, "RATELIMIT_ENABLED": False, "GOOGLE_API_KEY": ""}
    config.update(overrides)
    return create_app(config).test_client()


def upload(client, data: bytes, name="scan.pdf"):
    return client.post(
        "/upload_resume",
        data={"resume_file": (io.BytesIO(data), name)},
        content_type="multipart/form-data",
    )


@unittest.skipUnless(OCR, "tesseract / pytesseract / pypdfium2 not installed")
class OcrTests(unittest.TestCase):
    def test_ocr_reads_scanned_pdf(self):
        text = ocr_pdf(scanned_pdf("Python Developer Docker AWS"))
        self.assertIn("Python", text)
        self.assertIn("Docker", text)

    def test_upload_route_falls_back_to_ocr(self):
        res = upload(make_client(), scanned_pdf("Python Developer Docker AWS"))
        self.assertEqual(res.status_code, 200)
        self.assertIn("Python", res.get_json()["extracted_text"])

    def test_health_reports_ocr(self):
        self.assertTrue(make_client().get("/health").get_json()["ocr_enabled"])

    def test_ocr_budget_limits_batch_scans(self):
        client = make_client(OCR_MAX_FILES_PER_REQUEST=1)
        pdf = scanned_pdf("Python Developer Docker AWS")
        res = client.post(
            "/rank_resumes",
            data={
                "job_description": "Python developer with Docker and AWS",
                "resume_files": [(io.BytesIO(pdf), "a.pdf"), (io.BytesIO(pdf), "b.pdf")],
            },
            content_type="multipart/form-data",
        )
        results = res.get_json()["results"]
        self.assertEqual(len([r for r in results if "error" not in r]), 1)
        self.assertIn("Too many scanned PDFs", [r for r in results if "error" in r][0]["error"])


class OcrDisabledTests(unittest.TestCase):
    def test_disabled_ocr_keeps_the_clear_message(self):
        res = upload(make_client(OCR_ENABLED=False), scanned_pdf("Python"))
        self.assertEqual(res.status_code, 400)
        self.assertIn("no selectable text", res.get_json()["error"])

    def test_no_text_error_is_a_parse_error(self):
        from screener.services.parser import ParseError

        self.assertTrue(issubclass(NoTextError, ParseError))


class FakeRedis:
    def __init__(self, fail=False):
        self.counts, self.expiries, self.fail = {}, {}, fail

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis):
        self.redis, self.ops = redis, []

    def incr(self, key):
        self.ops.append(("incr", key))

    def expire(self, key, seconds):
        self.ops.append(("expire", key, seconds))

    def execute(self):
        if self.redis.fail:
            raise ConnectionError("down")
        results = []
        for op in self.ops:
            if op[0] == "incr":
                self.redis.counts[op[1]] = self.redis.counts.get(op[1], 0) + 1
                results.append(self.redis.counts[op[1]])
            else:
                self.redis.expiries[op[1]] = op[2]
                results.append(True)
        return results


class RedisLimiterTests(unittest.TestCase):
    def test_blocks_after_limit_and_sets_expiry(self):
        fake = FakeRedis()
        backend = ratelimit.RedisBackend(fake)
        results = [backend.hit("1.2.3.4:x", 2, 60) for _ in range(3)]
        self.assertEqual(results[:2], [None, None])
        self.assertIsInstance(results[2], int)
        self.assertTrue(all(v == 61 for v in fake.expiries.values()))

    def test_fails_open_when_redis_is_down(self):
        backend = ratelimit.RedisBackend(FakeRedis(fail=True))
        self.assertIsNone(backend.hit("k", 1, 60))
        self.assertIsNone(backend.hit("k", 1, 60))

    def test_route_uses_the_redis_backend(self):
        app = create_app({"TESTING": True, "RATELIMIT_ENABLED": True, "RATELIMIT_AI": (1, 60), "GOOGLE_API_KEY": ""})
        app.extensions["ratelimit_backend"] = ratelimit.RedisBackend(FakeRedis())
        client = app.test_client()
        body = {"job_description": "x", "resume_text": "y"}
        codes = [client.post("/analyze_all", json=body).status_code for _ in range(2)]
        self.assertEqual(codes, [503, 429])  # 503 = AI off but request counted; 429 = limited

    def test_unreachable_redis_url_falls_back_to_memory(self):
        app = create_app({"TESTING": True, "GOOGLE_API_KEY": "", "REDIS_URL": "redis://127.0.0.1:1/0"})
        self.assertNotIn("ratelimit_backend", app.extensions)


class SkillsTests(unittest.TestCase):
    def test_vocabulary_is_large(self):
        self.assertGreater(len(skills.SKILLS), 300)

    def test_cross_domain_matching(self):
        cases = [
            ("Spring Boot engineer", "engineer who built services in Spring"),
            ("SQL Server experience", "worked with MSSQL"),
            ("A/B testing", "ran a/b tests"),
            ("financial modeling and GAAP", "financial modeling, GAAP reporting"),
            ("Ruby on Rails developer", "developer who wrote Rails apps"),
            ("HIPAA and EHR", "electronic health records, HIPAA"),
        ]
        for job, resume in cases:
            with self.subTest(job=job):
                self.assertEqual(score_resume(job, resume)["score"], 100.0)

    def test_soft_words_are_not_weighted_as_skills(self):
        result = score_resume("leadership and presentation", "python")
        self.assertEqual(result["missing_skills"], [])

    def test_custom_skills_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write("# comment\nbim\nsupply chain planning\ns&op = sales and operations planning\n")
            path = handle.name
        try:
            self.assertEqual(skills.load_custom_skills(path), 3)
        finally:
            os.unlink(path)
        result = score_resume("Need BIM, supply chain planning and S&OP", "BIM, supply chain planning, sales and operations planning")
        self.assertEqual(result["score"], 100.0)
        self.assertIn("BIM".lower(), [k.lower() for k in result["matched_skills"]])

    def test_missing_custom_file_does_not_crash_startup(self):
        app = create_app({"TESTING": True, "GOOGLE_API_KEY": "", "CUSTOM_SKILLS_FILE": "/nonexistent/skills.txt"})
        self.assertEqual(app.test_client().get("/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()

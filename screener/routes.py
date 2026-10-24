"""HTTP routes. Endpoint paths match the original app so existing clients keep working."""
import logging

from flask import Blueprint, current_app, jsonify, render_template, request
from werkzeug.utils import secure_filename

from .ratelimit import rate_limit
from .services.analysis import run_analysis
from .services.gemini import GeminiError
from .services.parser import NoTextError, ParseError, extract_text, ocr_available, ocr_pdf
from .services.privacy import redact_pii
from .services.scoring import combine_scores, cosine, score_resume, semantic_percent

log = logging.getLogger(__name__)
bp = Blueprint("main", __name__)


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# --------------------------------------------------------------------------- helpers
def _client():
    client = current_app.extensions.get("gemini")
    if client is None:
        raise ApiError("AI features are off. Set GOOGLE_API_KEY on the server to turn them on.", 503)
    return client


def _clip(text: str) -> str:
    return text.strip()[: current_app.config["MAX_TEXT_CHARS"]]


def _read_fields() -> tuple:
    """Read and validate job_description and resume_text from a JSON body."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Send a JSON body with job_description and resume_text.")
    job = data.get("job_description")
    resume = data.get("resume_text")
    if not isinstance(job, str) or not isinstance(resume, str) or not job.strip() or not resume.strip():
        raise ApiError("Both job_description and resume_text are required.")
    return _clip(job), _clip(resume), data


def _for_ai(text: str) -> str:
    return redact_pii(text) if current_app.config["REDACT_PII"] else text


def _semantic_score(job: str, resume: str, job_vector=None):
    """Return (semantic_percent, job_vector), or (None, job_vector) if unavailable."""
    client = current_app.extensions.get("gemini")
    if client is None:
        return None, job_vector
    try:
        job_vector = job_vector or client.embed(_for_ai(job))
        resume_vector = client.embed(_for_ai(resume))
        return semantic_percent(cosine(job_vector, resume_vector)), job_vector
    except GeminiError as exc:
        log.warning("Semantic scoring skipped: %s", exc)
        return None, job_vector


def _ocr_ready() -> bool:
    return bool(current_app.config["OCR_ENABLED"]) and ocr_available()


def _read_upload(file_storage, ocr_budget=None) -> tuple:
    """Return (display_name, text, was_truncated) for an uploaded file.

    Scanned PDFs are read with OCR when it is available. ocr_budget is a dict like
    {"left": 3} that caps how many scans one request may OCR.
    """
    name = secure_filename(file_storage.filename or "") or "resume"
    data = file_storage.read(current_app.config["MAX_FILE_BYTES"] + 1)
    if len(data) > current_app.config["MAX_FILE_BYTES"]:
        raise ParseError("The file is larger than 5 MB.")
    try:
        text = extract_text(file_storage.filename or "", data)
    except NoTextError:
        if not _ocr_ready():
            raise
        if ocr_budget is not None:
            if ocr_budget["left"] <= 0:
                raise ParseError(
                    "Too many scanned PDFs in one upload. Upload fewer at a time."
                ) from None
            ocr_budget["left"] -= 1
        text = ocr_pdf(
            data,
            max_pages=current_app.config["OCR_MAX_PAGES"],
            lang=current_app.config["OCR_LANG"],
        )
    limit = current_app.config["MAX_TEXT_CHARS"]
    return name, text[:limit], len(text) > limit


# --------------------------------------------------------------------------- errors
@bp.app_errorhandler(ApiError)
def handle_api_error(exc):
    return jsonify({"error": exc.message}), exc.status


@bp.app_errorhandler(ParseError)
def handle_parse_error(exc):
    return jsonify({"error": str(exc)}), 400


@bp.app_errorhandler(GeminiError)
def handle_gemini_error(exc):
    return jsonify({"error": str(exc)}), 502


@bp.app_errorhandler(413)
def handle_too_large(_exc):
    return jsonify({"error": "The upload is too large (20 MB maximum in total)."}), 413


# --------------------------------------------------------------------------- pages
@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "ai_enabled": current_app.extensions.get("gemini") is not None,
            "ocr_enabled": _ocr_ready(),
        }
    )


# --------------------------------------------------------------------------- upload + score
@bp.post("/upload_resume")
@rate_limit()
def upload_resume():
    file = request.files.get("resume_file")
    if file is None:
        raise ApiError("No file part in the request.")
    if not file.filename:
        raise ApiError("No file selected.")
    name, text, truncated = _read_upload(file, {"left": 1})
    return jsonify({"extracted_text": text, "filename": name, "truncated": truncated})


@bp.post("/score_resume")
@rate_limit()
def api_score_resume():
    job, resume, data = _read_fields()
    result = score_resume(job, resume)
    if "error" in result:
        raise ApiError(result["error"])

    result["keyword_score"] = result["score"]
    result["semantic_score"] = None
    if data.get("use_semantic") is True:
        semantic, _ = _semantic_score(job, resume)
        result["semantic_score"] = semantic
        result["score"] = combine_scores(result["keyword_score"], semantic)
    return jsonify(result)


# --------------------------------------------------------------------------- AI features
def _ai_response(sections: list):
    job, resume, _ = _read_fields()
    client = _client()
    return jsonify(run_analysis(client, _for_ai(job), _for_ai(resume), sections))


@bp.post("/analyze_resume_ai")
@rate_limit("RATELIMIT_AI")
def analyze_resume_ai():
    return _ai_response(["analysis"])


@bp.post("/generate_interview_questions")
@rate_limit("RATELIMIT_AI")
def generate_interview_questions():
    return _ai_response(["questions"])


@bp.post("/suggest_resume_improvements")
@rate_limit("RATELIMIT_AI")
def suggest_resume_improvements():
    return _ai_response(["suggestions"])


@bp.post("/analyze_all")
@rate_limit("RATELIMIT_AI")
def analyze_all():
    """Review + interview questions + suggestions in a single Gemini request."""
    return _ai_response(["analysis", "questions", "suggestions"])


# --------------------------------------------------------------------------- batch ranking
@bp.post("/rank_resumes")
@rate_limit()
def rank_resumes():
    job = _clip(request.form.get("job_description") or "")
    files = [f for f in request.files.getlist("resume_files") if f and f.filename]
    if not job:
        raise ApiError("A job description is required.")
    if not files:
        raise ApiError("Add at least one resume file.")
    max_files = current_app.config["MAX_RANK_FILES"]
    if len(files) > max_files:
        raise ApiError(f"You can rank up to {max_files} resumes at a time.")

    use_semantic = request.form.get("use_semantic") == "true"
    job_vector = None
    rows = []
    ocr_budget = {"left": current_app.config["OCR_MAX_FILES_PER_REQUEST"]}

    for file in files:
        try:
            name, text, _ = _read_upload(file, ocr_budget)
        except ParseError as exc:
            rows.append({"filename": secure_filename(file.filename) or "resume", "error": str(exc)})
            continue

        result = score_resume(job, text)
        if "error" in result:
            raise ApiError(result["error"])

        score = result["score"]
        semantic = None
        if use_semantic:
            semantic, job_vector = _semantic_score(job, text, job_vector)
            score = combine_scores(score, semantic)

        rows.append(
            {
                "filename": name,
                "score": score,
                "keyword_score": result["score"],
                "semantic_score": semantic,
                "skill_score": result["skill_score"],
                "matched_count": len(result["matched_keywords"]),
                "missing_count": len(result["missing_keywords"]),
                "missing_skills": result["missing_skills"][:8],
                "matched_skills": result["matched_skills"][:8],
                "text": text,
            }
        )

    scored = sorted((r for r in rows if "error" not in r), key=lambda r: -r["score"])
    for position, row in enumerate(scored, start=1):
        row["rank"] = position
    failed = [r for r in rows if "error" in r]
    return jsonify({"results": scored + failed})

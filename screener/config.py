"""Application configuration, read from environment variables (or a .env file)."""
import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional at runtime
    pass


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # --- Gemini ---
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    GEMINI_EMBED_MODEL = os.environ.get("GEMINI_EMBED_MODEL", "text-embedding-004")
    GEMINI_TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT", "30"))

    # --- Uploads and input limits ---
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # whole request (covers batch uploads)
    MAX_FILE_BYTES = 5 * 1024 * 1024  # one resume file
    MAX_TEXT_CHARS = 20_000  # per job description / resume
    MAX_RANK_FILES = 20

    # --- OCR for scanned PDFs (needs the tesseract program installed) ---
    OCR_ENABLED = _bool("OCR_ENABLED", True)
    OCR_MAX_PAGES = int(os.environ.get("OCR_MAX_PAGES", "5"))
    OCR_LANG = os.environ.get("OCR_LANG", "eng")
    OCR_MAX_FILES_PER_REQUEST = 3  # OCR is slow, so cap scans per batch upload

    # --- Optional extras ---
    CUSTOM_SKILLS_FILE = os.environ.get("CUSTOM_SKILLS_FILE", "")
    REDIS_URL = os.environ.get("REDIS_URL", "")  # shared rate limiting across workers

    # --- Privacy ---
    # Remove emails, phone numbers and links before text is sent to Gemini.
    REDACT_PII = _bool("REDACT_PII", True)

    # --- Rate limiting (in-memory, per process) ---
    RATELIMIT_ENABLED = _bool("RATELIMIT_ENABLED", True)
    RATELIMIT_AI = (10, 60)  # 10 requests per 60 seconds per client
    RATELIMIT_DEFAULT = (60, 60)

    # Set TRUST_PROXY=true when running behind nginx / a load balancer.
    TRUST_PROXY = _bool("TRUST_PROXY", False)

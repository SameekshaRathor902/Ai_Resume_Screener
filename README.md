# Resume Screener

A Flask web app that scores resumes against a job description, shows which keywords and technical skills are present or missing, and (optionally) uses Google Gemini for a written review, interview questions and resume suggestions.

## What it does

- **Upload or paste** resumes as `.pdf`, `.docx` or `.txt` (tables in Word files are read too).
- **Scanned PDFs are read with OCR** (Tesseract) when it is installed. Up to 5 pages per file and 3 scans per batch upload, because OCR is slow.
- **Weighted keyword score (0-100).** Recognised technical skills count three times as much as generic words. The built-in list has about 400 skills across software, data, cloud, security, design, QA, product, business, marketing, finance, HR and healthcare. Aliases match (`JS` = JavaScript, `k8s` = Kubernetes, `Postgres` = PostgreSQL), multi-word skills such as "machine learning" and "REST API" are one term, and word forms match (develop / developer / developing).
- **Compare several resumes.** Upload up to 20 files, get a ranked table, download it as CSV.
- **Optional semantic score.** Tick "compare meaning" to blend in an embedding-based similarity score (70% keywords, 30% meaning).
- **AI review in one request.** Summary, strengths, weaknesses, suggested changes and interview questions come from a single Gemini call.

Without a Gemini key everything except the AI features still works.

## Run it

Requires **Python 3.10 or newer**. Check with `python3 --version`.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # optional: only needed for the AI features
PORT=5001 python3 app.py           # then open http://127.0.0.1:5001
```

On macOS, port 5000 is used by AirPlay Receiver and shows a "403 Forbidden" error, which is why the example uses 5001. On Windows, set the port with `set PORT=5001` first.

OCR needs the Tesseract program on your computer (the Python packages are in `requirements.txt`):

```bash
brew install tesseract            # macOS
sudo apt install tesseract-ocr    # Ubuntu / Debian
```

Without it the app still works and scanned PDFs get a clear error message.

Production:

```bash
gunicorn "app:app" --bind 0.0.0.0:8000 --workers 2
# or
docker build -t resume-screener .
docker run -p 8000:8000 --env-file .env resume-screener
```

Get a key from [Google AI Studio](https://aistudio.google.com/). **Never commit it.** `.env` is git-ignored.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `GOOGLE_API_KEY` | none | Turns on AI features |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Model for reviews. Check Google's docs, as model names change |
| `GEMINI_EMBED_MODEL` | `text-embedding-004` | Model for the semantic score |
| `GEMINI_TIMEOUT` | `30` | Seconds before a Gemini request gives up |
| `REDACT_PII` | `true` | Remove emails, phone numbers and links before text goes to Gemini |
| `OCR_ENABLED` | `true` | Read scanned PDFs when Tesseract is installed |
| `OCR_MAX_PAGES` | `5` | Pages read per scanned PDF |
| `OCR_LANG` | `eng` | Tesseract language code (that language pack must be installed) |
| `CUSTOM_SKILLS_FILE` | none | Path to your own skills list (see below) |
| `REDIS_URL` | none | Share rate limits across workers, e.g. `redis://localhost:6379/0` |
| `RATELIMIT_ENABLED` | `true` | Per-client request limits |
| `TRUST_PROXY` | `false` | Set `true` only behind a reverse proxy |

## API

All endpoints keep their original paths.

| Endpoint | Body | Returns |
|---|---|---|
| `POST /upload_resume` | form: `resume_file` | `extracted_text`, `filename`, `truncated` |
| `POST /score_resume` | JSON: `job_description`, `resume_text`, optional `use_semantic` | `score`, `keyword_score`, `skill_score`, `matched_keywords`, `missing_keywords`, `matched_skills`, `missing_skills` |
| `POST /rank_resumes` | form: `job_description`, `resume_files` (many), optional `use_semantic` | ranked `results` |
| `POST /analyze_all` | JSON: `job_description`, `resume_text` | `summary`, `strengths`, `weaknesses`, `suggestions`, `questions` |
| `POST /analyze_resume_ai` | same | `summary`, `strengths`, `weaknesses` |
| `POST /generate_interview_questions` | same | `questions` |
| `POST /suggest_resume_improvements` | same | `suggestions` |
| `GET /health` | | `status`, `ai_enabled`, `ocr_enabled` |

Errors are always JSON: `{"error": "message"}`.

## Adding your own skills

The built-in list will not know every tool in every field. Copy `custom_skills.example.txt`, add one skill per line, and point the app at it:

```bash
# in .env
CUSTOM_SKILLS_FILE=my_skills.txt
```

```
bim                                         # a single-word skill
supply chain planning                       # a multi-word skill
s&op = sales and operations planning        # a variant that means the same thing
```

The built-in vocabulary itself lives in `screener/services/skills.py`.

## Project layout

```
app.py                  entry point
screener/
  app_factory.py        create_app()
  config.py             settings from environment
  routes.py             HTTP endpoints
  ratelimit.py          rate limiter (memory, or Redis when REDIS_URL is set)
  services/
    parser.py           pdf / docx / txt text extraction, OCR for scans
    scoring.py          keyword and semantic scoring
    skills.py           skills vocabulary and custom skills loader
    gemini.py           Gemini REST client
    analysis.py         prompts for the AI features
    privacy.py          email / phone / link redaction
templates/index.html    the UI
custom_skills.example.txt  template for your own skills
tests/                  unittest suite
```

## Tests

```bash
python -m unittest discover -s tests -t . -v
```

## Limits and honest caveats

- Keyword scoring is a heuristic. The skills list is broad but not complete, so add your own terms with `CUSTOM_SKILLS_FILE`.
- The semantic score maps cosine similarity onto 0-100 with a fixed range. Treat it as a rough signal, not a calibrated probability.
- OCR is only as good as the scan. Low-resolution, skewed or handwritten pages may come out wrong. Languages other than English need the matching Tesseract language pack.
- Without `REDIS_URL` the rate limiter counts per process, so several workers each get their own allowance. If Redis becomes unreachable the limiter lets requests through rather than blocking everyone.
- Automated screening can be unfair. Use scores to prioritise a person's reading, not to reject candidates, and check the tool against your own hiring data.

## License and credits

Apache-2.0, see `LICENSE`. This project is a rewrite of [AI-Powered-Resume-Screening-and-Scoring-Web-Application](https://github.com/itssahiljmbt/AI-Powered-Resume-Screening-and-Scoring-Web-Application), which is also Apache-2.0. See `NOTICE`.

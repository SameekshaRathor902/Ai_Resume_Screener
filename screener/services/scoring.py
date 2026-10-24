"""Resume-vs-job-description scoring.

Compared with plain word overlap this scorer:
  * recognises multi-word skills ("machine learning", "REST API") as one term
  * treats aliases as equal (JS = JavaScript, K8s = Kubernetes, Postgres = PostgreSQL)
  * matches word forms (develop / developer / developing)
  * weights known technical skills higher than generic words
  * gives repeated JD terms a small boost (the employer mentioned it more than once)
  * can blend in an optional semantic (embedding) similarity score
"""
import math
import re
from collections import Counter

from . import skills
from .skills import ALIASES, DISPLAY, PHRASES, SKILLS

STOP_WORDS = set(
    """
    a about above across after again against all along also although am among an and any are
    around as at be because been before being below between both but by can could did do does
    doing down during each either else etc even ever every few for from further had has have
    having he her here hers him his how however i if in into is it its itself just least less
    like may me might more most much must my no nor not now of off often on once one only or
    other our ours out over own per same shall she should since so some such than that the
    their theirs them then there these they this those though through thus to too under until
    up upon us use used using very via was we were what when where whether which while who
    whom whose why will with within without would yet you your yours
    ability able candidate candidates company excellent good great including include includes
    job join looking need needed opportunity part plus position preferred required requirement
    requirements responsibilities responsibility responsible role seeking strong team teams
    work working works year years experience experienced skills skill knowledge understanding
    know knows familiar familiarity proficient proficiency bonus nice want ideal overview summary
    """.split()
)

_phrase_cache: tuple = (None, None)


def _phrase_re() -> re.Pattern:
    """Compile (and cache) one regex for every known phrase. Rebuilt if custom skills are added."""
    global _phrase_cache
    if _phrase_cache[0] != skills.VERSION:
        pattern = re.compile(
            r"(?<![a-z0-9])(?:"
            + "|".join(re.escape(p) for p in sorted(PHRASES, key=len, reverse=True))
            + r")(?![a-z0-9])"
        )
        _phrase_cache = (skills.VERSION, pattern)
    return _phrase_cache[1]


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#_]*(?:\.[a-z0-9+#_]+)*")
_NUMBER_RE = re.compile(r"^\d+(\.\d+)*$")

_SUFFIXES = (
    "izations", "ization", "ations", "ation", "ments", "ment", "ingly", "ings", "ing",
    "ies", "ied", "ers", "er", "ed", "es", "s",
)


def _stem(word: str) -> str:
    """A tiny suffix stripper: good enough to match develop/developer/developing."""
    if len(word) <= 4 or not word.isalpha():
        return word
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            stem = word[: -len(suffix)]
            if suffix in ("ies", "ied"):
                stem += "y"
            return stem
    return word


def _display(token: str) -> str:
    if token in DISPLAY:
        return DISPLAY[token]
    name = token.replace("_", " ")
    return name.title() if token in SKILLS else name


def _terms(text: str) -> dict:
    """Return {match_key: (display_text, count, is_skill)} for the meaningful terms in text."""
    text = text.lower()
    text = _phrase_re().sub(lambda m: PHRASES[m.group(0)], text)
    text = re.sub(r"[-/]", " ", text)

    counts: Counter = Counter()
    info: dict = {}
    for raw in _TOKEN_RE.findall(text):
        token = ALIASES.get(raw, raw)
        if token in STOP_WORDS or _NUMBER_RE.match(token) or len(token) < 2:
            continue

        is_skill = token in SKILLS
        protected = is_skill or not token.isalpha()
        key = token if protected else _stem(token)
        if key in STOP_WORDS:
            continue

        counts[key] += 1
        info.setdefault(key, (_display(token), is_skill))

    return {key: (info[key][0], counts[key], info[key][1]) for key in counts}


def _weight(count: int, is_skill: bool) -> float:
    base = 3.0 if is_skill else 1.0
    return base * (1 + 0.25 * min(count - 1, 4))


def score_resume(job_description_text: str, resume_text: str) -> dict:
    """Score a resume against a job description using weighted keyword matching.

    Returns a dict with: score (0-100), skill_score (0-100 or None),
    matched_keywords, missing_keywords, matched_skills, missing_skills, total_keywords.
    On bad input it returns {'score': 0.0, ..., 'error': '<message>'}.
    """
    empty = {
        "score": 0.0,
        "skill_score": None,
        "matched_keywords": [],
        "missing_keywords": [],
        "matched_skills": [],
        "missing_skills": [],
        "total_keywords": 0,
    }
    if not job_description_text or not resume_text:
        return {**empty, "error": "Both job description and resume text are required."}

    jd_terms = _terms(job_description_text)
    if not jd_terms:
        return {**empty, "error": "No meaningful keywords found in the job description."}
    resume_keys = set(_terms(resume_text))

    matched, missing = [], []
    for key, (display, count, is_skill) in jd_terms.items():
        entry = (display, _weight(count, is_skill), is_skill)
        (matched if key in resume_keys else missing).append(entry)

    def total(items, skills_only=False):
        return sum(w for _, w, s in items if s or not skills_only)

    jd_total = total(matched) + total(missing)
    score = 100.0 * total(matched) / jd_total

    skills_total = total(matched, True) + total(missing, True)
    # total(..., True) sums only skill entries; non-skill entries have s == False.
    skill_matched = sum(w for _, w, s in matched if s)
    skill_score = round(100.0 * skill_matched / skills_total, 1) if skills_total else None

    def names(items, only_skills=False):
        picked = [(d, w) for d, w, s in items if s or not only_skills]
        picked.sort(key=lambda item: (-item[1], item[0].lower()))
        return [d for d, _ in picked]

    return {
        "score": round(score, 1),
        "skill_score": skill_score,
        "matched_keywords": names(matched),
        "missing_keywords": names(missing),
        "matched_skills": names(matched, True),
        "missing_skills": names(missing, True),
        "total_keywords": len(jd_terms),
    }


# ---------------------------------------------------------------------------
# Optional semantic similarity (needs embeddings from the Gemini client)
# ---------------------------------------------------------------------------
def cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def semantic_percent(cos: float) -> float:
    """Map cosine similarity to 0-100.

    Embeddings of two related documents usually land between 0.4 and 0.9, so the raw
    value is stretched over that range. This is a heuristic, not a calibrated probability.
    """
    return round(max(0.0, min(1.0, (cos - 0.4) / 0.5)) * 100, 1)


def combine_scores(keyword_score: float, semantic_score) -> float:
    """Blend keyword and semantic scores (70/30). Falls back to keywords alone."""
    if semantic_score is None:
        return keyword_score
    return round(0.7 * keyword_score + 0.3 * semantic_score, 1)

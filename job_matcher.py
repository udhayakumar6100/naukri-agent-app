"""
job_matcher.py — Phase 2: AI job matching using FREE Google Gemini API
With detailed error logging to diagnose failures.
"""

import json
import logging
import time
import os
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

MATCH_THRESHOLD = 70
GEMINI_API_URL  = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


def score_jobs(jobs: list, resume_text: str, config: dict) -> list:
    if not jobs:
        return []

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()

    # ── Check API key ────────────────────────────────────────────
    if not api_key:
        logger.error("❌ GEMINI_API_KEY is not set in GitHub Secrets!")
        logger.error("   Go to GitHub → Settings → Secrets → Add GEMINI_API_KEY")
        logger.warning("⚠️  Falling back to keyword-based matching (no AI)")
        return _keyword_match(jobs, config)

    logger.info(f"🤖 AI scoring {len(jobs)} jobs with Gemini...")
    logger.info(f"   API key starts with: {api_key[:8]}...")

    # ── Test API with one job first ───────────────────────────────
    logger.info("   Testing Gemini API connection...")
    test_ok, test_err = _test_api(api_key)
    if not test_ok:
        logger.error(f"❌ Gemini API test failed: {test_err}")
        logger.warning("⚠️  Falling back to keyword-based matching")
        return _keyword_match(jobs, config)

    logger.info("   ✅ Gemini API connection OK")

    # ── Score all jobs ────────────────────────────────────────────
    scored = []
    failed = 0

    for i, job in enumerate(jobs):
        try:
            score, reason = _score_job(api_key, job, resume_text, config)
            job["score"]  = score
            job["reason"] = reason
            scored.append(job)
            logger.info(f"   [{i+1}/{len(jobs)}] {job['title'][:40]} → {score}/100")
            time.sleep(2)  # Respect free tier rate limit
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            logger.warning(f"   ⚠️  HTTP {e.code} for '{job['title']}': {body[:200]}")
            job["score"]  = 0
            job["reason"] = f"API error {e.code}"
            scored.append(job)
            failed += 1
            if e.code == 429:
                logger.warning("   Rate limited — waiting 30 seconds...")
                time.sleep(30)
            elif e.code in (400, 403):
                logger.error(f"   API key issue (HTTP {e.code}) — switching to keyword match")
                remaining = jobs[i+1:]
                kw_matched = _keyword_match(remaining, config)
                scored.extend(kw_matched)
                break
        except Exception as e:
            logger.warning(f"   ⚠️  Error scoring '{job['title']}': {type(e).__name__}: {e}")
            job["score"]  = 0
            job["reason"] = "Scoring error"
            scored.append(job)
            failed += 1

    if failed > 0:
        logger.warning(f"   {failed} jobs failed to score — they show as 0")

    scored.sort(key=lambda x: x["score"], reverse=True)
    good = [j for j in scored if j["score"] >= MATCH_THRESHOLD]
    logger.info(f"✅ {len(good)} good matches (≥{MATCH_THRESHOLD}) out of {len(scored)} scored")
    return good


def _test_api(api_key: str) -> tuple:
    """Quick API test — returns (success, error_message)."""
    try:
        payload = json.dumps({
            "contents": [{"parts": [{"text": "Reply with exactly: {\"score\": 85, \"reason\": \"test ok\"}"}]}],
            "generationConfig": {"maxOutputTokens": 50}
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{GEMINI_API_URL}?key={api_key}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "candidates" in data:
                return True, ""
            return False, f"Unexpected response: {str(data)[:100]}"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        return False, f"HTTP {e.code}: {body[:200]}"
    except Exception as e:
        return False, str(e)


def _score_job(api_key: str, job: dict, resume_text: str, config: dict) -> tuple:
    profile = config["profile"]
    skills  = config["job_search"]["skills"]

    prompt = f"""You are a job matching assistant. Score this job vs the candidate.

JOB:
Title   : {job['title']}
Company : {job['company']}
Location: {job['location']}
Exp Req : {job['exp']}
Skills  : {job['skills']}

CANDIDATE:
Experience : {profile['experience_years']} years
Location   : {profile['current_location']}
Skills     : {', '.join(skills)}
Expected   : {profile['expected_salary_lpa']} LPA

RESUME:
{resume_text[:1200]}

Respond ONLY in JSON (no markdown, no extra text):
{{"score": <number 0-100>, "reason": "<one sentence why>"}}

Scoring: 90-100=perfect, 70-89=good, 50-69=partial, 0-49=poor"""

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 100, "temperature": 0.1}
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{GEMINI_API_URL}?key={api_key}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        parsed = json.loads(raw)
        score  = int(parsed.get("score", 0))
        reason = str(parsed.get("reason", ""))
        return score, reason
    except Exception:
        import re
        m = re.search(r'"score"\s*:\s*(\d+)', raw)
        return (int(m.group(1)) if m else 0), raw[:100]


def _keyword_match(jobs: list, config: dict) -> list:
    """
    Fallback: simple keyword-based matching when Gemini API is unavailable.
    Scores jobs based on skill overlap with candidate profile.
    """
    logger.info("🔤 Using keyword-based matching (Gemini unavailable)...")
    skills = [s.lower() for s in config["job_search"]["skills"]]
    location = config["profile"]["current_location"].lower()
    matched = []

    for job in jobs:
        score  = 50  # Base score
        reason = ""

        job_text = (
            f"{job.get('title','')} {job.get('skills','')} "
            f"{job.get('company','')} {job.get('location','')}"
        ).lower()

        # +5 per matching skill
        skill_hits = sum(1 for s in skills if s in job_text)
        score += skill_hits * 5

        # +10 if location matches
        if location in job_text:
            score += 10

        # +5 for exact title match
        title_lower = job.get('title', '').lower()
        if any(k.lower() in title_lower for k in config["job_search"]["keywords"]):
            score += 5

        score  = min(score, 95)
        reason = f"Keyword match: {skill_hits} skills matched"

        job["score"]  = score
        job["reason"] = reason

        if score >= MATCH_THRESHOLD:
            matched.append(job)
            logger.info(f"   ✅ {job['title'][:40]} → {score}/100 ({reason})")

    matched.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"   {len(matched)} keyword matches (≥{MATCH_THRESHOLD})")
    return matched

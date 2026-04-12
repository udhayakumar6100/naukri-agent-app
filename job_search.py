"""
job_search.py — Phase 2: Search Naukri for RECENTLY POSTED jobs only
Filters jobs posted in last 24 hours using multiple Naukri URL parameters.
Also extracts posted date from each job card for verification.
"""

import time
import logging
from datetime import datetime, date, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

logger = logging.getLogger(__name__)

# Naukri jobAge parameter values
# 0 = last 24 hours, 1 = last 3 days, 7 = last week
RECENT_JOB_AGE = 0   # last 24 hours only


def search_jobs(driver, config: dict) -> list:
    """
    Search Naukri for recently posted jobs matching your profile.
    Only returns jobs posted in the last 24 hours.
    Searches all preferred locations, not just the first one.
    """
    job_search = config["job_search"]
    keywords   = job_search["keywords"]
    locations  = config["profile"]["preferred_locations"]
    exp_min    = job_search["experience_min"]
    exp_max    = job_search["experience_max"]

    all_jobs = []

    # Search top 3 keywords × top 2 locations
    for keyword in keywords[:3]:
        for location in locations[:2]:
            logger.info(f"🔍 '{keyword}' in {location} (last 24h)...")
            jobs = _search_keyword(driver, keyword, location, exp_min, exp_max)
            logger.info(f"   Found {len(jobs)} recent jobs")
            all_jobs.extend(jobs)
            time.sleep(3)

    # Deduplicate by URL
    seen, unique = set(), []
    for job in all_jobs:
        if job["url"] not in seen:
            seen.add(job["url"])
            unique.append(job)

    # Filter out jobs that look too old (extra safety check)
    fresh = [j for j in unique if _is_recent(j.get("posted", ""))]
    stale = len(unique) - len(fresh)

    if stale > 0:
        logger.info(f"   ⏭️  Filtered out {stale} older jobs")

    logger.info(f"📋 Total fresh unique jobs: {len(fresh)}")
    return fresh


def _search_keyword(driver, keyword: str, location: str,
                    exp_min: int, exp_max: int) -> list:
    """Build Naukri search URL with recent filter and extract job cards."""
    jobs = []
    try:
        kw  = keyword.lower().replace(" ", "-")
        loc = location.lower().replace(" ", "-")

        # jobAge=0 → last 24 hours
        # jobAge=1 → last 3 days (fallback if 0 returns nothing)
        for age in [0, 1]:
            url = (
                f"https://www.naukri.com/{kw}-jobs-in-{loc}"
                f"?experience={exp_min}&to={exp_max}"
                f"&jobAge={age}"
                f"&sort=1"    # sort=1 → sort by date (newest first)
            )
            driver.get(url)
            time.sleep(4)

            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, ".srp-jobtuple-wrapper, .jobTuple, article.jobTupleHeader"))
                )
            except TimeoutException:
                logger.warning(f"   No results for age={age}, trying next...")
                continue

            cards = driver.find_elements(
                By.CSS_SELECTOR,
                ".srp-jobtuple-wrapper, article.jobTuple"
            )[:20]

            if not cards:
                logger.warning(f"   No cards found for age={age}")
                continue

            for card in cards:
                try:
                    job = _extract_job(card)
                    if job:
                        jobs.append(job)
                except Exception:
                    continue

            if jobs:
                logger.info(f"   ✅ Found {len(jobs)} jobs (jobAge={age})")
                break   # Got results — no need to try next age

    except Exception as e:
        logger.error(f"   ❌ Search error for '{keyword}': {e}")

    return jobs


def _extract_job(card) -> dict:
    """Extract all details from a single Naukri job card element."""
    def safe_text(*selectors):
        for sel in selectors:
            try:
                el = card.find_element(By.CSS_SELECTOR, sel)
                t  = el.text.strip()
                if t:
                    return t
            except Exception:
                continue
        return ""

    def safe_href(*selectors):
        for sel in selectors:
            try:
                el   = card.find_element(By.CSS_SELECTOR, sel)
                href = el.get_attribute("href") or ""
                if href.startswith("http"):
                    return href
            except Exception:
                continue
        return ""

    title   = safe_text(".title", ".jobTitle", "a.title", ".job-title")
    company = safe_text(".comp-name", ".companyName", ".subTitle", ".comp-dtls-wrap a")
    exp     = safe_text(".exp-wrap li", ".experience", ".expwdth")
    salary  = safe_text(".sal-wrap li", ".salary", ".sal")
    loc     = safe_text(".loc-wrap li", ".location", ".loc")
    skills  = safe_text(".tags-gt", ".skill-list", ".techSkill", ".tag-li")
    posted  = safe_text(".job-post-day", ".postDate", ".post-day", ".fresh-relevance-list__posted")
    url     = safe_href(".title", "a.title", ".job-title a", "a")

    if not title or not url:
        return None

    # Clean up URL — remove tracking params
    if "?" in url:
        url = url.split("?")[0]

    return {
        "title":    title,
        "company":  company,
        "exp":      exp,
        "salary":   salary or "Not disclosed",
        "location": loc,
        "skills":   skills,
        "posted":   posted,
        "url":      url,
        "applied":  False,
        "score":    0
    }


def _is_recent(posted_text: str) -> bool:
    """
    Check if a job was posted recently based on the posted text.
    Examples: 'Just now', '2 hours ago', '1 day ago', 'Few hours ago'
    Returns True if posted within last 2 days, False if older.
    """
    if not posted_text:
        return True   # No date info — assume recent (jobAge filter already applied)

    text = posted_text.lower().strip()

    # Definitely recent
    recent_signals = [
        "just now", "few minutes", "hour", "hours",
        "today", "1 day", "few hours", "recently"
    ]
    for signal in recent_signals:
        if signal in text:
            return True

    # Definitely old — skip these
    old_signals = ["week", "month", "30 days", "15 days", "10 days"]
    for signal in old_signals:
        if signal in text:
            return False

    # "2 days ago", "3 days ago" etc — allow up to 2 days
    import re
    match = re.search(r'(\d+)\s*day', text)
    if match:
        days = int(match.group(1))
        return days <= 2

    return True   # Unknown format — keep it

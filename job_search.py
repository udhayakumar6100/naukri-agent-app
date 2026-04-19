"""
job_search.py — Phase 2: Search Naukri for recent jobs
Searches multiple keywords × locations for maximum job coverage.
"""

import time
import logging
import random
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys

logger = logging.getLogger(__name__)


def search_jobs(driver, config: dict) -> list:
    job_search = config["job_search"]
    keywords   = job_search["keywords"]
    locations  = config["profile"]["preferred_locations"]
    exp_min    = job_search["experience_min"]
    exp_max    = job_search["experience_max"]

    all_jobs = []

    # Search ALL keywords × top 3 locations for maximum coverage
    for keyword in keywords:
        for location in locations[:3]:
            logger.info(f"🔍 '{keyword}' in {location}...")
            jobs = _search(driver, keyword, location, exp_min, exp_max)
            logger.info(f"   Found {len(jobs)} jobs")
            all_jobs.extend(jobs)
            time.sleep(random.uniform(3, 5))

    # Deduplicate by URL
    seen, unique = set(), []
    for job in all_jobs:
        if job["url"] not in seen:
            seen.add(job["url"])
            unique.append(job)

    logger.info(f"📋 Total unique jobs: {len(unique)}")
    return unique


def _search(driver, keyword, location, exp_min, exp_max) -> list:
    jobs = []
    try:
        kw  = keyword.lower().replace(" ", "-")
        loc = location.lower().replace(" ", "-")

        # Try jobAge=1 (last 3 days) first, then jobAge=3 (last week) as fallback
        for job_age in [1, 3]:
            url = (f"https://www.naukri.com/{kw}-jobs-in-{loc}"
                   f"?experience={exp_min}&jobAge={job_age}")
            logger.info(f"   URL (jobAge={job_age}): {url}")
            driver.get(url)
            time.sleep(6)

            _close_popups(driver)

            cards = _find_cards(driver)
            if cards:
                logger.info(f"   ✅ {len(cards)} cards found (jobAge={job_age})")
                for card in cards[:20]:
                    try:
                        job = _extract(card)
                        if job:
                            jobs.append(job)
                    except Exception:
                        continue
                break  # Got results — no need for fallback age
            else:
                logger.warning(f"   No cards found with jobAge={job_age}")

        if not jobs:
            # Final fallback — search via Naukri homepage search box
            logger.info("   Trying homepage search fallback...")
            jobs = _homepage_search(driver, keyword, location)

    except Exception as e:
        logger.error(f"   Search error: {e}")

    return jobs


def _find_cards(driver):
    """Try all known Naukri job card selectors."""
    selectors = [
        'div.srp-jobtuple-wrapper',
        'article.jobTuple',
        'div[class*="srp-jobtuple"]',
        'div[class*="jobTuple"]',
        'div[data-job-id]',
        'article[data-job-id]',
        '.list article',
        '#listContainer article',
        '.jobsList li',
    ]
    for sel in selectors:
        try:
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel))
            )
            cards = driver.find_elements(By.CSS_SELECTOR, sel)
            if cards:
                return cards
        except Exception:
            continue

    # Debug: log classes present on page
    try:
        import re
        src     = driver.page_source[:8000]
        classes = re.findall(r'class="([^"]*(?:job|tuple|srp)[^"]*)"', src, re.IGNORECASE)
        if classes:
            logger.info(f"   Job-related classes on page: {list(set(classes))[:5]}")
        else:
            logger.warning(f"   No job classes found. Current URL: {driver.current_url}")
    except Exception:
        pass

    return []


def _close_popups(driver):
    try:
        for sel in ['[class*="close"]', '[aria-label="close"]',
                    '[aria-label="Close"]', '.modal button']:
            try:
                btns = driver.find_elements(By.CSS_SELECTOR, sel)
                for btn in btns[:1]:
                    btn.click()
                    time.sleep(0.5)
            except Exception:
                pass
    except Exception:
        pass


def _homepage_search(driver, keyword, location) -> list:
    try:
        driver.get("https://www.naukri.com")
        time.sleep(4)

        for sel in ['#qsb-keyword-sugg', 'input[placeholder*="skill"]',
                    'input[placeholder*="Search"]', '.nI-gNb-sb__main input']:
            try:
                sb = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
                sb.clear()
                sb.send_keys(keyword)
                time.sleep(1)

                for lsel in ['#qsb-location-sugg', 'input[placeholder*="ocation"]']:
                    try:
                        lb = driver.find_element(By.CSS_SELECTOR, lsel)
                        lb.clear()
                        lb.send_keys(location)
                        time.sleep(1)
                        break
                    except Exception:
                        pass

                sb.send_keys(Keys.RETURN)
                time.sleep(5)
                cards = _find_cards(driver)
                jobs  = []
                for card in cards[:20]:
                    try:
                        job = _extract(card)
                        if job:
                            jobs.append(job)
                    except Exception:
                        continue
                return jobs
            except Exception:
                continue
    except Exception as e:
        logger.error(f"   Homepage search error: {e}")
    return []


def _extract(card) -> dict:
    def text(*sels):
        for s in sels:
            try:
                t = card.find_element(By.CSS_SELECTOR, s).text.strip()
                if t: return t
            except Exception:
                pass
        return ""

    def link(*sels):
        for s in sels:
            try:
                h = card.find_element(By.CSS_SELECTOR, s).get_attribute("href") or ""
                if h.startswith("http"): return h.split("?")[0]
            except Exception:
                pass
        return ""

    title = text('a.title', 'a[class*="title"]', '.jobTitle a',
                 'h2 a', 'h3 a', '[class*="designation"] a')
    if not title:
        try:
            for a in card.find_elements(By.TAG_NAME, 'a'):
                t = (a.get_attribute('title') or a.text or "").strip()
                if 5 < len(t) < 100:
                    title = t
                    break
        except Exception:
            pass

    company = text('.comp-name', 'a[class*="comp"]', '[class*="company"] a',
                   '[class*="companyName"]')
    exp     = text('[class*="exp"] li', '[class*="experience"]', '.expwdth')
    salary  = text('[class*="sal"] li', '[class*="salary"]')
    loc     = text('[class*="loc"] li', '[class*="location"]', '.locWdth')
    skills  = text('[class*="tag"]', '[class*="skill"]', '[class*="tech"]')
    posted  = text('[class*="postDate"]', '[class*="post-day"]', '.date')
    url     = link('a.title', 'a[class*="title"]', 'h2 a', 'a')

    if not title or not url:
        return None

    return {
        "title":    title,
        "company":  company or "Unknown",
        "exp":      exp,
        "salary":   salary or "Not disclosed",
        "location": loc,
        "skills":   skills,
        "posted":   posted,
        "url":      url,
        "applied":  False,
        "score":    0
    }

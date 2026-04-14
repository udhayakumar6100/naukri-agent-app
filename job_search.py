"""
job_search.py — Phase 2: Search Naukri for recent jobs
Uses Naukri's confirmed working URL format:
  naukri.com/software-developer-jobs-in-chennai?experience=1&jobAge=1
"""

import time
import logging
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
    for keyword in keywords[:3]:
        for location in locations[:2]:
            logger.info(f"🔍 '{keyword}' in {location}...")
            jobs = _search(driver, keyword, location, exp_min, exp_max)
            logger.info(f"   Found {len(jobs)} jobs")
            all_jobs.extend(jobs)
            time.sleep(4)

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
        # Naukri confirmed URL format — e.g. naukri.com/python-developer-jobs-in-chennai
        kw  = keyword.lower().replace(" ", "-")
        loc = location.lower().replace(" ", "-")

        # Try with jobAge=1 (last 3 days) — more results than jobAge=0
        url = f"https://www.naukri.com/{kw}-jobs-in-{loc}?experience={exp_min}&jobAge=1"
        logger.info(f"   Fetching: {url}")
        driver.get(url)
        time.sleep(6)  # Give React app time to render

        # Close any popup/modal that appears
        _close_popups(driver)

        # Check if page loaded correctly
        page_title = driver.title.lower()
        logger.info(f"   Page title: {driver.title}")

        if "naukri" not in driver.current_url:
            logger.warning("   Redirected away from Naukri!")
            return []

        # Wait for job cards — try all known selectors
        cards = _find_job_cards(driver)

        if not cards:
            logger.warning(f"   No cards found with standard selectors — trying search box approach")
            cards = _search_via_homepage(driver, keyword, location)

        logger.info(f"   Extracting {len(cards)} cards...")
        for card in cards[:20]:
            try:
                job = _extract(card)
                if job:
                    jobs.append(job)
            except Exception as e:
                continue

    except Exception as e:
        logger.error(f"   Search error: {e}")

    return jobs


def _close_popups(driver):
    """Close any popup/overlay that might block results."""
    try:
        close_btns = driver.find_elements(By.CSS_SELECTOR,
            '[class*="close"], [class*="modal"] button, '
            '[aria-label="close"], [aria-label="Close"]')
        for btn in close_btns[:2]:
            try:
                btn.click()
                time.sleep(0.5)
            except Exception:
                pass
    except Exception:
        pass


def _find_job_cards(driver):
    """Try all known Naukri job card selectors."""
    selectors = [
        'div.srp-jobtuple-wrapper',
        'article.jobTuple',
        '[class="srp-jobtuple-wrapper"]',
        'div[class*="srp-jobtuple"]',
        'div[class*="jobTuple"]',
        'div[data-job-id]',
        'li[data-job-id]',
        '.list article',
        '.jobsList article',
        '#listContainer article',
    ]

    for sel in selectors:
        try:
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel))
            )
            cards = driver.find_elements(By.CSS_SELECTOR, sel)
            if cards:
                logger.info(f"   ✅ Found {len(cards)} cards with: {sel}")
                return cards
        except Exception:
            continue

    # Log page source for debugging
    try:
        src = driver.page_source
        # Look for known class patterns
        import re
        classes = re.findall(r'class="([^"]*job[^"]*)"', src[:5000], re.IGNORECASE)
        if classes:
            logger.info(f"   Job-related classes found: {classes[:5]}")
        else:
            logger.warning(f"   No job classes found in page. URL: {driver.current_url}")
    except Exception:
        pass

    return []


def _search_via_homepage(driver, keyword, location):
    """Fallback: use Naukri search box directly."""
    try:
        logger.info("   Trying search via homepage...")
        driver.get("https://www.naukri.com")
        time.sleep(4)

        # Find search box
        search_box = None
        for sel in ['#qsb-keyword-sugg', 'input[placeholder*="skill"]',
                    'input[placeholder*="Search"]', '.nI-gNb-sb__main input']:
            try:
                search_box = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
                break
            except Exception:
                continue

        if not search_box:
            return []

        search_box.clear()
        search_box.send_keys(keyword)
        time.sleep(1)

        # Location box
        for sel in ['#qsb-location-sugg', 'input[placeholder*="location"]',
                    'input[placeholder*="Location"]']:
            try:
                loc_box = driver.find_element(By.CSS_SELECTOR, sel)
                loc_box.clear()
                loc_box.send_keys(location)
                time.sleep(1)
                break
            except Exception:
                continue

        # Submit
        search_box.send_keys(Keys.RETURN)
        time.sleep(5)

        return _find_job_cards(driver)

    except Exception as e:
        logger.error(f"   Homepage search failed: {e}")
        return []


def _extract(card) -> dict:
    """Extract job info from a card element."""
    def text(*selectors):
        for s in selectors:
            try:
                t = card.find_element(By.CSS_SELECTOR, s).text.strip()
                if t: return t
            except Exception:
                pass
        return ""

    def link(*selectors):
        for s in selectors:
            try:
                h = card.find_element(By.CSS_SELECTOR, s).get_attribute("href") or ""
                if h.startswith("http"): return h.split("?")[0]
            except Exception:
                pass
        return ""

    title = text(
        'a.title', 'a[class*="title"]', '.jobTitle a',
        'h2 a', 'h3 a', '[class*="designation"] a',
        'a[title]'
    )
    # Fallback: get title from anchor tag text
    if not title:
        try:
            anchors = card.find_elements(By.TAG_NAME, 'a')
            for a in anchors:
                t = a.text.strip()
                if len(t) > 5 and len(t) < 100:
                    title = t
                    break
        except Exception:
            pass

    company = text(
        '.comp-name', 'a[class*="comp"]', '[class*="company"] a',
        '.companyInfo a', '[class*="companyName"]'
    )
    exp    = text('[class*="exp"] li', '[class*="experience"]', '.expwdth')
    salary = text('[class*="sal"] li', '[class*="salary"]', '.salaryInfo')
    loc    = text('[class*="loc"] li', '[class*="location"]', '.locInfo')
    skills = text('[class*="tag"]', '[class*="skill"]', '[class*="tech"]')
    posted = text('[class*="postDate"]', '[class*="post-day"]', '.date')
    url    = link('a.title', 'a[class*="title"]', 'h2 a', 'a')

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

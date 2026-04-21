"""
job_apply.py — Phase 3: Auto-apply to matched jobs
Correctly distinguishes between:
  - Applied on Naukri directly → "applied"
  - Redirects to company portal → "manual"  
  - Opens company portal in new tab → "manual"
  - No apply button found → "failed"
"""

import time
import logging
import json
import os
import random
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

logger = logging.getLogger(__name__)
APPLIED_LOG = "logs/applied_jobs.json"

# Domains that indicate a company's own portal
EXTERNAL_DOMAINS = [
    "greenhouse.io", "lever.co", "workday.com", "taleo.net",
    "successfactors.com", "icims.com", "jobvite.com", "smartrecruiters.com",
    "myworkdayjobs.com", "careers.", "jobs.", "apply.", "recruit.",
    "linkedin.com", "instahyre.com", "hirist.com", "freshteam.com",
    "zohorecruit.com", "keka.com", "darwinbox.com", "bamboohr.com",
    "recruitcrm.io", "peoplestrong.com",
]


def load_applied_jobs() -> set:
    if os.path.exists(APPLIED_LOG):
        try:
            with open(APPLIED_LOG, "r") as f:
                return set(json.load(f).get("urls", []))
        except Exception:
            return set()
    return set()


def save_applied_job(url, title, company):
    os.makedirs("logs", exist_ok=True)
    data = {}
    if os.path.exists(APPLIED_LOG):
        try:
            with open(APPLIED_LOG, "r") as f:
                data = json.load(f)
        except Exception:
            data = {}
    urls    = data.get("urls", [])
    details = data.get("details", [])
    if url not in urls:
        urls.append(url)
        details.append({
            "title": title, "company": company, "url": url,
            "applied_on": datetime.now().strftime("%Y-%m-%d %H:%M")
        })
    with open(APPLIED_LOG, "w") as f:
        json.dump({"urls": urls, "details": details}, f, indent=2)


def apply_to_jobs(driver, matched_jobs: list, config: dict) -> dict:
    daily_cap       = config["job_search"].get("max_applications_per_day", 20)
    already_done    = load_applied_jobs()

    # Also skip jobs already in manual list
    try:
        from job_tracker import load_jobs_data
        jd = load_jobs_data()
        already_done |= set(j["url"] for j in jd.get("manual_jobs", []))
    except Exception:
        pass

    new_jobs = [j for j in matched_jobs if j["url"] not in already_done]
    results  = {"applied": [], "manual": [], "failed": [], "total_applied": 0}

    logger.info(f"📨 {len(new_jobs)} new jobs to process (cap: {daily_cap})")

    for job in new_jobs:
        if results["total_applied"] >= daily_cap:
            logger.info("   ⏹️  Daily cap reached.")
            break

        title, company, url = job["title"], job["company"], job["url"]
        logger.info(f"   📩 Processing: {title} @ {company}")

        result = _apply_single(driver, job)

        if result == "applied":
            save_applied_job(url, title, company)
            results["applied"].append(job)
            results["total_applied"] += 1
            logger.info(f"   ✅ Applied on Naukri directly!")

        elif result == "manual":
            try:
                from job_tracker import save_manual_job
                save_manual_job(job)
            except Exception:
                pass
            results["manual"].append(job)
            logger.info(f"   📌 Saved to Manual Apply list (company portal)")

        else:
            results["failed"].append(job)
            logger.warning(f"   ❌ Failed to apply")

        time.sleep(random.uniform(8, 15))

    logger.info(
        f"✅ Done — Applied on Naukri: {results['total_applied']}, "
        f"Manual (company portal): {len(results['manual'])}, "
        f"Failed: {len(results['failed'])}"
    )
    return results


def _apply_single(driver, job: dict) -> str:
    """
    Try to apply to a job.
    Returns: 'applied' | 'manual' | 'failed'
    
    'applied' = successfully applied directly through Naukri
    'manual'  = job requires applying on company's own website
    'failed'  = couldn't find apply button or error occurred
    """
    url = job["url"]
    try:
        # Record tabs before clicking Apply
        driver.get(url)
        time.sleep(3)
        original_url   = driver.current_url
        original_tabs  = set(driver.window_handles)

        # ── Find Apply button ──────────────────────────────────────
        apply_btn = None
        apply_btn_text = ""
        for by, loc in [
            (By.XPATH, '//button[contains(text(),"Apply")]'),
            (By.XPATH, '//a[contains(text(),"Apply")]'),
            (By.CSS_SELECTOR, 'button.apply-button'),
            (By.CSS_SELECTOR, '#apply-button'),
            (By.XPATH, '//button[contains(text(),"Easy Apply")]'),
            (By.XPATH, '//button[contains(@class,"apply")]'),
        ]:
            try:
                apply_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((by, loc)))
                apply_btn_text = apply_btn.text.lower()
                break
            except Exception:
                continue

        if not apply_btn:
            logger.info(f"   No Apply button found")
            return "failed"

        # Already applied through Naukri?
        if "applied" in apply_btn_text:
            logger.info(f"   Already applied (Naukri shows 'Applied')")
            return "applied"

        # ── Click Apply ────────────────────────────────────────────
        driver.execute_script("arguments[0].click();", apply_btn)
        time.sleep(4)

        # ── Check result ───────────────────────────────────────────
        current_url  = driver.current_url
        current_tabs = set(driver.window_handles)
        new_tabs     = current_tabs - original_tabs

        # Case 1: New tab opened → company portal
        if new_tabs:
            new_tab_url = ""
            try:
                driver.switch_to.window(list(new_tabs)[0])
                new_tab_url = driver.current_url
                driver.close()
                driver.switch_to.window(list(original_tabs)[0])
            except Exception:
                pass
            logger.info(f"   🔗 New tab opened: {new_tab_url[:60]}")
            job["company_portal_url"] = new_tab_url
            return "manual"

        # Case 2: Redirected away from Naukri → company portal
        if _is_external_redirect(original_url, current_url):
            logger.info(f"   🔗 Redirected to: {current_url[:60]}")
            job["company_portal_url"] = current_url
            try:
                driver.back()
                time.sleep(2)
            except Exception:
                pass
            return "manual"

        # Case 3: Still on Naukri — check for success confirmation
        page_source = driver.page_source.lower()

        # Strong success indicators
        if any(phrase in page_source for phrase in [
            "successfully applied", "application submitted",
            "applied successfully", "thank you for applying",
            "your application has been", "application received"
        ]):
            return "applied"

        # Check if button now says "Applied"
        try:
            new_btn_text = apply_btn.text.lower()
            if "applied" in new_btn_text:
                return "applied"
        except Exception:
            pass

        # Still on Naukri with no error → assume applied
        if "naukri.com" in current_url and "login" not in current_url:
            _handle_popup(driver)
            return "applied"

        return "failed"

    except Exception as e:
        logger.error(f"      Error: {e}")
        return "failed"


def _is_external_redirect(original_url: str, current_url: str) -> bool:
    if "naukri.com" not in current_url:
        return True
    for domain in EXTERNAL_DOMAINS:
        if domain in current_url:
            return True
    return False


def _handle_popup(driver):
    for by, loc in [
        (By.XPATH, '//button[contains(text(),"Apply")]'),
        (By.XPATH, '//button[contains(text(),"Confirm")]'),
        (By.XPATH, '//button[contains(text(),"Submit")]'),
    ]:
        try:
            btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((by, loc)))
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(2)
            break
        except Exception:
            continue

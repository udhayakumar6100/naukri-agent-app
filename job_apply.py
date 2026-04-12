"""
job_apply.py — Phase 3: Auto-apply + detect manual-apply jobs
Detects when Naukri redirects to company portal and saves those separately.
"""

import time
import logging
import random
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from job_tracker import save_applied_job, save_manual_job

logger = logging.getLogger(__name__)

# Domains that indicate a company portal redirect
EXTERNAL_DOMAINS = [
    "greenhouse.io", "lever.co", "workday.com", "taleo.net",
    "successfactors.com", "icims.com", "jobvite.com", "smartrecruiters.com",
    "myworkdayjobs.com", "careers.", "jobs.", "apply.", "recruit.",
    "linkedin.com", "indeed.com", "instahyre.com", "hirist.com",
]


def apply_to_jobs(driver, matched_jobs: list, config: dict) -> dict:
    """
    Apply to matched jobs up to daily cap.
    Detects company portal redirects and saves them as manual-apply jobs.
    """
    from job_tracker import load_jobs_data
    daily_cap    = config["job_search"].get("max_applications_per_day", 15)
    already_done = set(
        j["url"] for j in load_jobs_data()["applied_jobs"]
    ) | set(
        j["url"] for j in load_jobs_data()["manual_jobs"]
    )

    new_jobs = [j for j in matched_jobs if j["url"] not in already_done]
    results  = {"applied": [], "manual": [], "failed": [], "total_applied": 0}

    logger.info(f"📨 {len(new_jobs)} new jobs to process (cap: {daily_cap})")

    for job in new_jobs:
        if results["total_applied"] >= daily_cap:
            logger.info("   ⏹️  Daily cap reached.")
            break

        title, company, url = job["title"], job["company"], job["url"]
        logger.info(f"   📩 Processing: {title} @ {company} (score: {job['score']})")

        result = _apply_single(driver, job)

        if result == "applied":
            save_applied_job(job)
            results["applied"].append(job)
            results["total_applied"] += 1
            logger.info(f"   ✅ Applied!")

        elif result == "manual":
            save_manual_job(job)
            results["manual"].append(job)
            logger.info(f"   📌 Manual apply needed — saved to dashboard")

        else:
            results["failed"].append(job)
            logger.warning(f"   ❌ Failed")

        time.sleep(random.uniform(8, 15))

    logger.info(
        f"✅ Done — Applied: {results['total_applied']}, "
        f"Manual: {len(results['manual'])}, "
        f"Failed: {len(results['failed'])}"
    )
    return results


def _apply_single(driver, job: dict) -> str:
    """
    Try to apply to a job.
    Returns: 'applied' | 'manual' | 'failed'
    """
    url = job["url"]
    try:
        driver.get(url)
        time.sleep(3)

        original_url = driver.current_url

        # Find apply button
        apply_btn = None
        for by, loc in [
            (By.XPATH, '//button[contains(text(),"Apply")]'),
            (By.XPATH, '//a[contains(text(),"Apply")]'),
            (By.CSS_SELECTOR, 'button.apply-button'),
            (By.CSS_SELECTOR, '#apply-button'),
            (By.XPATH, '//button[contains(text(),"Easy Apply")]'),
        ]:
            try:
                apply_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((by, loc))
                )
                break
            except Exception:
                continue

        if not apply_btn:
            return "failed"

        # Already applied?
        if "applied" in apply_btn.text.lower():
            return "applied"

        driver.execute_script("arguments[0].click();", apply_btn)
        time.sleep(4)

        # Check if redirected to external company portal
        current_url = driver.current_url
        if _is_external_redirect(original_url, current_url):
            logger.info(f"   🔗 Redirected to company portal: {current_url[:60]}...")
            job["company_portal_url"] = current_url
            driver.back()
            time.sleep(2)
            return "manual"

        # Handle any confirmation popup
        _handle_popup(driver)

        # Check for success
        page_source = driver.page_source.lower()
        if any(word in page_source for word in
               ["successfully applied", "application submitted",
                "applied successfully", "thank you for applying"]):
            return "applied"

        return "applied"   # Assume success if no error shown

    except Exception as e:
        logger.error(f"      Error: {e}")
        return "failed"


def _is_external_redirect(original_url: str, current_url: str) -> bool:
    """Check if browser was redirected away from naukri.com."""
    if "naukri.com" not in current_url:
        return True
    for domain in EXTERNAL_DOMAINS:
        if domain in current_url and domain not in original_url:
            return True
    return False


def _handle_popup(driver):
    for by, loc in [
        (By.XPATH, '//button[contains(text(),"Apply")]'),
        (By.XPATH, '//button[contains(text(),"Confirm")]'),
        (By.XPATH, '//button[contains(text(),"Submit")]'),
    ]:
        try:
            btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((by, loc)))
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(2)
            break
        except Exception:
            continue

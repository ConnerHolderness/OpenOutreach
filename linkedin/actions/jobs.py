# linkedin/actions/jobs.py
"""
LinkedIn Jobs Scraper

Navigates the LinkedIn job-search split-panel UI and extracts structured data
from every listing visible across all result pages.

Layout recap (confirmed against live DOM):
  • Left panel  – job card list (scrollable)
  • Right panel – job detail (AJAX-loaded on card click, URL updates currentJobId)

All CSS selectors are taken from the specification; semantic fallbacks are
included where class names are obfuscated and may rotate on deploys.
"""

import logging
import random
import re
import time
from typing import Optional
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

# Per-card click delay (seconds).  LinkedIn's bot-detection watches click cadence.
_MIN_CLICK_DELAY = 2.0
_MAX_CLICK_DELAY = 4.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pause():
    delay = random.uniform(_MIN_CLICK_DELAY, _MAX_CLICK_DELAY)
    logger.debug("Job scraper pause: %.2fs", delay)
    time.sleep(delay)


def _job_id_from_url(url: str) -> Optional[str]:
    """Extract the LinkedIn job ID from a URL.

    Checks the ``currentJobId`` query parameter first, then falls back to the
    ``/jobs/view/{id}/`` path segment.
    """
    try:
        params = parse_qs(urlparse(url).query)
        if "currentJobId" in params:
            return params["currentJobId"][0]
        m = re.search(r"/jobs/view/(\d+)", url)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _safe_text(locator, timeout: int = 2_000) -> Optional[str]:
    """Return stripped text from the first match, or None on any failure."""
    try:
        if locator.count() > 0:
            return locator.first.text_content(timeout=timeout).strip() or None
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Left-panel card extraction
# ---------------------------------------------------------------------------

def _extract_card_data(card) -> dict:
    """Extract the fields visible inside a left-panel job card.

    Fields: title, company, location, salary (optional), benefits (optional),
    posted_date_display (optional), posted_date_exact (optional).
    """
    data: dict = {}

    # ── Job title ──────────────────────────────────────────────────────────
    # Prefer the inner ``span:not([class])`` which carries the clean title.
    title = _safe_text(card.locator("span:not([class])").first)
    if not title:
        # Fallback: the hashed span – strip the "(Verified job)" suffix
        raw = _safe_text(card.locator("span.f5bf1c61").first)
        if raw:
            title = re.sub(r"\s*\(Verified job\)\s*", "", raw).strip() or None
    if title:
        data["title"] = title

    # ── Company & location (two consecutive <p> elements) ──────────────────
    try:
        company_els = card.locator("p.f30498a9._37677861").all()
        if len(company_els) >= 1:
            text = company_els[0].text_content(timeout=2_000).strip()
            if text:
                data["company"] = text
        if len(company_els) >= 2:
            text = company_els[1].text_content(timeout=2_000).strip()
            if text:
                data["location"] = text
    except Exception:
        pass

    # ── Salary & benefits (optional) ───────────────────────────────────────
    try:
        comp_els = card.locator("p.f30498a9._4d7f75b3").all()
        if len(comp_els) >= 1:
            text = comp_els[0].text_content(timeout=2_000).strip()
            if text:
                data["salary"] = text
        if len(comp_els) >= 2:
            text = comp_els[1].text_content(timeout=2_000).strip()
            if text:
                data["benefits"] = text
    except Exception:
        pass

    # ── Posted date – display ("3 weeks ago") and exact timestamp ──────────
    try:
        # 2nd ``span:not([class])`` → human-readable relative date
        unclassed = card.locator("span:not([class])").all()
        if len(unclassed) >= 2:
            text = unclassed[1].text_content(timeout=2_000).strip()
            if text:
                data["posted_date_display"] = text
    except Exception:
        pass

    try:
        # 2nd ``span.f5bf1c61`` → exact "Posted on …" timestamp
        hashed = card.locator("span.f5bf1c61").all()
        if len(hashed) >= 2:
            text = hashed[1].text_content(timeout=2_000).strip()
            if text:
                data["posted_date_exact"] = text
    except Exception:
        pass

    return data


# ---------------------------------------------------------------------------
# Right-panel (job detail) extraction
# ---------------------------------------------------------------------------

def _extract_detail_data(page) -> dict:
    """Extract all fields from the right-panel job detail view.

    Fields: job_id, title, job_url, company, company_url, location, work_type,
    employment_type, description, industry, employee_count.
    """
    data: dict = {}

    # ── A. Job title + URL + job_id ────────────────────────────────────────
    try:
        # Primary selector: anchor whose href contains /jobs/view/
        link = page.locator('a[href*="/jobs/view/"]').first
        if link.count() > 0:
            title = link.text_content(timeout=3_000).strip()
            if title:
                data["title"] = title
            href = link.get_attribute("href")
            if href:
                data["job_url"] = href
                jid = _job_id_from_url(href)
                if jid:
                    data["job_id"] = jid
    except Exception:
        pass

    # ── B. Company name + LinkedIn company page URL ────────────────────────
    try:
        company_link = page.locator('a[href*="linkedin.com/company/"]').first
        if company_link.count() > 0:
            name = company_link.text_content(timeout=3_000).strip()
            if name:
                data["company"] = name
            href = company_link.get_attribute("href")
            if href:
                data["company_url"] = href
    except Exception:
        pass

    # ── C. Location & work/employment type ────────────────────────────────
    try:
        loc = page.locator("span._45102191").first
        if loc.count() > 0:
            text = loc.text_content(timeout=3_000).strip()
            if text:
                data["location"] = text
    except Exception:
        pass

    try:
        type_spans = page.locator("span.f30498a9._5e3c1b19").all()
        if len(type_spans) >= 1:
            text = type_spans[0].text_content(timeout=2_000).strip()
            if text:
                data["work_type"] = text          # "On-site" / "Remote" / "Hybrid"
        if len(type_spans) >= 2:
            text = type_spans[1].text_content(timeout=2_000).strip()
            if text:
                data["employment_type"] = text    # "Full-time" / "Part-time"
    except Exception:
        pass

    # ── D. Job description ("About the job") ──────────────────────────────
    try:
        desc = page.locator("div._0d26244a.e030d934._7f013249 > p.f30498a9").first
        if desc.count() > 0:
            text = desc.inner_text(timeout=5_000).strip()
            if text:
                data["description"] = text
    except Exception:
        pass

    # ── E. "About the company" section (optional) ─────────────────────────
    try:
        meta_divs = page.locator(
            "div.b902da86._744bf2ab._4d8e8f8c div._04bda81b._9dfef8a0"
        ).all()
        # index 0 = industry category, index 1 = employee count
        if len(meta_divs) >= 1:
            text = meta_divs[0].text_content(timeout=2_000).strip()
            if text:
                data["industry"] = text
        if len(meta_divs) >= 2:
            text = meta_divs[1].text_content(timeout=2_000).strip()
            if text:
                data["employee_count"] = text
    except Exception:
        pass

    return data


# ---------------------------------------------------------------------------
# Wait helpers
# ---------------------------------------------------------------------------

def _wait_for_detail_panel(page, old_job_id: Optional[str], timeout: int = 10_000):
    """Block until the right-panel refreshes for a new job.

    Strategy 1 – URL's currentJobId parameter changes.
    Strategy 2 – The job-title anchor appears in the DOM (fallback).
    """
    if old_job_id:
        try:
            page.wait_for_function(
                f"""() => {{
                    const params = new URLSearchParams(window.location.search);
                    return params.get('currentJobId') !== '{old_job_id}';
                }}""",
                timeout=timeout,
            )
            return
        except Exception:
            pass

    # Fallback: wait for the job-title link to be visible
    try:
        page.wait_for_selector('a[href*="/jobs/view/"]', timeout=timeout)
    except Exception:
        logger.warning("Detail panel load timed out – scraping whatever is present")


# ---------------------------------------------------------------------------
# Public scraper
# ---------------------------------------------------------------------------

def scrape_jobs(session, search_url: str, max_pages: int = 10) -> list[dict]:
    """Scrape all job listings from a LinkedIn jobs-search URL.

    Iterates every job card on each results page, clicking each card to load
    its detail panel, then combines left-panel card metadata with right-panel
    detail data.

    Args:
        session:     Authenticated ``AccountSession``.
        search_url:  Full LinkedIn jobs search URL (with filters already applied).
        max_pages:   Hard cap on result pages to visit (default 10).

    Returns:
        List of dicts, one per job, containing all extractable fields.
    """
    page = session.page
    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    logger.info("Navigating to jobs search URL…")
    page.goto(search_url, wait_until="networkidle", timeout=30_000)
    page.wait_for_load_state("load")
    _pause()

    for page_num in range(1, max_pages + 1):
        logger.info("── Page %d ──────────────────────────────────────", page_num)

        # Scope all card lookups inside the visible list container to avoid
        # the duplicate-DOM issue described in the spec.
        container = page.locator("div._0d26244a._171b1336.b902da86").first
        if container.count() == 0:
            logger.warning("Job list container not found – stopping pagination")
            break

        # ── Type A card: the first/currently-selected job (rendered as <a>) ──
        type_a = container.locator("a.e4aff2a8._8cf960e8").all()

        # ── Type B cards: all other jobs (rendered as div[role="button"]) ──
        type_b = container.locator('div[role="button"]._8cf960e8._01942f8a').all()

        total = len(type_a) + len(type_b)
        logger.info(
            "Found %d job card(s) on page %d (Type A: %d, Type B: %d)",
            total, page_num, len(type_a), len(type_b),
        )

        if total == 0:
            logger.warning("No job cards – ending scrape")
            break

        # ── Process Type A (already selected – detail panel is pre-loaded) ──
        for card in type_a:
            try:
                card_data = _extract_card_data(card)
                current_job_id = _job_id_from_url(page.url)
                detail_data = _extract_detail_data(page)

                job_data = {**card_data, **detail_data}
                if current_job_id and not job_data.get("job_id"):
                    job_data["job_id"] = current_job_id

                job_id = job_data.get("job_id")
                if job_id and job_id not in seen_ids:
                    seen_ids.add(job_id)
                    all_jobs.append(job_data)
                    logger.info(
                        "  [A] %s @ %s  (id=%s)",
                        job_data.get("title", "?"),
                        job_data.get("company", "?"),
                        job_id,
                    )
            except Exception as e:
                logger.error("Error scraping Type A card: %s", e, exc_info=True)

        # ── Process Type B (click each to trigger AJAX panel refresh) ──────
        for idx, card in enumerate(type_b):
            try:
                card_data = _extract_card_data(card)
                old_job_id = _job_id_from_url(page.url)

                card.scroll_into_view_if_needed()
                card.click()
                _pause()
                _wait_for_detail_panel(page, old_job_id)

                current_job_id = _job_id_from_url(page.url)
                detail_data = _extract_detail_data(page)

                job_data = {**card_data, **detail_data}
                if current_job_id and not job_data.get("job_id"):
                    job_data["job_id"] = current_job_id

                job_id = job_data.get("job_id")
                if job_id and job_id not in seen_ids:
                    seen_ids.add(job_id)
                    all_jobs.append(job_data)
                    logger.info(
                        "  [B:%d] %s @ %s  (id=%s)",
                        idx + 1,
                        job_data.get("title", "?"),
                        job_data.get("company", "?"),
                        job_id,
                    )
                elif job_id and job_id in seen_ids:
                    logger.debug("  [B:%d] Duplicate job_id=%s – skipping", idx + 1, job_id)

            except Exception as e:
                logger.error("Error scraping Type B card %d: %s", idx, e, exc_info=True)

        # ── Pagination ────────────────────────────────────────────────────
        try:
            # Primary: hashed class selector filtered by exact text
            next_btn = page.locator("button.e161b7da.af2f639c").filter(has_text="Next")
            if next_btn.count() == 0:
                # Semantic fallback
                next_btn = page.locator("button").filter(has_text="Next")

            if next_btn.count() > 0 and next_btn.first.is_enabled():
                next_btn.first.click()
                _pause()
                page.wait_for_load_state("load")
                logger.info("Navigated to page %d", page_num + 1)
            else:
                logger.info("No 'Next' button – reached the last results page")
                break
        except Exception as e:
            logger.info("Pagination ended: %s", e)
            break

    logger.info("Scrape complete – %d unique jobs collected", len(all_jobs))
    return all_jobs

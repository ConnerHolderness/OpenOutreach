# linkedin/campaigns/job_scraper.py
"""
Job-scraper campaign

Authenticates a LinkedIn account session, navigates to the supplied job-search
URL, scrapes every listing across all result pages, and persists each job to
the account's local SQLite database.
"""

import csv
import logging

from termcolor import colored

from linkedin.actions.jobs import scrape_jobs
from linkedin.conf import DATA_DIR
from linkedin.db.jobs import save_job, get_all_jobs, jobs_to_dicts
from linkedin.sessions.account import AccountSession

logger = logging.getLogger(__name__)

# Default search URL (can be overridden at call-site or via CLI)
DEFAULT_SEARCH_URL = (
    "https://www.linkedin.com/jobs/search-results/"
    "?keywords=Sales%20Engineer%20Chicago"
    "&origin=JOB_SEARCH_PAGE_JOB_FILTER"
    "&f_SAL=f_SA_id_230001%3A272019%2C291004%24f_SA_id_228001%3A292001"
)


def run_job_scraper(
    handle: str,
    search_url: str = DEFAULT_SEARCH_URL,
    max_pages: int = 10,
    export_csv: bool = True,
) -> list[dict]:
    """Launch a full job-scrape campaign for one LinkedIn account.

    Args:
        handle:      LinkedIn account handle (must exist in accounts.secrets.yaml).
        search_url:  Full LinkedIn jobs-search URL with filters.
        max_pages:   Maximum result pages to visit (default 10 ≈ 250 jobs).
        export_csv:  When True, write results to assets/data/<handle>_jobs.csv.

    Returns:
        List of job dicts that were saved to the database.
    """
    logger.info(colored("Starting job scraper", "cyan", attrs=["bold"]) + f" for @{handle}")

    session = AccountSession(handle)
    try:
        session.ensure_browser()

        # Scrape all jobs
        jobs = scrape_jobs(session, search_url=search_url, max_pages=max_pages)

        if not jobs:
            logger.warning("No jobs were scraped – check the search URL or selectors")
            return []

        # Persist to DB
        saved = 0
        for job_data in jobs:
            result = save_job(session.db_session, job_data)
            if result:
                saved += 1

        logger.info(
            colored("Saved %d job(s) to database", "green", attrs=["bold"]),
            saved,
        )

        # Optional CSV export
        if export_csv:
            _export_csv(session, handle)

        return jobs_to_dicts(get_all_jobs(session.db_session))

    finally:
        session.close()


def _export_csv(session, handle: str):
    """Write all jobs for this account to a CSV file in assets/data/."""
    all_jobs = jobs_to_dicts(get_all_jobs(session.db_session))
    if not all_jobs:
        return

    out_path = DATA_DIR / f"{handle}_jobs.csv"
    fieldnames = list(all_jobs[0].keys())

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_jobs)

    logger.info(colored("Exported %d job(s) → %s", "green"), len(all_jobs), out_path)

"""
scrape_jobs.py – LinkedIn Job Scraper entry point

Usage:
    python scrape_jobs.py                           # uses first active account + default URL
    python scrape_jobs.py <handle>                  # explicit account, default URL
    python scrape_jobs.py <handle> "<search_url>"   # explicit account + custom URL
    python scrape_jobs.py <handle> "<search_url>" <max_pages>

The default search URL targets:
    "Sales Engineer" in Chicago with salary filters applied.

Results are saved to:
    assets/data/<handle>.db          (SQLite – always)
    assets/data/<handle>_jobs.csv    (CSV export – always)
"""

import logging
import sys

from linkedin.campaigns.job_scraper import DEFAULT_SEARCH_URL, run_job_scraper
from linkedin.conf import get_first_active_account

logging.getLogger().handlers.clear()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(message)s",
    datefmt="%H:%M:%S",
)

if __name__ == "__main__":
    handle = sys.argv[1] if len(sys.argv) > 1 else get_first_active_account()
    if not handle:
        print("No active account found. Add credentials to assets/accounts.secrets.yaml")
        sys.exit(1)

    search_url = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SEARCH_URL
    max_pages = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    print(f"Account  : {handle}")
    print(f"URL      : {search_url[:80]}{'…' if len(search_url) > 80 else ''}")
    print(f"Max pages: {max_pages}")
    print("-" * 60)

    jobs = run_job_scraper(handle=handle, search_url=search_url, max_pages=max_pages)

    print("-" * 60)
    print(f"Done – {len(jobs)} job(s) in database.")

# linkedin/db/jobs.py
"""Database operations for LinkedIn job listings."""

import logging
from typing import Optional

from linkedin.db.models import Job

logger = logging.getLogger(__name__)


def save_job(db_session, job_data: dict) -> Optional[Job]:
    """
    Insert or update a job record.

    If a Job with the same job_id already exists it is updated in-place;
    otherwise a new row is inserted.  Returns the Job ORM object, or None
    when job_data contains no usable job_id.
    """
    job_id = job_data.get("job_id")
    if not job_id:
        logger.warning("save_job called with no job_id – skipping: %s", job_data)
        return None

    existing = db_session.query(Job).filter_by(job_id=job_id).first()

    if existing:
        for key, value in job_data.items():
            if hasattr(Job, key) and key != "job_id":
                setattr(existing, key, value)
        db_session.commit()
        logger.debug("Updated job %s → %s", job_id, job_data.get("title"))
        return existing

    job = Job(**{k: v for k, v in job_data.items() if hasattr(Job, k)})
    db_session.add(job)
    db_session.commit()
    logger.debug("Saved new job %s → %s", job_id, job_data.get("title"))
    return job


def job_exists(db_session, job_id: str) -> bool:
    """Return True if this job_id is already in the database."""
    return db_session.query(Job).filter_by(job_id=job_id).first() is not None


def get_all_jobs(db_session) -> list[Job]:
    """Return all saved Job records ordered by creation date (newest first)."""
    return db_session.query(Job).order_by(Job.created_at.desc()).all()


def jobs_to_dicts(jobs: list[Job]) -> list[dict]:
    """Convert a list of Job ORM objects to plain dictionaries."""
    columns = [c.name for c in Job.__table__.columns]
    return [{col: getattr(j, col) for col in columns} for j in jobs]

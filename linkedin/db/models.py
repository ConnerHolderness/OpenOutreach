# linkedin/db_models.py

from sqlalchemy import Column, String, JSON, DateTime, Boolean, Integer
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class Profile(Base):
    __tablename__ = 'profiles'

    # USING public_identifier as primary key
    public_identifier = Column(String, primary_key=True)

    # Parsed / cleaned data (what you return from get_profile)
    profile = Column(JSON, nullable=True)

    # Full raw JSON from LinkedIn's API (for debugging, re-parsing, etc.)
    data = Column(JSON, nullable=True)

    # Whether this profile has been sent to your backend / cloud / CRM
    cloud_synced = Column(Boolean, default=False, server_default='false', nullable=False)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    state = Column(String, nullable=False, default="discovered")


class Job(Base):
    __tablename__ = 'jobs'

    # LinkedIn job ID as primary key (extracted from URL or job detail href)
    job_id = Column(String, primary_key=True)

    # Core job info from detail panel
    title = Column(String, nullable=True)
    job_url = Column(String, nullable=True)

    # Company
    company = Column(String, nullable=True)
    company_url = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    employee_count = Column(String, nullable=True)

    # Location & work arrangement
    location = Column(String, nullable=True)
    work_type = Column(String, nullable=True)       # "On-site" / "Remote" / "Hybrid"
    employment_type = Column(String, nullable=True)  # "Full-time" / "Part-time"

    # Compensation (optional – not all listings include it)
    salary = Column(String, nullable=True)
    benefits = Column(String, nullable=True)

    # Posting dates
    posted_date_display = Column(String, nullable=True)   # e.g. "3 weeks ago"
    posted_date_exact = Column(String, nullable=True)     # e.g. "Posted on February 10, 2026, 1:10 PM"

    # Full job description text
    description = Column(String, nullable=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
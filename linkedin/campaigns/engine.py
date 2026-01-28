# campaigns/engine.py
from __future__ import annotations

import logging

from linkedin.api.emails import ensure_newsletter_subscription
from linkedin.campaigns.connect_follow_up import process_profiles
from linkedin.campaigns.connect_only import process_connections
from linkedin.sessions.account import AccountSession

logger = logging.getLogger(__name__)


def start_campaign(handle: str, session: AccountSession, profiles: list[dict]):
    """Original campaign: scrape → connect → follow-up message."""
    session.ensure_browser()

    ensure_newsletter_subscription(session)

    process_profiles(handle, session, profiles)


def start_connect_only_campaign(handle: str, session: AccountSession, profiles: list[dict]):
    """
    Simplified campaign: connection requests only (no messages).

    - 20-30 connections per day (randomized)
    - 2-5 minute delays between connections
    - Tracks progress in database
    - All stealth features intact
    """
    session.ensure_browser()

    process_connections(handle, session, profiles)

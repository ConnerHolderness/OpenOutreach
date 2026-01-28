# campaigns/connect_only.py
"""
Simplified campaign: Send connection requests only (no messages).

Features:
- Reads target URLs from CSV
- Sends connection requests WITHOUT personalized notes
- 20-30 connections per day (randomized daily limit)
- 2-5 minute delays between connection attempts (human-like)
- Tracks progress in database for resumability
- Keeps all stealth/anti-detection features intact
"""
import logging
import random
import time
from datetime import date

from termcolor import colored

from linkedin.db.models import Profile
from linkedin.db.profiles import get_profile, set_profile_state, url_to_public_id
from linkedin.navigation.enums import ProfileState
from linkedin.navigation.exceptions import SkipProfile, ReachedConnectionLimit
from linkedin.navigation.utils import save_page

logger = logging.getLogger(__name__)

# Daily connection limits (randomized between these values)
MIN_DAILY_CONNECTIONS = 20
MAX_DAILY_CONNECTIONS = 30

# Delay between connection attempts (in seconds)
# 2-5 minutes = 120-300 seconds
MIN_CONNECTION_DELAY = 120
MAX_CONNECTION_DELAY = 300


def get_daily_connection_count(session) -> int:
    """Count connections sent today (profiles moved to PENDING today)."""
    from sqlalchemy import func

    today = date.today()
    count = (
        session.db_session
        .query(Profile)
        .filter(Profile.state == ProfileState.PENDING.value)
        .filter(func.date(Profile.updated_at) == today)
        .count()
    )
    return count


def get_daily_limit() -> int:
    """Get randomized daily limit (cached per day for consistency)."""
    # Use date as seed for consistent daily limit
    random.seed(date.today().toordinal())
    limit = random.randint(MIN_DAILY_CONNECTIONS, MAX_DAILY_CONNECTIONS)
    random.seed()  # Reset to random seed
    return limit


def human_connection_delay():
    """Wait 2-5 minutes between connection attempts (human-like behavior)."""
    delay = random.uniform(MIN_CONNECTION_DELAY, MAX_CONNECTION_DELAY)
    minutes = delay / 60
    logger.info(colored(f"Waiting {minutes:.1f} minutes before next connection...", "cyan"))
    time.sleep(delay)


def process_profile_for_connection(
    handle: str,
    session: "AccountSession",
    simple_profile: dict,
) -> ProfileState:
    """
    Simplified profile processing: only send connection request.

    State machine:
    - DISCOVERED/ENRICHED -> Navigate to profile, send connection -> PENDING
    - PENDING -> Already sent, skip
    - CONNECTED/COMPLETED/FAILED -> Terminal, skip

    Returns the new state after processing.
    """
    from linkedin.actions.connect import send_connection_request
    from linkedin.navigation.login import goto_page

    public_identifier = simple_profile['public_identifier']
    url = simple_profile['url']

    # Get current state from database
    profile_row = get_profile(session, public_identifier)

    if profile_row:
        current_state = ProfileState(profile_row.state)
        profile = profile_row.profile or simple_profile
    else:
        current_state = ProfileState.DISCOVERED
        profile = simple_profile

    logger.debug(f"Processing: {public_identifier} (state: {current_state.value})")

    # Handle terminal states
    if current_state in (ProfileState.PENDING, ProfileState.CONNECTED,
                         ProfileState.COMPLETED, ProfileState.FAILED):
        logger.info(f"Skipping {public_identifier} - already {current_state.value}")
        return current_state

    # Navigate to profile page
    logger.info(colored(f"Visiting profile: {public_identifier}", "blue"))
    goto_page(session, url)

    # Send connection request (uses existing stealth-enabled logic)
    new_state = send_connection_request(handle=handle, profile=profile)

    # Save state to database
    set_profile_state(session, public_identifier, new_state.value)

    return new_state


def process_connections(handle: str, session, profiles: list[dict]):
    """
    Main loop: process profiles and send connection requests.

    Features:
    - Respects daily connection limit (20-30 per day)
    - Adds 2-5 minute delays between connection attempts
    - Handles exceptions gracefully (skip, limit reached)
    - Resumes from where it left off (via database state)
    """
    daily_limit = get_daily_limit()
    connections_sent_today = get_daily_connection_count(session)

    logger.info(colored(
        f"Daily limit: {daily_limit} | Already sent today: {connections_sent_today}",
        "green", attrs=["bold"]
    ))

    if connections_sent_today >= daily_limit:
        logger.info(colored(
            f"Daily limit reached ({connections_sent_today}/{daily_limit}). "
            "Run again tomorrow!",
            "yellow", attrs=["bold"]
        ))
        return

    remaining = daily_limit - connections_sent_today
    profiles_to_process = profiles[:remaining + 10]  # Buffer for already-processed ones

    connections_this_session = 0

    for i, simple_profile in enumerate(profiles_to_process):
        public_identifier = simple_profile.get("public_identifier", "unknown")

        # Check if we've hit the daily limit
        current_count = get_daily_connection_count(session)
        if current_count >= daily_limit:
            logger.info(colored(
                f"Daily limit reached ({current_count}/{daily_limit}). Stopping.",
                "yellow", attrs=["bold"]
            ))
            break

        try:
            old_count = current_count
            new_state = process_profile_for_connection(
                handle=handle,
                session=session,
                simple_profile=simple_profile,
            )

            # If we actually sent a new connection (state changed to PENDING)
            if new_state == ProfileState.PENDING:
                connections_this_session += 1
                new_count = get_daily_connection_count(session)

                logger.info(colored(
                    f"Connection #{new_count} sent to {public_identifier} "
                    f"({new_count}/{daily_limit} today)",
                    "green", attrs=["bold"]
                ))

                # Add human-like delay before next connection (unless last one)
                if new_count < daily_limit and i < len(profiles_to_process) - 1:
                    human_connection_delay()

        except SkipProfile as e:
            logger.warning(colored(
                f"Skipping profile: {public_identifier} - {e}",
                "yellow"
            ))
            save_page(session, simple_profile)
            continue

        except ReachedConnectionLimit as e:
            logger.warning(colored(
                f"LinkedIn weekly limit reached: {e}",
                "red", attrs=["bold"]
            ))
            break

        except Exception as e:
            logger.error(colored(
                f"Error processing {public_identifier}: {e}",
                "red"
            ))
            continue

    # Summary
    final_count = get_daily_connection_count(session)
    logger.info(colored(
        f"\nSession complete: Sent {connections_this_session} new connections "
        f"({final_count}/{daily_limit} total today)",
        "green", attrs=["bold"]
    ))

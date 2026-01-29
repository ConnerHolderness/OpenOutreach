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
- Activity checking: only connects with recently active profiles
"""
import logging
import random
import re
import time
from datetime import date, timedelta
from typing import Optional

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

# Activity threshold: only connect with profiles active within this many days
ACTIVITY_THRESHOLD_DAYS = 30


def parse_relative_time(time_text: str) -> Optional[int]:
    """
    Parse LinkedIn's relative time strings into days ago.

    Examples:
    - "1d" -> 1
    - "2w" -> 14
    - "3mo" -> 90
    - "5mo ago" -> 150
    - "1yr" -> 365
    - "Just now" -> 0
    - "5h" -> 0

    Returns None if unable to parse.
    """
    original_text = time_text
    time_text = time_text.lower().strip()

    # Handle "just now" or "today"
    if "just now" in time_text or "today" in time_text:
        logger.debug(f"Activity parse: '{original_text}' -> 0 days (just now/today)")
        return 0

    # IMPORTANT: Order matters! Longer patterns must come BEFORE shorter ones
    # e.g., "month" before "mo" before "m", otherwise "5mo" matches "5m" (minutes)
    pattern = r'(\d+)\s*(month|minute|min|mo|week|year|hour|day|yr|[mhdw])s?'
    match = re.search(pattern, time_text)

    if not match:
        logger.warning(f"Activity parse FAILED: '{original_text}' - no pattern match")
        return None

    value = int(match.group(1))
    unit = match.group(2)

    # Map units to days
    unit_to_days = {
        # Minutes/hours -> 0 days (same day)
        'm': 0,
        'min': 0,
        'minute': 0,
        'h': 0,
        'hour': 0,
        # Days
        'd': 1,
        'day': 1,
        # Weeks
        'w': 7,
        'week': 7,
        # Months (approximate)
        'mo': 30,
        'month': 30,
        # Years
        'yr': 365,
        'year': 365,
    }

    multiplier = unit_to_days.get(unit, None)
    if multiplier is None:
        logger.warning(f"Activity parse FAILED: '{original_text}' - unknown unit '{unit}'")
        return None

    days = value * multiplier
    logger.info(f"Activity parse: '{original_text}' -> number={value}, unit='{unit}', days={days}")

    return days


def scroll_to_activity_section(session) -> bool:
    """
    Scroll down the profile page to find and load the Activity section.

    Returns True if Activity section was found, False otherwise.
    """
    page = session.page

    # LinkedIn activity section selectors (various possible structures)
    activity_selectors = [
        'section:has-text("Activity")',
        '#content_collections',
        'section[data-member-activity]',
        'div.pv-recent-activity-section',
        'section:has(> div:has-text("Activity"))',
    ]

    # Scroll down incrementally to trigger lazy loading
    for scroll_attempt in range(5):
        # Check if activity section is visible
        for selector in activity_selectors:
            try:
                element = page.locator(selector).first
                if element.is_visible(timeout=500):
                    # Scroll element into view
                    element.scroll_into_view_if_needed()
                    time.sleep(0.5)  # Wait for content to load
                    return True
            except Exception:
                continue

        # Scroll down by viewport height
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        time.sleep(0.8)  # Wait for lazy loading

    return False


def get_latest_activity_days_ago(session) -> Optional[int]:
    """
    Extract the number of days since the profile's most recent activity.

    Looks for timestamps in the Activity section of the profile.
    Returns None if no activity found or unable to parse.
    """
    page = session.page

    # Try to find activity timestamps
    # LinkedIn shows activity with timestamps like "1d", "2w", "3mo" etc.
    activity_time_selectors = [
        # Activity feed items with time
        'section:has-text("Activity") span.feed-shared-actor__sub-description',
        'section:has-text("Activity") time',
        'section:has-text("Activity") span:has-text("ago")',
        'section:has-text("Activity") span:has-text("d")',
        'section:has-text("Activity") span:has-text("w")',
        'section:has-text("Activity") span:has-text("mo")',
        # Alternate structures
        '#content_collections time',
        '#content_collections span.update-components-actor__sub-description',
        'div.pv-recent-activity-section time',
        # Generic activity timestamps
        '[data-test-id="activity-section"] time',
        'section.pv-profile-section time',
    ]

    timestamps = []

    for selector in activity_time_selectors:
        try:
            elements = page.locator(selector).all()
            for element in elements[:5]:  # Check first 5 elements
                try:
                    text = element.inner_text(timeout=500)
                    if text:
                        days = parse_relative_time(text)
                        if days is not None:
                            timestamps.append(days)
                except Exception:
                    continue
        except Exception:
            continue

    # Also try to find any visible time-related text near "Activity"
    try:
        # Look for common time patterns in the activity area
        activity_section = page.locator('section:has-text("Activity")').first
        if activity_section.is_visible(timeout=1000):
            section_text = activity_section.inner_text(timeout=2000)
            # Find all time-like patterns
            time_patterns = re.findall(
                r'\b(\d+)\s*(m|h|d|w|mo|yr|min|hour|day|week|month|year)s?\b',
                section_text.lower()
            )
            for value, unit in time_patterns[:5]:
                days = parse_relative_time(f"{value}{unit}")
                if days is not None:
                    timestamps.append(days)
    except Exception:
        pass

    if not timestamps:
        return None

    # Return the most recent activity (smallest number of days)
    return min(timestamps)


def check_profile_activity(session, threshold_days: int = ACTIVITY_THRESHOLD_DAYS) -> tuple[bool, Optional[int]]:
    """
    Check if a profile has been active within the threshold period.

    Returns:
        tuple: (is_active: bool, days_since_activity: Optional[int])
        - is_active is True if activity found within threshold_days
        - days_since_activity is the number of days since last activity (None if not found)
    """
    # Scroll to find activity section
    found_activity = scroll_to_activity_section(session)

    if not found_activity:
        logger.debug("Activity section not found on profile")
        return False, None

    # Get the most recent activity timestamp
    days_ago = get_latest_activity_days_ago(session)

    if days_ago is None:
        logger.debug("Could not parse activity timestamps")
        return False, None

    is_active = days_ago <= threshold_days
    return is_active, days_ago


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
    check_activity: bool = True,
    activity_threshold: int = ACTIVITY_THRESHOLD_DAYS,
) -> ProfileState:
    """
    Simplified profile processing: only send connection request.

    State machine:
    - DISCOVERED/ENRICHED -> Navigate to profile, check activity, send connection -> PENDING
    - INACTIVE -> Already marked inactive, skip
    - PENDING -> Already sent, skip
    - CONNECTED/COMPLETED/FAILED -> Terminal, skip

    Args:
        handle: Account handle
        session: AccountSession instance
        simple_profile: Dict with 'public_identifier' and 'url'
        check_activity: If True, check profile activity before connecting
        activity_threshold: Days of inactivity allowed (default: ACTIVITY_THRESHOLD_DAYS)

    Returns the new state after processing.
    """
    from linkedin.actions.connect import send_connection_request
    from linkedin.navigation.utils import goto_page

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

    # Handle terminal states (including INACTIVE)
    if current_state in (ProfileState.PENDING, ProfileState.CONNECTED,
                         ProfileState.COMPLETED, ProfileState.FAILED,
                         ProfileState.INACTIVE):
        logger.info(f"Skipping {public_identifier} - already {current_state.value}")
        return current_state

    # Navigate to profile page
    logger.info(colored(f"Visiting profile: {public_identifier}", "blue"))
    goto_page(
        session,
        action=lambda: session.page.goto(url),
        expected_url_pattern=f"/in/{public_identifier}",
    )

    # Check activity if enabled
    if check_activity:
        is_active, days_ago = check_profile_activity(session, activity_threshold)

        if days_ago is not None:
            if is_active:
                logger.info(colored(
                    f"Profile active ({days_ago} days ago) - proceeding with connection",
                    "green"
                ))
            else:
                logger.info(colored(
                    f"Skipping {public_identifier} - inactive ({days_ago} days ago, threshold: {activity_threshold})",
                    "yellow"
                ))
                set_profile_state(session, public_identifier, ProfileState.INACTIVE.value)
                return ProfileState.INACTIVE
        else:
            # No activity found - could be private or no posts
            logger.info(colored(
                f"Skipping {public_identifier} - no activity found",
                "yellow"
            ))
            set_profile_state(session, public_identifier, ProfileState.INACTIVE.value)
            return ProfileState.INACTIVE

    # Send connection request (uses existing stealth-enabled logic)
    new_state = send_connection_request(handle=handle, profile=profile)

    # Save state to database
    set_profile_state(session, public_identifier, new_state.value)

    return new_state


def process_connections(
    handle: str,
    session,
    profiles: list[dict],
    check_activity: bool = True,
    activity_threshold: int = ACTIVITY_THRESHOLD_DAYS,
):
    """
    Main loop: process profiles and send connection requests.

    Features:
    - Respects daily connection limit (20-30 per day)
    - Adds 2-5 minute delays between connection attempts
    - Checks profile activity before connecting (configurable)
    - Handles exceptions gracefully (skip, limit reached)
    - Resumes from where it left off (via database state)

    Args:
        handle: Account handle
        session: AccountSession instance
        profiles: List of profile dicts with 'public_identifier' and 'url'
        check_activity: If True, skip profiles inactive beyond threshold
        activity_threshold: Days of inactivity allowed (default: ACTIVITY_THRESHOLD_DAYS)
    """
    daily_limit = get_daily_limit()
    connections_sent_today = get_daily_connection_count(session)

    logger.info(colored(
        f"Daily limit: {daily_limit} | Already sent today: {connections_sent_today}",
        "green", attrs=["bold"]
    ))
    if check_activity:
        logger.info(colored(
            f"Activity check enabled: skipping profiles inactive > {activity_threshold} days",
            "cyan"
        ))

    if connections_sent_today >= daily_limit:
        logger.info(colored(
            f"Daily limit reached ({connections_sent_today}/{daily_limit}). "
            "Run again tomorrow!",
            "yellow", attrs=["bold"]
        ))
        return

    remaining = daily_limit - connections_sent_today
    profiles_to_process = profiles[:remaining + 20]  # Buffer for skipped/inactive ones

    connections_this_session = 0
    inactive_this_session = 0

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
            new_state = process_profile_for_connection(
                handle=handle,
                session=session,
                simple_profile=simple_profile,
                check_activity=check_activity,
                activity_threshold=activity_threshold,
            )

            # Track inactive profiles
            if new_state == ProfileState.INACTIVE:
                inactive_this_session += 1
                continue

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
    if inactive_this_session > 0:
        logger.info(colored(
            f"Skipped {inactive_this_session} inactive profiles",
            "yellow"
        ))

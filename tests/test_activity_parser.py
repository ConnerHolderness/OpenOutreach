# tests/test_activity_parser.py
"""Unit tests for activity date parsing."""
try:
    import pytest
except ImportError:
    pytest = None

from linkedin.campaigns.connect_only import parse_relative_time


class TestParseRelativeTime:
    """Test parse_relative_time function."""

    def test_months_short(self):
        """5mo ago should return 150 days (5 * 30)."""
        assert parse_relative_time("5mo ago") == 150
        assert parse_relative_time("5mo") == 150
        assert parse_relative_time("1mo") == 30
        assert parse_relative_time("3mo ago") == 90
        assert parse_relative_time("12mo") == 360

    def test_months_long(self):
        """month/months should work."""
        assert parse_relative_time("5 months ago") == 150
        assert parse_relative_time("1 month ago") == 30
        assert parse_relative_time("3months") == 90

    def test_weeks(self):
        """Weeks should multiply by 7."""
        assert parse_relative_time("3w ago") == 21
        assert parse_relative_time("1w") == 7
        assert parse_relative_time("2 weeks ago") == 14
        assert parse_relative_time("4w") == 28

    def test_days(self):
        """Days should return as-is."""
        assert parse_relative_time("2d ago") == 2
        assert parse_relative_time("1d") == 1
        assert parse_relative_time("5 days ago") == 5
        assert parse_relative_time("30d") == 30

    def test_years(self):
        """Years should multiply by 365."""
        assert parse_relative_time("1yr ago") == 365
        assert parse_relative_time("2yr") == 730
        assert parse_relative_time("1 year ago") == 365
        assert parse_relative_time("3years") == 1095

    def test_hours_and_minutes(self):
        """Hours and minutes should return 0 (same day)."""
        assert parse_relative_time("5h ago") == 0
        assert parse_relative_time("30m ago") == 0
        assert parse_relative_time("2 hours ago") == 0
        assert parse_relative_time("15 minutes ago") == 0
        assert parse_relative_time("45min") == 0

    def test_just_now(self):
        """Just now and today should return 0."""
        assert parse_relative_time("Just now") == 0
        assert parse_relative_time("just now") == 0
        assert parse_relative_time("today") == 0

    def test_invalid_input(self):
        """Invalid input should return None."""
        assert parse_relative_time("invalid") is None
        assert parse_relative_time("") is None
        assert parse_relative_time("no numbers here") is None

    def test_critical_bug_case(self):
        """
        CRITICAL: This was the original bug.
        '5mo' was incorrectly matching 'm' (minutes) instead of 'mo' (months).
        """
        # This MUST return 150, not 0
        result = parse_relative_time("5mo ago")
        assert result == 150, f"CRITICAL BUG: '5mo ago' returned {result}, expected 150"

        # Verify the fix works for similar cases
        assert parse_relative_time("10mo") == 300  # Not 0
        assert parse_relative_time("6mo ago") == 180  # Not 0


if __name__ == "__main__":
    # Quick manual test
    test_cases = [
        ("5mo ago", 150),
        ("3w ago", 21),
        ("2d ago", 2),
        ("1yr ago", 365),
        ("5h ago", 0),
        ("30m ago", 0),
        ("Just now", 0),
    ]

    print("Testing parse_relative_time():\n")
    all_passed = True

    for text, expected in test_cases:
        result = parse_relative_time(text)
        status = "✓" if result == expected else "✗ FAIL"
        if result != expected:
            all_passed = False
        print(f"  {status} parse_relative_time('{text}') = {result} (expected {expected})")

    print()
    if all_passed:
        print("All tests passed!")
    else:
        print("SOME TESTS FAILED!")
        exit(1)

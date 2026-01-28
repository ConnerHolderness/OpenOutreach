import argparse
import logging
import sys

from linkedin.csv_launcher import launch_connect_follow_up_campaign, launch_connect_only_campaign

logging.getLogger().handlers.clear()
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)


def main():
    parser = argparse.ArgumentParser(
        description="OpenOutreach LinkedIn Automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run simplified connect-only campaign (default: reads from assets/inputs/urls.csv)
  python main.py --connect-only

  # Run connect-only with specific account
  python main.py --connect-only --handle john_doe

  # Run connect-only with custom CSV file
  python main.py --connect-only --csv /path/to/profiles.csv

  # Run original full campaign (scrape → connect → follow-up message)
  python main.py --full

  # Legacy mode (same as --full)
  python main.py john_doe
        """
    )

    parser.add_argument(
        "handle",
        nargs="?",
        default=None,
        help="Account handle (optional, uses first active account if not specified)"
    )
    parser.add_argument(
        "--connect-only", "-c",
        action="store_true",
        help="Run simplified connect-only campaign (no messages)"
    )
    parser.add_argument(
        "--full", "-f",
        action="store_true",
        help="Run full campaign with follow-up messages"
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Path to CSV file with LinkedIn URLs (connect-only mode)"
    )
    parser.add_argument(
        "--handle", "-H",
        dest="handle_flag",
        type=str,
        default=None,
        help="Account handle (alternative to positional argument)"
    )

    args = parser.parse_args()

    # Determine handle (flag takes precedence)
    handle = args.handle_flag or args.handle

    # Determine campaign mode
    if args.connect_only:
        launch_connect_only_campaign(handle=handle, input_csv=args.csv)
    elif args.full or args.handle:
        # --full flag or legacy positional argument mode
        launch_connect_follow_up_campaign(handle=handle)
    else:
        # Default to connect-only if no flags specified
        print("No campaign mode specified. Use --connect-only or --full")
        print("Run 'python main.py --help' for usage information")
        sys.exit(1)


if __name__ == "__main__":
    main()

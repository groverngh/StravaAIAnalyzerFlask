#!/usr/bin/env python3
"""
WhatsApp Weekly Running Summary Bot
Main script to fetch athlete data and send weekly summary via WhatsApp
"""
import sys
import os
import argparse
from datetime import datetime

# Add parent directory to Python path so we can import whatsapp_bot module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from whatsapp_bot.data_fetcher import get_athletes_data
from whatsapp_bot.message_generator import generate_message
from whatsapp_bot.whatsapp_sender import send_whatsapp_message


def main():
    """Main entry point for the weekly summary bot"""
    parser = argparse.ArgumentParser(description='WhatsApp Weekly Running Summary Bot')
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Generate and print message without sending to WhatsApp'
    )
    parser.add_argument(
        '--contact',
        type=str,
        help='Override contact name from .env file'
    )
    parser.add_argument(
        '--headless',
        action='store_true',
        help='Run browser in headless mode (no visible window)'
    )
    parser.add_argument(
        '--yearly',
        action='store_true',
        help='Generate yearly stats summary instead of weekly'
    )
    parser.add_argument(
        '--week',
        type=int,
        help='Generate stats for a specific week number (1-based index, e.g., --week 5 for week 5)'
    )

    args = parser.parse_args()

    print("="*60)
    print("   WhatsApp Weekly Running Summary Bot")
    print("="*60)
    print(f"   Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    print()

    # Step 1: Fetch athlete data from Google Sheets
    print("[1/3] Fetching athlete data from Google Sheets...")
    try:
        athletes_data = get_athletes_data()
        if not athletes_data:
            print("✗ No athlete data found or error fetching data")
            sys.exit(1)
        print(f"✓ Successfully fetched data for {len(athletes_data)} athletes")
    except Exception as e:
        print(f"✗ Error fetching athlete data: {e}")
        sys.exit(1)

    print()

    # Step 2: Generate summary message
    if args.yearly:
        print("[2/3] Generating yearly stats summary...")
        mode = 'yearly'
        week_num = None
    elif args.week:
        print(f"[2/3] Generating stats for week {args.week}...")
        mode = 'specific_week'
        week_num = args.week - 1  # Convert to 0-indexed
    else:
        print("[2/3] Generating current week summary...")
        mode = 'weekly'
        week_num = None

    try:
        message = generate_message(athletes_data, mode=mode, week_number=week_num)
        print("✓ Message generated successfully")
        print()
        print("-" * 60)
        print("MESSAGE PREVIEW:")
        print("-" * 60)
        print(message)
        print("-" * 60)
    except Exception as e:
        print(f"✗ Error generating message: {e}")
        sys.exit(1)

    print()

    # Step 3: Send message via WhatsApp (or dry run)
    if args.dry_run:
        print("[3/3] DRY RUN MODE - Skipping WhatsApp send")
        print("✓ Dry run complete! Message was NOT sent to WhatsApp.")
        print()
        print("To send the actual message, run without --dry-run flag:")
        print("  python3 whatsapp_bot/run_weekly_summary.py")
    else:
        print("[3/3] Sending message via WhatsApp...")
        try:
            success, error = send_whatsapp_message(
                message,
                contact_name=args.contact,
                headless=args.headless
            )

            if success:
                print("✓ Message sent successfully!")
                print()
                print("="*60)
                print("   ✓ WEEKLY SUMMARY SENT!")
                print("="*60)
            else:
                print(f"✗ Failed to send message: {error}")
                print()
                print("="*60)
                print("   ✗ FAILED TO SEND MESSAGE")
                print("="*60)
                sys.exit(1)

        except Exception as e:
            print(f"✗ Unexpected error: {e}")
            sys.exit(1)

    print(f"   Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)


if __name__ == "__main__":
    main()

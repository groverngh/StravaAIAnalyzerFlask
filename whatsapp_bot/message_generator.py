"""
Message generator for WhatsApp Weekly Summary Bot
"""
from datetime import datetime
from whatsapp_bot.config import SHOW_WEEK_NUMBER, SHOW_TOTAL_MILEAGE


def get_emoji_for_mileage(miles):
    """Get emoji based on mileage range

    Args:
        miles (float): Mileage for the week

    Returns:
        str: Emoji string
    """
    if miles >= 40:
        return "🔥"
    elif miles >= 30:
        return "💪"
    elif miles >= 20:
        return "⚡"
    elif miles >= 10:
        return "👍"
    else:
        return "👏"


def get_week_number():
    """Get current week number and year

    Returns:
        str: Week number formatted as "Week X of YYYY"
    """
    now = datetime.now()
    week_num = now.isocalendar()[1]
    year = now.year
    return f"Week{week_num}"


def generate_yearly_stats_message(athletes_data):
    """Generate yearly stats summary message

    Args:
        athletes_data (list): List of athlete dictionaries from Google Sheets

    Returns:
        str: Formatted WhatsApp message with yearly stats
    """
    # Filter athletes with yearly distance > 0
    active_runners = []
    for athlete in athletes_data:
        try:
            yearly_distance = float(athlete.get('yearly_distance', 0))
            number_of_runs = int(athlete.get('number_of_runs', 0))
            if yearly_distance > 0:
                active_runners.append({
                    'name': athlete.get('athlete', 'Unknown'),
                    'miles': yearly_distance,
                    'runs': number_of_runs
                })
        except (ValueError, TypeError):
            continue

    # Handle no runners case
    if not active_runners:
        return "🏃‍♂️💨 YEARLY RUNNING SUMMARY 💨🏃‍♀️\n\n📢 No data available!\n\nGet those miles in! 🎯"

    # Sort by miles (descending)
    active_runners.sort(key=lambda x: x['miles'], reverse=True)

    # Calculate totals
    total_miles = sum(r['miles'] for r in active_runners)
    total_runs = sum(r['runs'] for r in active_runners)

    # Build message
    year = datetime.now().year
    message_parts = [f"🏃‍♂️💨 {year} YEARLY RUNNING SUMMARY 💨🏃‍♀️\n"]

    # Handle podium or simple list
    if len(active_runners) >= 3:
        # Top 3 podium
        message_parts.append("🏆 TOP MILEAGE LEADERS 🏆")

        # 1st place
        message_parts.append(f"🥇 {active_runners[0]['name']}: {active_runners[0]['miles']:.2f} mi ({active_runners[0]['runs']} runs)")

        # 2nd place
        message_parts.append(f"🥈 {active_runners[1]['name']}: {active_runners[1]['miles']:.2f} mi ({active_runners[1]['runs']} runs)")

        # 3rd place
        message_parts.append(f"🥉 {active_runners[2]['name']}: {active_runners[2]['miles']:.2f} mi ({active_runners[2]['runs']} runs)")

        # Other runners
        if len(active_runners) > 3:
            message_parts.append("\n🏃 OTHER RUNNERS 🏃")
            for runner in active_runners[3:]:
                message_parts.append(f"• {runner['name']}: {runner['miles']:.2f} mi ({runner['runs']} runs)")
    else:
        # Simple list for 1-2 runners
        message_parts.append("🏃 YEARLY STATS 🏃")
        for i, runner in enumerate(active_runners, 1):
            message_parts.append(f"{i}. {runner['name']}: {runner['miles']:.2f} mi ({runner['runs']} runs)")

    # Add totals
    message_parts.append(f"\n📊 GROUP TOTALS 📊")
    message_parts.append(f"Total miles: {total_miles:.2f} mi 🎯")
    message_parts.append(f"Total runs: {total_runs} runs 👟")

    # Add motivational closing
    message_parts.append("\nKeep crushing those goals! 💪✨")
    message_parts.append(f"\n#RunningCrew #{year}YearInReview")

    return "\n".join(message_parts)


def generate_specific_week_message(athletes_data, week_number):
    """Generate message for a specific week

    Args:
        athletes_data (list): List of athlete dictionaries from Google Sheets
        week_number (int): Week number to report (0-indexed)

    Returns:
        str: Formatted WhatsApp message
    """
    # Filter athletes with mileage for the specified week
    active_runners = []
    week_label = None

    for athlete in athletes_data:
        try:
            weekly_volumes = athlete.get('weekly_volumes', [])
            week_labels = athlete.get('week_labels', [])

            # Check if week number is valid
            if week_number < len(weekly_volumes):
                week_miles = weekly_volumes[week_number]
                if week_miles > 0:
                    active_runners.append({
                        'name': athlete.get('athlete', 'Unknown'),
                        'miles': week_miles
                    })

                # Get week label from first athlete
                if week_label is None and week_number < len(week_labels):
                    week_label = week_labels[week_number]

        except (ValueError, TypeError, IndexError):
            continue

    # If no week label found, use week number
    if week_label is None:
        week_label = f"Week {week_number + 1}"

    # Handle no runners case
    if not active_runners:
        return f"🏃‍♂️💨 {week_label.upper()} LEADERBOARD 💨🏃‍♀️\n\n📢 No miles logged for this week!\n\nGet out there and run! 🎯"

    # Sort by miles (descending)
    active_runners.sort(key=lambda x: x['miles'], reverse=True)

    # Calculate total mileage
    total_miles = sum(r['miles'] for r in active_runners)

    # Build message
    message_parts = [f"🏃‍♂️💨 {week_label.upper()} LEADERBOARD 💨🏃‍♀️\n"]

    # Handle podium or simple list
    if len(active_runners) >= 3:
        # Top 3 podium
        message_parts.append("🏆 PODIUM FINISHERS 🏆")

        # 1st place
        emoji1 = get_emoji_for_mileage(active_runners[0]['miles'])
        message_parts.append(f"🥇 {active_runners[0]['name']}: {active_runners[0]['miles']:.2f} mi - Beast Mode! {emoji1}")

        # 2nd place
        emoji2 = get_emoji_for_mileage(active_runners[1]['miles'])
        message_parts.append(f"🥈 {active_runners[1]['name']}: {active_runners[1]['miles']:.2f} mi - Crushing it! {emoji2}")

        # 3rd place
        emoji3 = get_emoji_for_mileage(active_runners[2]['miles'])
        message_parts.append(f"🥉 {active_runners[2]['name']}: {active_runners[2]['miles']:.2f} mi - On fire! {emoji3}")

        # Other runners
        if len(active_runners) > 3:
            message_parts.append("\n🏃 ALSO PUTTING IN WORK 🏃")
            for runner in active_runners[3:]:
                message_parts.append(f"• {runner['name']}: {runner['miles']:.2f} mi")
    else:
        # Simple list for 1-2 runners
        message_parts.append(f"🏃 {week_label.upper()} RUNNERS 🏃")
        for i, runner in enumerate(active_runners, 1):
            emoji = get_emoji_for_mileage(runner['miles'])
            message_parts.append(f"{i}. {runner['name']}: {runner['miles']:.2f} mi {emoji}")

    # Add total mileage
    if SHOW_TOTAL_MILEAGE:
        message_parts.append(f"\nTotal group miles: {total_miles:.2f} mi 🎯")

    # Add motivational closing
    message_parts.append("Keep those legs moving! 🦵✨")

    # Add hashtag
    message_parts.append(f"\n#RunningCrew #{week_label.replace(' ', '')}")

    return "\n".join(message_parts)


def generate_weekly_message(athletes_data, week_number=None):
    """Generate fun weekly summary message

    Args:
        athletes_data (list): List of athlete dictionaries from Google Sheets
        week_number (int, optional): Specific week number (0-indexed). If None, uses current week.

    Returns:
        str: Formatted WhatsApp message
    """
    # If specific week requested, use that function
    if week_number is not None:
        return generate_specific_week_message(athletes_data, week_number)

    # Filter athletes with current_week > 0
    active_runners = []
    for athlete in athletes_data:
        try:
            current_week = float(athlete.get('current_week', 0)) if athlete.get('current_week') else 0
            if current_week > 0:
                active_runners.append({
                    'name': athlete.get('athlete', 'Unknown'),
                    'miles': current_week
                })
        except (ValueError, TypeError):
            continue

    # Handle no runners case
    if not active_runners:
        return "🏃‍♂️💨 WEEKLY RUNNING LEADERBOARD 💨🏃‍♀️\n\n📢 No miles logged this week!\nTime to lace up those shoes! 👟\n\nGet out there and run! 🎯"

    # Sort by miles (descending)
    active_runners.sort(key=lambda x: x['miles'], reverse=True)

    # Calculate total mileage
    total_miles = sum(r['miles'] for r in active_runners)

    # Build message
    message_parts = ["🏃‍♂️💨 WEEKLY RUNNING LEADERBOARD 💨🏃‍♀️\n"]

    # Handle podium or simple list
    if len(active_runners) >= 3:
        # Top 3 podium
        message_parts.append("🏆 PODIUM FINISHERS 🏆")

        # 1st place
        emoji1 = get_emoji_for_mileage(active_runners[0]['miles'])
        message_parts.append(f"🥇 {active_runners[0]['name']}: {active_runners[0]['miles']:.2f} mi - Beast Mode! {emoji1}")

        # 2nd place
        emoji2 = get_emoji_for_mileage(active_runners[1]['miles'])
        message_parts.append(f"🥈 {active_runners[1]['name']}: {active_runners[1]['miles']:.2f} mi - Crushing it! {emoji2}")

        # 3rd place
        emoji3 = get_emoji_for_mileage(active_runners[2]['miles'])
        message_parts.append(f"🥉 {active_runners[2]['name']}: {active_runners[2]['miles']:.2f} mi - On fire! {emoji3}")

        # Other runners
        if len(active_runners) > 3:
            message_parts.append("\n🏃 ALSO PUTTING IN WORK 🏃")
            for runner in active_runners[3:]:
                message_parts.append(f"• {runner['name']}: {runner['miles']:.2f} mi")
    else:
        # Simple list for 1-2 runners
        message_parts.append("🏃 THIS WEEK'S RUNNERS 🏃")
        for i, runner in enumerate(active_runners, 1):
            emoji = get_emoji_for_mileage(runner['miles'])
            message_parts.append(f"{i}. {runner['name']}: {runner['miles']:.2f} mi {emoji}")

    # Add total mileage
    if SHOW_TOTAL_MILEAGE:
        message_parts.append(f"\nTotal group miles: {total_miles:.2f} mi 🎯")

    # Add motivational closing
    message_parts.append("Keep those legs moving! 🦵✨")

    # Add week number hashtag
    if SHOW_WEEK_NUMBER:
        week_tag = get_week_number()
        message_parts.append(f"\n#RunningCrew #{week_tag}")

    return "\n".join(message_parts)


def generate_message(athletes_data, mode='weekly', week_number=None):
    """Main function to generate messages based on mode

    Args:
        athletes_data (list): List of athlete dictionaries from Google Sheets
        mode (str): 'weekly', 'yearly', or 'specific_week'
        week_number (int, optional): Week number for specific week mode (0-indexed)

    Returns:
        str: Formatted WhatsApp message
    """
    if mode == 'yearly':
        return generate_yearly_stats_message(athletes_data)
    elif mode == 'specific_week' and week_number is not None:
        return generate_specific_week_message(athletes_data, week_number)
    elif week_number is not None:
        return generate_specific_week_message(athletes_data, week_number)
    else:
        return generate_weekly_message(athletes_data)


if __name__ == "__main__":
    # Test with sample data
    sample_data = [
        {
            'athlete': 'Jane Smith',
            'current_week': '45.67',
            'yearly_distance': 500,
            'number_of_runs': 50,
            'weekly_volumes': [10.5, 15.2, 20.0, 25.3, 30.1, 35.4, 40.2, 45.67],
            'week_labels': ['Week 1', 'Week 2', 'Week 3', 'Week 4', 'Week 5', 'Week 6', 'Week 7', 'Week 8']
        },
        {
            'athlete': 'John Doe',
            'current_week': '38.92',
            'yearly_distance': 450,
            'number_of_runs': 45,
            'weekly_volumes': [8.0, 12.5, 18.0, 22.5, 28.0, 32.5, 35.0, 38.92],
            'week_labels': ['Week 1', 'Week 2', 'Week 3', 'Week 4', 'Week 5', 'Week 6', 'Week 7', 'Week 8']
        },
        {
            'athlete': 'Mike Johnson',
            'current_week': '32.45',
            'yearly_distance': 400,
            'number_of_runs': 40,
            'weekly_volumes': [5.0, 10.0, 15.0, 20.0, 25.0, 28.0, 30.0, 32.45],
            'week_labels': ['Week 1', 'Week 2', 'Week 3', 'Week 4', 'Week 5', 'Week 6', 'Week 7', 'Week 8']
        },
    ]

    print("=== CURRENT WEEK MESSAGE ===")
    print(generate_message(sample_data, mode='weekly'))
    print("\n=== YEARLY STATS MESSAGE ===")
    print(generate_message(sample_data, mode='yearly'))
    print("\n=== SPECIFIC WEEK MESSAGE (Week 3) ===")
    print(generate_message(sample_data, mode='specific_week', week_number=2))
    print("\n=== NO RUNNERS MESSAGE ===")
    print(generate_message([]))

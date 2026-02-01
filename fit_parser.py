"""
FIT File Parser for Strava-like Activity Data
Converts FIT files to a format compatible with Strava API responses
"""
from fitparse import FitFile
from datetime import datetime, timedelta
import os


def parse_fit_file(filepath):
    """Parse a FIT file and extract activity data in Strava-compatible format

    Args:
        filepath (str): Path to the .fit file

    Returns:
        dict: Activity data in Strava-compatible format, or None if parsing fails
    """
    try:
        fitfile = FitFile(filepath)

        # Initialize activity data structure
        activity_data = {
            'name': 'Manual FIT Upload',
            'type': 'Run',  # Default to Run, will try to detect
            'start_date': None,
            'start_date_local': None,
            'distance': 0,  # meters
            'moving_time': 0,  # seconds
            'elapsed_time': 0,  # seconds
            'total_elevation_gain': 0,  # meters
            'elev_high': None,  # meters
            'elev_low': None,  # meters
            'average_speed': 0,  # meters/second
            'max_speed': 0,  # meters/second
            'average_heartrate': None,
            'max_heartrate': None,
            'average_cadence': None,
            'has_heartrate': False,
            'calories': 0,
            'splits_standard': [],  # mile splits
            'id': f"fit_{datetime.now().timestamp()}",  # Generate unique ID
            'manual': True  # Flag to indicate manual upload
        }

        # Storage for records to calculate splits
        records = []
        heart_rates = []
        cadences = []
        elevations = []

        # Parse all messages
        for record in fitfile.get_messages():
            # Session data (summary of entire activity)
            if record.name == 'session':
                for field in record:
                    if field.name == 'start_time':
                        activity_data['start_date'] = field.value.isoformat() + 'Z'
                        activity_data['start_date_local'] = field.value.isoformat()
                    elif field.name == 'total_distance':
                        activity_data['distance'] = field.value
                    elif field.name == 'total_timer_time':
                        activity_data['moving_time'] = int(field.value)
                    elif field.name == 'total_elapsed_time':
                        activity_data['elapsed_time'] = int(field.value)
                    elif field.name == 'total_ascent':
                        activity_data['total_elevation_gain'] = field.value
                    elif field.name == 'avg_speed':
                        activity_data['average_speed'] = field.value
                    elif field.name == 'max_speed':
                        activity_data['max_speed'] = field.value
                    elif field.name == 'avg_heart_rate':
                        activity_data['average_heartrate'] = field.value
                        activity_data['has_heartrate'] = True
                    elif field.name == 'max_heart_rate':
                        activity_data['max_heartrate'] = field.value
                    elif field.name == 'avg_cadence':
                        # Cadence is often doubled in FIT files (for running)
                        activity_data['average_cadence'] = field.value
                    elif field.name == 'total_calories':
                        activity_data['calories'] = field.value
                    elif field.name == 'sport':
                        # Map FIT sport types to Strava activity types
                        sport_map = {
                            'running': 'Run',
                            'cycling': 'Ride',
                            'walking': 'Walk',
                            'hiking': 'Hike',
                            'swimming': 'Swim',
                            'generic': 'Workout'
                        }
                        activity_data['type'] = sport_map.get(field.value.lower(), 'Run')

            # Record data (individual data points during activity)
            elif record.name == 'record':
                record_data = {}
                for field in record:
                    if field.name == 'timestamp':
                        record_data['timestamp'] = field.value
                    elif field.name == 'distance':
                        record_data['distance'] = field.value
                    elif field.name == 'heart_rate':
                        record_data['heart_rate'] = field.value
                        heart_rates.append(field.value)
                    elif field.name == 'altitude':
                        record_data['altitude'] = field.value
                        elevations.append(field.value)
                    elif field.name == 'cadence':
                        record_data['cadence'] = field.value
                        cadences.append(field.value)
                    elif field.name == 'speed':
                        record_data['speed'] = field.value

                if record_data:
                    records.append(record_data)

            # Activity/File ID
            elif record.name == 'file_id':
                for field in record:
                    if field.name == 'time_created':
                        if not activity_data['start_date']:
                            activity_data['start_date'] = field.value.isoformat() + 'Z'
                            activity_data['start_date_local'] = field.value.isoformat()

        # Calculate elevation high/low from records
        if elevations:
            activity_data['elev_high'] = max(elevations)
            activity_data['elev_low'] = min(elevations)

        # Calculate splits (miles for US standard)
        if records and activity_data['distance'] > 0:
            activity_data['splits_standard'] = calculate_mile_splits(records)

        # Set name based on type and date
        if activity_data['start_date']:
            date_str = datetime.fromisoformat(activity_data['start_date'].replace('Z', '')).strftime('%B %d, %Y')
            activity_data['name'] = f"{activity_data['type']} - {date_str}"

        # Add description indicating manual upload
        activity_data['description'] = 'Uploaded from FIT file'

        return activity_data

    except Exception as e:
        print(f"Error parsing FIT file: {e}")
        return None


def calculate_mile_splits(records):
    """Calculate mile splits from record data

    Args:
        records (list): List of record dictionaries with distance and timestamp

    Returns:
        list: List of split dictionaries compatible with Strava format
    """
    splits = []
    METERS_PER_MILE = 1609.34

    current_mile = 1
    mile_start_index = 0

    for i, record in enumerate(records):
        distance = record.get('distance', 0)

        # Check if we've crossed a mile boundary
        if distance >= current_mile * METERS_PER_MILE:
            # Find the records that bracket this mile mark
            if i > 0:
                # Calculate split time
                split_start_time = records[mile_start_index].get('timestamp')
                split_end_time = record.get('timestamp')

                if split_start_time and split_end_time:
                    elapsed_time = (split_end_time - split_start_time).total_seconds()

                    # Calculate average speed for this split
                    split_distance = distance - records[mile_start_index].get('distance', 0)
                    avg_speed = split_distance / elapsed_time if elapsed_time > 0 else 0

                    # Calculate elevation difference
                    elevation_diff = 0
                    if 'altitude' in record and 'altitude' in records[mile_start_index]:
                        elevation_diff = record['altitude'] - records[mile_start_index]['altitude']

                    split = {
                        'distance': METERS_PER_MILE,
                        'elapsed_time': int(elapsed_time),
                        'moving_time': int(elapsed_time),
                        'split': current_mile,
                        'average_speed': avg_speed,
                        'elevation_difference': elevation_diff,
                        'pace_zone': 0  # Could be calculated if we have zones
                    }

                    splits.append(split)

                    mile_start_index = i
                    current_mile += 1

    return splits


def validate_fit_file(filepath):
    """Validate that a file is a valid FIT file

    Args:
        filepath (str): Path to the file

    Returns:
        tuple: (is_valid (bool), error_message (str or None))
    """
    # Check file exists
    if not os.path.exists(filepath):
        return False, "File does not exist"

    # Check file extension
    if not filepath.lower().endswith('.fit'):
        return False, "File must have .fit extension"

    # Check file size (should be reasonable, not too large)
    file_size = os.path.getsize(filepath)
    if file_size > 50 * 1024 * 1024:  # 50 MB limit
        return False, "FIT file is too large (max 50 MB)"

    if file_size == 0:
        return False, "FIT file is empty"

    # Try to parse the file header
    try:
        fitfile = FitFile(filepath)
        # Try to read at least one message
        messages = list(fitfile.get_messages())
        if not messages:
            return False, "FIT file contains no data"
        return True, None
    except Exception as e:
        return False, f"Invalid FIT file format: {str(e)}"


if __name__ == "__main__":
    # Test the parser with a sample file
    import sys

    if len(sys.argv) > 1:
        fit_file_path = sys.argv[1]
        print(f"Parsing FIT file: {fit_file_path}")

        # Validate first
        is_valid, error = validate_fit_file(fit_file_path)
        if not is_valid:
            print(f"Validation failed: {error}")
            sys.exit(1)

        # Parse the file
        activity = parse_fit_file(fit_file_path)

        if activity:
            print("\n=== Activity Data ===")
            print(f"Name: {activity['name']}")
            print(f"Type: {activity['type']}")
            print(f"Date: {activity['start_date_local']}")
            print(f"Distance: {activity['distance'] / 1609.34:.2f} miles")
            print(f"Moving Time: {activity['moving_time'] // 60} min {activity['moving_time'] % 60} sec")
            print(f"Pace: {(activity['moving_time'] / 60) / (activity['distance'] / 1609.34):.2f} min/mile")
            print(f"Elevation Gain: {activity['total_elevation_gain']:.0f} meters ({activity['total_elevation_gain'] * 3.28084:.0f} feet)")
            if activity['has_heartrate']:
                print(f"Avg HR: {activity['average_heartrate']:.0f} bpm")
                print(f"Max HR: {activity['max_heartrate']:.0f} bpm")
            print(f"Calories: {activity['calories']:.0f}")
            print(f"Splits: {len(activity['splits_standard'])} miles")
        else:
            print("Failed to parse FIT file")
    else:
        print("Usage: python fit_parser.py <path_to_fit_file>")

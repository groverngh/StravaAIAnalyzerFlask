"""
Google Sheets data fetcher for WhatsApp Weekly Summary Bot
"""
from google.oauth2 import service_account
from googleapiclient.discovery import build
from whatsapp_bot.config import (
    GOOGLE_SHEETS_CREDENTIALS_FILE,
    GOOGLE_SHEET_ID,
    GOOGLE_SHEET_NAME
)


def get_sheets_service(readonly=True):
    """Get authenticated Google Sheets service"""
    scope = ['https://www.googleapis.com/auth/spreadsheets.readonly'] if readonly else ['https://www.googleapis.com/auth/spreadsheets']
    creds = service_account.Credentials.from_service_account_file(
        GOOGLE_SHEETS_CREDENTIALS_FILE,
        scopes=scope
    )
    return build('sheets', 'v4', credentials=creds)


def get_athletes_data():
    """Fetch athlete data from Google Sheets

    Returns:
        list: List of athlete dictionaries with keys:
            - athlete (str): Athlete name
            - yearly_distance (float): Total distance in miles
            - number_of_runs (int): Total number of runs
            - current_week (str): Current week mileage (last value from WeeklyVolGen)
            - weekly_volumes (list): All weekly volumes as floats
            - week_labels (list): Week labels from XAxisLabel column
    """
    try:
        service = get_sheets_service(readonly=True)

        # Fetch data from the sheet
        sheet = service.spreadsheets()
        result = sheet.values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f'{GOOGLE_SHEET_NAME}!A:Z'  # Get all columns
        ).execute()

        values = result.get('values', [])
        if not values:
            print("No data found in Google Sheet")
            return []

        # First row is headers
        headers = values[0]
        data = []

        # Debug: Print actual headers found
        print(f"Found headers in Google Sheet: {headers}")

        # Find column indices
        try:
            athlete_idx = headers.index('Athelete')  # Note: Column is spelled 'Athelete' in the sheet
            distance_idx = headers.index('Total Distance(miles)')
            runs_idx = headers.index('Number of Runs')
            weekly_vol_idx = headers.index('WeeklyVolGen')

            # Try to find XAxisLabel column (optional)
            try:
                axis_label_idx = headers.index('XAxisLabel')
                has_axis_labels = True
            except ValueError:
                print("Note: XAxisLabel column not found, week labels will be numbered")
                axis_label_idx = None
                has_axis_labels = False

        except ValueError as e:
            print(f"ERROR - Column not found: {e}")
            print(f"Available columns: {headers}")
            return []

        # Process each row
        for row in values[1:]:  # Skip header row
            if len(row) > max(athlete_idx, distance_idx, runs_idx, weekly_vol_idx):
                # Get weekly volumes (comma-separated)
                weekly_vol_value = row[weekly_vol_idx] if len(row) > weekly_vol_idx else ''
                weekly_volumes = []
                current_week = ''

                if weekly_vol_value:
                    csv_values = weekly_vol_value.split(',')
                    # Parse all weekly volumes as floats
                    for val in csv_values:
                        try:
                            weekly_volumes.append(float(val.strip()))
                        except (ValueError, AttributeError):
                            weekly_volumes.append(0.0)

                    # Current week is the last value
                    current_week = csv_values[-1].strip() if csv_values else ''

                # Get week labels if available
                week_labels = []
                if has_axis_labels and axis_label_idx is not None and len(row) > axis_label_idx:
                    axis_label_value = row[axis_label_idx]
                    if axis_label_value:
                        week_labels = [label.strip() for label in axis_label_value.split(',')]

                # If no labels, create numbered weeks
                if not week_labels and weekly_volumes:
                    week_labels = [f"Week {i+1}" for i in range(len(weekly_volumes))]

                athlete_data = {
                    'athlete': row[athlete_idx] if len(row) > athlete_idx else '',
                    'yearly_distance': float(row[distance_idx]) if len(row) > distance_idx and row[distance_idx] else 0,
                    'number_of_runs': int(row[runs_idx]) if len(row) > runs_idx and row[runs_idx] else 0,
                    'current_week': current_week,
                    'weekly_volumes': weekly_volumes,
                    'week_labels': week_labels
                }
                data.append(athlete_data)

        print(f"Successfully fetched data for {len(data)} athletes")
        return data
    except Exception as e:
        print(f"Error fetching Google Sheets data: {e}")
        return []

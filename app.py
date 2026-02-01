from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from dotenv import load_dotenv
import os
import requests
import openai  # Re-enabled for hybrid OpenAI + Groq support
from groq import Groq
import google.generativeai as genai  # Google Gemini
from datetime import datetime
from urllib.parse import urlencode
import markdown2
import json
import time
import threading
from google.oauth2 import service_account
from googleapiclient.discovery import build
from werkzeug.utils import secure_filename
from fit_parser import parse_fit_file, validate_fit_file

load_dotenv()

# Global lock for rate limiting to prevent race conditions
rate_limit_lock = threading.Lock()

app = Flask(__name__)
app.secret_key = os.urandom(24)

STRAVA_ACTIVITIES_URL = 'https://www.strava.com/api/v3/athlete/activities'
STRAVA_ACTIVITY_DETAIL_URL = 'https://www.strava.com/api/v3/activities/{}'

# OpenAI Configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_DEFAULT_MODEL = os.getenv('OPENAI_DEFAULT_MODEL', 'gpt-4o')
OPENAI_MODELS = os.getenv('OPENAI_MODELS', 'gpt-4o,gpt-4o-mini,o1-mini,o1').split(',') if os.getenv('OPENAI_MODELS') else []

# Groq Configuration
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
GROQ_DEFAULT_MODEL = os.getenv('GROQ_DEFAULT_MODEL', 'llama-3.3-70b-versatile')
GROQ_MODELS = os.getenv('GROQ_MODELS', 'llama-3.3-70b-versatile,llama-3.1-70b-versatile,mixtral-8x7b-32768,gemma2-9b-it').split(',')

# Google Gemini Configuration
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_DEFAULT_MODEL = os.getenv('GEMINI_DEFAULT_MODEL', 'gemini-2.0-flash-exp')
GEMINI_MODELS = os.getenv('GEMINI_MODELS', 'gemini-2.0-flash-exp,gemini-1.5-pro,gemini-1.5-flash').split(',') if os.getenv('GEMINI_MODELS') else []

# Configure Gemini if API key is available
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Combine all models for dropdown (Groq first, then OpenAI, then Gemini if available)
ALL_MODELS = GROQ_MODELS.copy()
if OPENAI_MODELS and OPENAI_API_KEY:
    ALL_MODELS.extend(OPENAI_MODELS)
if GEMINI_MODELS and GEMINI_API_KEY:
    ALL_MODELS.extend(GEMINI_MODELS)

# Determine overall default model (prefer Gemini, then Groq, then OpenAI)
if GEMINI_API_KEY:
    DEFAULT_MODEL = GEMINI_DEFAULT_MODEL
elif GROQ_API_KEY:
    DEFAULT_MODEL = GROQ_DEFAULT_MODEL
elif OPENAI_API_KEY:
    DEFAULT_MODEL = OPENAI_DEFAULT_MODEL
else:
    DEFAULT_MODEL = 'llama-3.3-70b-versatile'

STRAVA_CLIENT_ID = os.getenv('STRAVA_CLIENT_ID')
STRAVA_CLIENT_SECRET = os.getenv('STRAVA_CLIENT_SECRET')
STRAVA_REDIRECT_URI = os.getenv('STRAVA_REDIRECT_URI', 'http://localhost:4200/callback')

# Rate limiting configuration (separate limits for each provider)
NUM_ANALYSIS_OPENAI = int(os.getenv('NUM_ANALYSIS_OPENAI', '0'))  # 0 = unlimited
NUM_ANALYSIS_GROQ = int(os.getenv('NUM_ANALYSIS_GROQ', '0'))  # 0 = unlimited
NUM_ANALYSIS_GEMINI = int(os.getenv('NUM_ANALYSIS_GEMINI', '0'))  # 0 = unlimited
DEBUG_SKIP_LLM = os.getenv('DEBUG_SKIP_LLM', 'false').lower() == 'true'
TOKEN_FILE = 'token_store.json'
GOOGLE_SHEETS_CREDENTIALS_FILE = 'njmaniacs-485422-8e16104bb447.json'
GOOGLE_SHEET_ID = '1POa75jrHHYwyfBAC0aObgc01HEFPnjl7ongLAJhqfa0'
GOOGLE_SHEET_NAME = 'Sheet1'
ATHLETE_CREDS_SHEET_NAME = 'Athelete'
AI_ANALYSIS_SHEET_NAME = 'AI Analysis'

# FIT file upload configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'fit'}
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Configure Flask app for file uploads
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_SIZE

# Token management functions
def save_tokens(access_token, refresh_token, expires_at):
    """Save tokens to persistent storage"""
    token_data = {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'expires_at': expires_at
    }
    with open(TOKEN_FILE, 'w') as f:
        json.dump(token_data, f)

def load_tokens():
    """Load tokens from persistent storage"""
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        with open(TOKEN_FILE, 'r') as f:
            return json.load(f)
    except:
        return None

def refresh_access_token(refresh_token):
    """Refresh the access token using the refresh token"""
    try:
        token_resp = requests.post('https://www.strava.com/oauth/token', data={
            'client_id': STRAVA_CLIENT_ID,
            'client_secret': STRAVA_CLIENT_SECRET,
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token
        })
        if token_resp.ok:
            token_data = token_resp.json()
            access_token = token_data.get('access_token')
            new_refresh_token = token_data.get('refresh_token')
            expires_at = token_data.get('expires_at')
            if access_token and new_refresh_token and expires_at:
                save_tokens(access_token, new_refresh_token, expires_at)
                return access_token
    except:
        pass
    return None

def get_valid_token():
    """Get a valid access token, refreshing if necessary"""
    tokens = load_tokens()
    if not tokens:
        return None

    # Check if token is expired (with 5 minute buffer)
    if tokens['expires_at'] <= int(time.time()) + 300:
        # Token is expired or about to expire, refresh it
        new_token = refresh_access_token(tokens['refresh_token'])
        if new_token:
            return new_token
        return None

    return tokens['access_token']

def get_token():
    """Get token from session or storage, with auto-refresh"""
    # First try session
    token = session.get('token')
    if token:
        return token

    # Fall back to stored token with auto-refresh
    token = get_valid_token()
    if token:
        session['token'] = token
        return token

    return None

# Google Sheets functions
def get_sheets_service(readonly=True):
    """Get authenticated Google Sheets service"""
    scope = ['https://www.googleapis.com/auth/spreadsheets.readonly'] if readonly else ['https://www.googleapis.com/auth/spreadsheets']
    creds = service_account.Credentials.from_service_account_file(
        GOOGLE_SHEETS_CREDENTIALS_FILE,
        scopes=scope
    )
    return build('sheets', 'v4', credentials=creds)

def get_athletes_data():
    """Fetch athlete data from Google Sheets"""
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
            return []

        # First row is headers
        headers = values[0]
        data = []

        # Debug: Print actual headers found
        print(f"DEBUG: Found headers in Google Sheet: {headers}")

        # Find column indices
        try:
            athlete_idx = headers.index('Athelete')  # Note: Column is spelled 'Athelete' in the sheet
            distance_idx = headers.index('Total Distance(miles)')
            runs_idx = headers.index('Number of Runs')
            weekly_vol_idx = headers.index('WeeklyVolGen')
        except ValueError as e:
            print(f"ERROR - Column not found: {e}")
            print(f"Available columns: {headers}")
            return []

        # Process each row
        for row in values[1:]:  # Skip header row
            if len(row) > max(athlete_idx, distance_idx, runs_idx, weekly_vol_idx):
                # Get the last value from WeeklyVolGen (comma-separated)
                weekly_vol_value = row[weekly_vol_idx] if len(row) > weekly_vol_idx else ''
                current_week = ''
                if weekly_vol_value:
                    csv_values = weekly_vol_value.split(',')
                    current_week = csv_values[-1].strip() if csv_values else ''

                athlete_data = {
                    'athlete': row[athlete_idx] if len(row) > athlete_idx else '',
                    'yearly_distance': float(row[distance_idx]) if len(row) > distance_idx and row[distance_idx] else 0,
                    'number_of_runs': int(row[runs_idx]) if len(row) > runs_idx and row[runs_idx] else 0,
                    'current_week': current_week
                }
                data.append(athlete_data)

        return data
    except Exception as e:
        print(f"Error fetching Google Sheets data: {e}")
        return []

def get_athlete_credentials(athlete_name=None):
    """Fetch athlete Strava credentials from Google Sheets"""
    try:
        service = get_sheets_service(readonly=True)
        sheet = service.spreadsheets()
        result = sheet.values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f'{ATHLETE_CREDS_SHEET_NAME}!A:G'
        ).execute()

        values = result.get('values', [])
        if not values:
            return None if athlete_name else []

        headers = values[0]
        print(f"DEBUG: Athlete credentials headers: {headers}")

        try:
            id_idx = headers.index('ID')
            name_idx = headers.index('Name')
            refresh_token_idx = headers.index('Refresh_token')
            access_token_idx = headers.index('Access_token')
            expires_at_idx = headers.index('Expires_at(EPOC)')
        except ValueError as e:
            print(f"ERROR - Column not found in Athelete sheet: {e}")
            print(f"Available columns: {headers}")
            return None if athlete_name else []

        athletes_creds = []
        for row_num, row in enumerate(values[1:], start=2):  # Start at 2 for actual row number
            if len(row) > max(id_idx, name_idx, refresh_token_idx, access_token_idx, expires_at_idx):
                strava_id = row[id_idx] if len(row) > id_idx else ''
                name = row[name_idx] if len(row) > name_idx else ''

                # Skip if not a valid Strava ID
                if not strava_id or strava_id == 'StravaSetupNeeded':
                    continue

                athlete_cred = {
                    'name': name,
                    'strava_id': strava_id,
                    'refresh_token': row[refresh_token_idx] if len(row) > refresh_token_idx else '',
                    'access_token': row[access_token_idx] if len(row) > access_token_idx else '',
                    'expires_at': int(row[expires_at_idx]) if len(row) > expires_at_idx and row[expires_at_idx] else 0,
                    'row_number': row_num
                }

                if athlete_name:
                    if name == athlete_name:
                        return athlete_cred
                else:
                    athletes_creds.append(athlete_cred)

        return None if athlete_name else athletes_creds
    except Exception as e:
        print(f"Error fetching athlete credentials: {e}")
        return None if athlete_name else []

def update_athlete_tokens(row_number, access_token, refresh_token, expires_at):
    """Update athlete tokens in Google Sheets"""
    try:
        service = get_sheets_service(readonly=False)

        # Calculate expires_in (usually 6 hours = 21600 seconds)
        expires_in = expires_at - int(time.time())

        # Format expires_at as readable date
        from datetime import datetime as dt
        expires_at_readable = dt.fromtimestamp(expires_at).strftime('%Y-%m-%d %H:%M:%S')

        # Update columns D (Access_token), C (Refresh_token), E (Expires_at(EPOC)), F (Expires_in), G (Expires at)
        values = [
            [refresh_token, access_token, str(expires_at), str(expires_in), expires_at_readable]
        ]

        body = {
            'values': values
        }

        # Update range C:G for the specific row
        range_name = f'{ATHLETE_CREDS_SHEET_NAME}!C{row_number}:G{row_number}'

        result = service.spreadsheets().values().update(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=range_name,
            valueInputOption='RAW',
            body=body
        ).execute()

        print(f"Updated {result.get('updatedCells')} cells for row {row_number}")
        return True
    except Exception as e:
        print(f"Error updating athlete tokens: {e}")
        return False

def get_model_provider(model_name):
    """Determine which provider a model belongs to

    Args:
        model_name (str): Model identifier

    Returns:
        str: 'openai', 'groq', or 'gemini'
    """
    if model_name in OPENAI_MODELS:
        return 'openai'
    elif model_name in GEMINI_MODELS:
        return 'gemini'
    else:
        return 'groq'

def get_client_ip():
    """Get client IP address, handling proxies"""
    if request.headers.get('X-Forwarded-For'):
        # Get the first IP in the X-Forwarded-For chain (client IP)
        ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
    elif request.headers.get('X-Real-IP'):
        ip = request.headers.get('X-Real-IP')
    else:
        ip = request.remote_addr
    return ip

def check_analysis_limit(ip_address, provider='groq'):
    """Check if IP address has exceeded daily analysis limit for a specific provider

    Args:
        ip_address (str): Client IP address
        provider (str): 'openai', 'groq', or 'gemini'

    Returns:
        tuple: (allowed (bool), count (int), limit (int))
    """
    # Get the appropriate limit based on provider
    if provider == 'openai':
        limit = NUM_ANALYSIS_OPENAI
    elif provider == 'gemini':
        limit = NUM_ANALYSIS_GEMINI
    else:
        limit = NUM_ANALYSIS_GROQ

    # If limit is -1, block all analyses
    if limit == -1:
        return False, 0, -1

    # If limit is 0, unlimited analyses allowed
    if limit == 0:
        return True, 0, 0

    try:
        service = get_sheets_service(readonly=True)

        # Fetch data from AI Analysis sheet (now includes provider in column F)
        sheet = service.spreadsheets()
        result = sheet.values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f'{AI_ANALYSIS_SHEET_NAME}!A:F'
        ).execute()

        values = result.get('values', [])
        if not values:
            # No data yet, allow analysis
            return True, 0, limit

        # Get today's date
        today = datetime.now().strftime('%Y-%m-%d')

        # Count analyses for this IP today for this provider
        count = 0
        for row in values[1:]:  # Skip header row (row 0)
            if len(row) >= 3:
                row_ip = row[0] if len(row) > 0 else ''
                row_date = row[2] if len(row) > 2 else ''
                row_provider = row[5] if len(row) > 5 else 'groq'  # Default to groq for legacy rows

                if row_ip == ip_address and row_date == today and row_provider == provider:
                    count += 1

        # Debug logging
        print(f"[Rate Limit Check] IP: {ip_address}, Provider: {provider}, Date: {today}, Count: {count}, Limit: {limit}")
        print(f"[Rate Limit Check] Total rows in sheet: {len(values)}, Data rows: {len(values)-1}")

        # Check if limit would be exceeded
        # count represents analyses ALREADY completed
        # If count >= limit, we've used our quota, so block
        allowed = count < limit

        print(f"[Rate Limit Check] Allowed: {allowed} (count {count} < limit {limit})")

        return allowed, count, limit

    except Exception as e:
        print(f"Error checking analysis limit: {e}")
        # On error, block the analysis (fail closed) to prevent abuse
        return False, 0, limit

def log_analysis_request(ip_address, athlete_name=None, activity_id=None, provider='groq', model=None):
    """Log analysis request to Google Sheets

    Args:
        ip_address (str): Client IP address
        athlete_name (str, optional): Athlete name if logged in
        activity_id (str, optional): Activity ID analyzed
        provider (str): 'openai', 'groq', or 'gemini'
        model (str, optional): Specific model used
    """
    try:
        service = get_sheets_service(readonly=False)

        # Get current timestamp
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        date = datetime.now().strftime('%Y-%m-%d')

        # Prepare row data (columns A-F)
        values = [[
            ip_address,
            timestamp,
            date,
            athlete_name or 'Unknown',
            str(activity_id) if activity_id else '',
            provider,
            model or ''
        ]]

        body = {
            'values': values
        }

        # Append to AI Analysis sheet
        result = service.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f'{AI_ANALYSIS_SHEET_NAME}!A:G',
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()

        print(f"[Rate Limit Log] Successfully logged: IP={ip_address}, Provider={provider}, Model={model}, Date={date}, Athlete={athlete_name}, Activity={activity_id}")
        return True
    except Exception as e:
        print(f"Error logging analysis request: {e}")
        return False

def strip_activity_data(activity):
    """Strip out images and unnecessary data from activity JSON to save tokens

    Args:
        activity (dict): Raw activity data from Strava API

    Returns:
        dict: Cleaned activity data without images and large unnecessary fields
    """
    # Create a copy to avoid modifying the original
    cleaned_activity = activity.copy()

    # Remove photo/image fields (these waste tokens and aren't useful for analysis)
    fields_to_remove = [
        'photos',  # Photo data
        'total_photo_count',  # Photo count
        'map',  # Map contains polyline and image URLs - usually very large
        'segment_efforts',  # Can be very large, not needed for general analysis
        'best_efforts',  # Can be large
        'laps',  # Can be large, usually redundant with splits
        'splits_metric',  # Keep splits_standard (miles), remove metric (km)
        'athlete',  # Athlete profile data not needed
        'similar_activities',  # Not needed
        'device_name',  # Not critical
        'gear',  # Gear details not critical
        'average_temp',  # Watch temperature affected by body heat, unreliable
        'temp',  # Temperature reading, unreliable from watch
    ]

    for field in fields_to_remove:
        cleaned_activity.pop(field, None)

    return cleaned_activity

def get_athlete_token(athlete_name):
    """Get valid token for a specific athlete, refreshing if necessary"""
    creds = get_athlete_credentials(athlete_name)
    if not creds:
        return None

    # Check if token is expired (with 5 minute buffer)
    if creds['expires_at'] <= int(time.time()) + 300:
        # Token is expired or about to expire, refresh it
        try:
            token_resp = requests.post('https://www.strava.com/oauth/token', data={
                'client_id': STRAVA_CLIENT_ID,
                'client_secret': STRAVA_CLIENT_SECRET,
                'grant_type': 'refresh_token',
                'refresh_token': creds['refresh_token']
            })
            if token_resp.ok:
                token_data = token_resp.json()
                new_access_token = token_data.get('access_token')
                new_refresh_token = token_data.get('refresh_token')
                new_expires_at = token_data.get('expires_at')

                if new_access_token and new_refresh_token and new_expires_at:
                    # Update the sheet with new tokens
                    update_athlete_tokens(creds['row_number'], new_access_token, new_refresh_token, new_expires_at)
                    return new_access_token
        except Exception as e:
            print(f"Error refreshing athlete token: {e}")
            return None

    return creds['access_token']

@app.route('/')
def index():
    """Main landing page - Athlete Summary"""
    return redirect(url_for('athletes'))

@app.route('/my-activities', methods=['GET', 'POST'])
def my_activities():
    """Personal Strava activity analyzer"""
    if request.method == 'POST':
        date = request.form['date']
        end_date = request.form.get('end_date', '').strip()
        analysis_query = request.form.get('analysis_query', '').strip()
        session['date'] = date
        session['end_date'] = end_date
        session['analysis_query'] = analysis_query

        # Check if we have a valid token already
        valid_token = get_valid_token()
        if valid_token:
            # Skip OAuth flow, go directly to fetching activities
            session['token'] = valid_token
            return redirect(url_for('fetch_activities'))

        # Start OAuth flow only if no valid token exists
        params = {
            'client_id': STRAVA_CLIENT_ID,
            'response_type': 'code',
            'redirect_uri': STRAVA_REDIRECT_URI,
            'approval_prompt': 'auto',  # Changed from 'force' to 'auto' to avoid re-authorization
            'scope': 'activity:read_all'
        }
        auth_url = f"https://www.strava.com/oauth/authorize?{urlencode(params)}"
        return redirect(auth_url)
    return render_template('my_activities.html')

@app.route('/callback')
def callback():
    code = request.args.get('code')
    date = session.get('date')
    end_date = session.get('end_date', '')
    analysis_query = session.get('analysis_query', '')
    if not code or not date:
        return redirect(url_for('index'))
    # Exchange code for access token
    token_resp = requests.post('https://www.strava.com/oauth/token', data={
        'client_id': STRAVA_CLIENT_ID,
        'client_secret': STRAVA_CLIENT_SECRET,
        'code': code,
        'grant_type': 'authorization_code'
    })
    token_data = token_resp.json()
    access_token = token_data.get('access_token')
    refresh_token = token_data.get('refresh_token')
    expires_at = token_data.get('expires_at')

    if not access_token or not refresh_token:
        return render_template('my_activities.html', error='Failed to get Strava access token.')

    # Save tokens persistently
    save_tokens(access_token, refresh_token, expires_at)
    session['token'] = access_token
    return redirect(url_for('fetch_activities'))

@app.route('/fetch_activities')
def fetch_activities():
    """Fetch activities for the date range stored in session"""
    token = session.get('token')
    date = session.get('date')
    end_date = session.get('end_date', '')
    analysis_query = session.get('analysis_query', '')

    if not date:
        return redirect(url_for('index'))

    # Get valid token (will auto-refresh if needed)
    if not token:
        token = get_valid_token()
        if not token:
            return redirect(url_for('index'))
        session['token'] = token

    # Fetch activities for the date range
    start_dt = datetime.strptime(date, '%Y-%m-%d')
    if end_date:
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    else:
        end_dt = start_dt
    after = int(start_dt.replace(hour=0, minute=0, second=0).timestamp())
    before = int(end_dt.replace(hour=23, minute=59, second=59).timestamp())
    headers = {'Authorization': f'Bearer {token}'}
    params = {'after': after, 'before': before, 'per_page': 100}
    resp = requests.get(STRAVA_ACTIVITIES_URL, headers=headers, params=params)
    activities = resp.json() if resp.ok else []
    # Convert distances to miles and add pace (min/mile)
    for act in activities:
        if 'distance' in act:
            act['distance_miles'] = round(act['distance'] / 1609.34, 2)
        if 'moving_time' in act and act.get('distance_miles', 0) > 0:
            act['pace_min_per_mile'] = round((act['moving_time'] / 60) / act['distance_miles'], 2)
    if not activities:
        return render_template('my_activities.html', error='No activities found for this date range.')
    if len(activities) == 1:
        return redirect(url_for('activity_detail', activity_id=activities[0]['id']))
    return render_template('select.html',
                         activities=activities,
                         analysis_query=analysis_query,
                         groq_models=GROQ_MODELS,
                         openai_models=OPENAI_MODELS,
                         gemini_models=GEMINI_MODELS,
                         default_model=DEFAULT_MODEL)

@app.route('/activity/<int:activity_id>', methods=['GET', 'POST'])
def activity_detail(activity_id):
    # Check if we're viewing a specific athlete's activities
    token = session.get('athlete_token')
    if not token:
        token = get_token()
    analysis_query = session.get('analysis_query', '')
    if not token:
        return redirect(url_for('index'))
    headers = {'Authorization': f'Bearer {token}'}
    resp = requests.get(STRAVA_ACTIVITY_DETAIL_URL.format(activity_id), headers=headers)
    activity = resp.json() if resp.ok else None
    analysis = None
    analysis_html = None
    error = None
    if not activity:
        error = 'Failed to fetch activity details from Strava.'
    if request.method == 'POST' and activity:
        try:
            # Use default model (prefer Groq if available)
            provider = get_model_provider(DEFAULT_MODEL)

            # Initialize appropriate client
            if provider == 'openai':
                llm_client = openai.OpenAI(api_key=OPENAI_API_KEY)
            elif provider == 'gemini':
                llm_client = genai.GenerativeModel(DEFAULT_MODEL)
            else:
                llm_client = Groq(api_key=GROQ_API_KEY)

            system_prompt = """You are a fitness data analyst.

CRITICAL - STRAVA API DATA FORMAT:
- ALL distances in the JSON are in METERS (not miles or kilometers)
- ALL elevations in the JSON are in METERS (not feet)
- ALL speeds are in METERS PER SECOND (not mph or min/mile)
- ALL temperatures are in CELSIUS (not Fahrenheit)
- Times are in SECONDS

REQUIRED CONVERSIONS FOR YOUR ANALYSIS:
- Distance: divide meters by 1609.34 to get miles
- Elevation: divide meters by 0.3048 to get feet
- Pace: (moving_time_seconds / distance_meters) * 26.8224 = minutes per mile
- Speed: multiply meters/second by 2.23694 to get mph
- Temperature: (celsius × 9/5) + 32 = Fahrenheit

OUTPUT FORMAT - USE US UNITS:
- Display all distances in MILES (e.g., "5.2 miles")
- Display all elevations in FEET (e.g., "450 feet")
- Display pace in MINUTES PER MILE (e.g., "8:30 min/mi")
- Display temperatures in FAHRENHEIT (e.g., "72°F")
- Display splits in miles unless the activity has custom kilometer splits

Provide clear, actionable insights based on properly converted data."""

            # Strip out images and unnecessary data to save tokens
            cleaned_activity = strip_activity_data(activity)

            prompt = f"Analyze this Strava activity in detail: {cleaned_activity}"
            if analysis_query:
                prompt += f"\nFocus on: {analysis_query}"

            # Check if debug mode is enabled
            if DEBUG_SKIP_LLM:
                # Save prompt to file instead of calling OpenAI
                import os as debug_os

                # Create debug_prompts directory if it doesn't exist
                debug_dir = 'debug_prompts'
                debug_os.makedirs(debug_dir, exist_ok=True)

                # Generate filename with timestamp
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f'prompt_{timestamp}_activity_{activity_id}_detail.txt'
                filepath = debug_os.path.join(debug_dir, filename)

                # Write prompt to file
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write("=" * 80 + "\n")
                    f.write("DEBUG MODE: LLM Call Skipped - Prompt Saved to File\n")
                    f.write("=" * 80 + "\n\n")
                    f.write(f"Activity ID: {activity_id}\n")
                    f.write(f"Analysis Query: {analysis_query or 'Not specified'}\n")
                    f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("\n" + "=" * 80 + "\n")
                    f.write("SYSTEM PROMPT\n")
                    f.write("=" * 80 + "\n\n")
                    f.write(system_prompt)
                    f.write("\n\n" + "=" * 80 + "\n")
                    f.write("USER PROMPT\n")
                    f.write("=" * 80 + "\n\n")
                    f.write(prompt)
                    f.write("\n\n" + "=" * 80 + "\n")
                    f.write("END OF PROMPT\n")
                    f.write("=" * 80 + "\n")

                print(f"DEBUG MODE: Prompt saved to {filepath}")

                # Return response with file path
                analysis = f"""# Debug Mode - LLM Call Skipped

**Analysis Query:** {analysis_query or 'Not specified'}

The actual LLM call was skipped because `DEBUG_SKIP_LLM` is enabled.

**Prompt saved to:** `{filepath}`

You can open this file to see the exact system prompt and user prompt that would have been sent to the LLM.

To make actual API calls, set `DEBUG_SKIP_LLM=false` in your .env file.
"""
                analysis_html = markdown2.markdown(analysis)
            else:
                # Call LLM API (OpenAI, Groq, or Gemini)
                if provider == 'gemini':
                    # Gemini API format
                    full_prompt = f"{system_prompt}\n\n{prompt}"
                    response = llm_client.generate_content(full_prompt)
                    analysis = response.text.strip()
                else:
                    # OpenAI/Groq API format
                    response = llm_client.chat.completions.create(
                        model=DEFAULT_MODEL,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt}
                        ]
                    )
                    analysis = response.choices[0].message.content.strip()

                analysis_html = markdown2.markdown(analysis)
        except Exception as e:
            error = f'LLM API error: {e}'
    return render_template('activity.html', activity=activity, analysis=analysis, analysis_html=analysis_html, error=error)

@app.route('/api/analyze_activity/<activity_id>', methods=['POST'])
def api_analyze_activity(activity_id):
    """API endpoint for analyzing a single activity with detailed data"""
    # Get client IP address
    client_ip = get_client_ip()

    # Get analysis mode, training intent, and model from request body
    request_data = request.get_json() or {}
    analysis_mode = request_data.get('mode', 'nerd')
    training_intent = request_data.get('training_intent', '')
    selected_model = request_data.get('model', DEFAULT_MODEL)

    # Determine provider from selected model
    provider = get_model_provider(selected_model)

    # Get the appropriate rate limit for this provider
    if provider == 'openai':
        rate_limit = NUM_ANALYSIS_OPENAI
    elif provider == 'gemini':
        rate_limit = NUM_ANALYSIS_GEMINI
    else:
        rate_limit = NUM_ANALYSIS_GROQ

    # Initialize for test message display
    current_count = 0
    limit = 0

    # Check if analysis is blocked entirely (rate_limit=-1)
    if rate_limit == -1:
        return jsonify({
            'error': f'{provider.upper()} AI analysis is currently disabled. Please contact the administrator.',
            'limit_reached': True,
            'current_count': 0,
            'limit': -1
        }), 429  # 429 Too Many Requests

    # Check if analysis limit is enforced (rate_limit > 0)
    if rate_limit > 0:
        # Use a lock to make check+log atomic and prevent race conditions
        with rate_limit_lock:
            allowed, current_count, limit = check_analysis_limit(client_ip, provider)
            if not allowed:
                return jsonify({
                    'error': f'Daily {provider.upper()} analysis limit reached. You have used {current_count}/{limit} {provider.upper()} analyses today. Limit resets at midnight.',
                    'limit_reached': True,
                    'current_count': current_count,
                    'limit': limit
                }), 429  # 429 Too Many Requests

            # Log the analysis request immediately within the lock
            # This ensures the count is incremented before the next request can check
            athlete_name = session.get('athlete_name', None)
            log_analysis_request(client_ip, athlete_name, activity_id, provider, selected_model)
    else:
        # rate_limit=0 means unlimited
        limit = 'unlimited'

    # Check if this is a FIT file activity (ID starts with "fit_")
    if str(activity_id).startswith('fit_'):
        # Get FIT activity from session
        activity = session.get('fit_activity')
        if not activity:
            return jsonify({'error': 'FIT file activity not found in session. Please upload the file again.'}), 404

        # Get analysis query from session (same as Strava activities)
        analysis_query = session.get('analysis_query', '')

        # FIT activities already have cleaned data structure
        cleaned_activity = strip_activity_data(activity)
    else:
        # This is a Strava activity - fetch from API
        token = session.get('athlete_token')
        if not token:
            token = get_token()
        analysis_query = session.get('analysis_query', '')
        if not token:
            return jsonify({'error': 'Not authenticated'}), 401

        # Fetch detailed activity data from Strava
        headers = {'Authorization': f'Bearer {token}'}
        resp = requests.get(STRAVA_ACTIVITY_DETAIL_URL.format(activity_id), headers=headers)

        if not resp.ok:
            return jsonify({'error': 'Failed to fetch activity details from Strava'}), 500

        activity = resp.json()

        # Strip out images and unnecessary data to save tokens
        cleaned_activity = strip_activity_data(activity)

    # Analyze with selected provider (OpenAI, Groq, or Gemini)
    try:
        # Initialize appropriate client based on provider
        if provider == 'openai':
            llm_client = openai.OpenAI(api_key=OPENAI_API_KEY)
        elif provider == 'gemini':
            llm_client = genai.GenerativeModel(selected_model)
        else:
            llm_client = Groq(api_key=GROQ_API_KEY)

        # Define system prompts based on analysis mode
        if analysis_mode == 'maniac':
            system_prompt = """You are my over-achieving endurance coach in "maniac mode."

CRITICAL - DATA FORMAT (Strava or FIT file):
- ALL distances in the JSON are in METERS (not miles or kilometers)
- ALL elevations in the JSON are in METERS (not feet)
- ALL speeds are in METERS PER SECOND
- ALL temperatures are in CELSIUS (not Fahrenheit)
- Times are in SECONDS
- CONVERT TO US UNITS: meters ÷ 1609.34 = miles | meters ÷ 0.3048 = feet | (moving_time_sec / distance_m) × 26.8224 = min/mile | (celsius × 9/5) + 32 = °F

Analyze this activity with brutal honesty. Assume I want to be faster, stronger, and more disciplined than 99% of athletes.

Rules:
- Be blunt, direct, and unsympathetic to excuses
- Call out inefficiencies, laziness, poor pacing, weak execution, and missed opportunities
- Point out where I left performance on the table
- If something was good, acknowledge it briefly, then push for a higher standard
- Compare my execution against what an elite amateur or competitive age-grouper would do

Analyze:
- Pacing discipline (splits, variability, fade)
- Effort vs outcome (did I earn the result?)
- Training intent vs actual execution
- Strengths I am under-leveraging
- Specific, uncomfortable improvements I must make

Output format:
- One-sentence harsh summary
- What I did wrong (bullet points, no sugarcoating)
- What I did right (short)
- What a serious athlete would do differently next time
- One non-negotiable action item for my next workout

Display all metrics in US units (miles, feet, min/mile pace).

Do not motivate me emotionally. Fix me."""

        elif analysis_mode == 'nice':
            system_prompt = """You are my supportive endurance coach in "nice guy mode."

CRITICAL - DATA FORMAT (Strava or FIT file):
- ALL distances in the JSON are in METERS (not miles or kilometers)
- ALL elevations in the JSON are in METERS (not feet)
- ALL speeds are in METERS PER SECOND
- ALL temperatures are in CELSIUS (not Fahrenheit)
- Times are in SECONDS
- CONVERT TO US UNITS: meters ÷ 1609.34 = miles | meters ÷ 0.3048 = feet | (moving_time_sec / distance_m) × 26.8224 = min/mile | (celsius × 9/5) + 32 = °F

Analyze this activity with a balanced, encouraging, and constructive tone. Assume I am committed and consistent, and I want to improve sustainably.

Guidelines:
- Start with what went well and why it matters
- Frame weaknesses as opportunities, not failures
- Focus on learning and long-term progression
- Avoid harsh language or shaming

Analyze:
- Overall effort and pacing quality
- Alignment with training intent
- Signs of improving fitness or durability
- Small adjustments that could make this workout better next time

Output format:
- Positive summary of the session
- Key strengths from this activity
- Areas to gently improve
- One or two actionable suggestions for the next similar workout
- What this workout contributes to my broader training

Display all metrics in US units (miles, feet, min/mile pace).

Keep it honest, but kind."""

        elif analysis_mode == 'nerd':
            system_prompt = """You are my sports science–oriented data analyst in "data nerd mode."

CRITICAL - DATA FORMAT (Strava or FIT file):
- ALL distances in the JSON are in METERS (not miles or kilometers)
- ALL elevations in the JSON are in METERS (not feet)
- ALL speeds are in METERS PER SECOND
- ALL temperatures are in CELSIUS (not Fahrenheit)
- Times are in SECONDS
- CONVERT TO US UNITS: meters ÷ 1609.34 = miles | meters ÷ 0.3048 = feet | (moving_time_sec / distance_m) × 26.8224 = min/mile | (celsius × 9/5) + 32 = °F

Analyze this activity purely through data, physiology, and execution quality. Assume I want objective insights, not motivation.

Rules:
- Be precise, quantitative, and evidence-based
- Avoid hype, emotion, or moral judgment
- If data is missing, state assumptions explicitly
- Distinguish correlation vs causation

Analyze:
- Pacing metrics (splits, variance, coefficient of variation if possible)
- Intensity distribution (time in zones, HR–pace decoupling, drift)
- Efficiency indicators (pace vs HR, cadence trends, stride consistency if available)
- Fatigue signals (late-run fade, HR drift, power drop if applicable)
- Execution vs stated training intent

Derived insights:
- What this workout implies about current fitness
- Whether this session was optimally stressful, undercooked, or excessive
- What adaptations this workout is likely to drive

Output format:
- Data summary (key metrics only)
- Observed patterns and anomalies
- Interpretation (what the data suggests, with confidence level)
- Limitations of this analysis
- One data-backed recommendation for future sessions

Display all metrics in US units (miles, feet, min/mile pace).

Do not coach emotionally. Let the data speak."""

        else:
            # Fallback for any unexpected mode
            system_prompt = """You are a fitness data analyst.

CRITICAL - DATA FORMAT (Strava or FIT file):
- ALL distances in the JSON are in METERS (not miles or kilometers)
- ALL elevations in the JSON are in METERS (not feet)
- ALL speeds are in METERS PER SECOND (not mph or min/mile)
- ALL temperatures are in CELSIUS (not Fahrenheit)
- Times are in SECONDS

REQUIRED CONVERSIONS FOR YOUR ANALYSIS:
- Distance: divide meters by 1609.34 to get miles
- Elevation: divide meters by 0.3048 to get feet
- Pace: (moving_time_seconds / distance_meters) * 26.8224 = minutes per mile
- Speed: multiply meters/second by 2.23694 to get mph
- Temperature: (celsius × 9/5) + 32 = Fahrenheit

OUTPUT FORMAT - USE US UNITS:
- Display all distances in MILES (e.g., "5.2 miles")
- Display all elevations in FEET (e.g., "450 feet")
- Display pace in MINUTES PER MILE (e.g., "8:30 min/mi")
- Display temperatures in FAHRENHEIT (e.g., "72°F")
- Display splits in miles unless the activity has custom kilometer splits

Provide clear, actionable insights based on properly converted data."""

        # Determine if this is a FIT file or Strava activity for the prompt
        activity_source = "FIT file activity" if str(activity_id).startswith('fit_') else "Strava activity"

        prompt = f"Analyze this {activity_source} in detail: {cleaned_activity}"
        if training_intent:
            prompt += f"\n\nStated training intent: {training_intent}"
            prompt += "\nEvaluate whether the execution matched the stated training intent."
        if analysis_query:
            prompt += f"\nFocus on: {analysis_query}"

        # Check if debug mode is enabled
        if DEBUG_SKIP_LLM:
            # Save prompt to file instead of calling OpenAI
            import os as debug_os

            # Create debug_prompts directory if it doesn't exist
            debug_dir = 'debug_prompts'
            debug_os.makedirs(debug_dir, exist_ok=True)

            # Generate filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'prompt_{timestamp}_activity_{activity_id}.txt'
            filepath = debug_os.path.join(debug_dir, filename)

            # Write prompt to file
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write("DEBUG MODE: LLM Call Skipped - Prompt Saved to File\n")
                f.write("=" * 80 + "\n\n")
                f.write(f"Activity ID: {activity_id}\n")
                f.write(f"Analysis Mode: {analysis_mode}\n")
                f.write(f"Training Intent: {training_intent or 'Not specified'}\n")
                f.write(f"Analysis Query: {analysis_query or 'Not specified'}\n")
                f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("\n" + "=" * 80 + "\n")
                f.write("SYSTEM PROMPT\n")
                f.write("=" * 80 + "\n\n")
                f.write(system_prompt)
                f.write("\n\n" + "=" * 80 + "\n")
                f.write("USER PROMPT\n")
                f.write("=" * 80 + "\n\n")
                f.write(prompt)
                f.write("\n\n" + "=" * 80 + "\n")
                f.write("END OF PROMPT\n")
                f.write("=" * 80 + "\n")

            print(f"DEBUG MODE: Prompt saved to {filepath}")

            # Return response with file path
            analysis = f"""# Debug Mode - LLM Call Skipped

**Analysis Mode:** {analysis_mode}
**Training Intent:** {training_intent or 'Not specified'}
**Analysis Query:** {analysis_query or 'Not specified'}

The actual LLM call was skipped because `DEBUG_SKIP_LLM` is enabled.

**Prompt saved to:** `{filepath}`

You can open this file to see the exact system prompt and user prompt that would have been sent to the LLM.

To make actual API calls, set `DEBUG_SKIP_LLM=false` in your .env file.
"""
            analysis_html = markdown2.markdown(analysis)
        else:
            # Call LLM API (OpenAI, Groq, or Gemini based on selected model)
            if provider == 'gemini':
                # Gemini API format - combine system and user prompts
                full_prompt = f"{system_prompt}\n\n{prompt}"
                response = llm_client.generate_content(full_prompt)
                analysis = response.text.strip()
            else:
                # OpenAI/Groq API format
                response = llm_client.chat.completions.create(
                    model=selected_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ]
                )
                analysis = response.choices[0].message.content.strip()

            analysis_html = markdown2.markdown(analysis)

        return jsonify({
            'success': True,
            'analysis': analysis,
            'analysis_html': analysis_html
        })
    except Exception as e:
        return jsonify({'error': f'LLM API error: {str(e)}'}), 500

@app.route('/analyze_list', methods=['GET', 'POST'])
def analyze_list():
    token = get_token()
    date = session.get('date')
    end_date = session.get('end_date', '')
    if request.method == 'POST':
        analysis_query = request.form.get('analysis_query', '').strip()
        if analysis_query:
            session['analysis_query'] = analysis_query
    analysis_query = session.get('analysis_query', '')
    if not token or not date:
        return redirect(url_for('index'))
    # Fetch activities again for the date range
    start_dt = datetime.strptime(date, '%Y-%m-%d')
    if end_date:
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    else:
        end_dt = start_dt
    after = int(start_dt.replace(hour=0, minute=0, second=0).timestamp())
    before = int(end_dt.replace(hour=23, minute=59, second=59).timestamp())
    headers = {'Authorization': f'Bearer {token}'}
    params = {'after': after, 'before': before, 'per_page': 100}
    resp = requests.get(STRAVA_ACTIVITIES_URL, headers=headers, params=params)
    activities = resp.json() if resp.ok else []
    for act in activities:
        if 'distance' in act:
            act['distance_miles'] = round(act['distance'] / 1609.34, 2)
        if 'moving_time' in act and act.get('distance_miles', 0) > 0:
            act['pace_min_per_mile'] = round((act['moving_time'] / 60) / act['distance_miles'], 2)
    analysis = None
    analysis_html = None
    summary = None
    if request.method == 'POST' and 'summarize' in request.form:
        # Summarize activities by type and total time
        from collections import defaultdict
        def seconds_to_hms(seconds):
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            return f"{h:02}:{m:02}:{s:02}"
        type_time = defaultdict(int)
        total_time = 0
        for act in activities:
            t = act.get('type', 'Unknown')
            mt = act.get('moving_time', 0)
            type_time[t] += mt
            total_time += mt
        activity_rows = [
            {'type': k, 'time': seconds_to_hms(v)} for k, v in type_time.items()
        ]
        summary = {
            'activity_rows': activity_rows,
            'total_time': seconds_to_hms(total_time)
        }
    elif request.method == 'POST' or 'analyze_list' in request.args:
        # Use default model (prefer Groq if available)
        provider = get_model_provider(DEFAULT_MODEL)

        # Initialize appropriate client
        if provider == 'openai':
            llm_client = openai.OpenAI(api_key=OPENAI_API_KEY)
        elif provider == 'gemini':
            llm_client = genai.GenerativeModel(DEFAULT_MODEL)
        else:
            llm_client = Groq(api_key=GROQ_API_KEY)

        system_prompt = """You are a fitness data analyst.

CRITICAL - STRAVA API DATA FORMAT:
- ALL distances in the JSON are in METERS (not miles or kilometers)
- ALL elevations in the JSON are in METERS (not feet)
- ALL speeds are in METERS PER SECOND (not mph or min/mile)
- ALL temperatures are in CELSIUS (not Fahrenheit)
- Times are in SECONDS

REQUIRED CONVERSIONS FOR YOUR ANALYSIS:
- Distance: divide meters by 1609.34 to get miles
- Elevation: divide meters by 0.3048 to get feet
- Pace: (moving_time_seconds / distance_meters) * 26.8224 = minutes per mile
- Speed: multiply meters/second by 2.23694 to get mph
- Temperature: (celsius × 9/5) + 32 = Fahrenheit

OUTPUT FORMAT - USE US UNITS:
- Display all distances in MILES (e.g., "5.2 miles")
- Display all elevations in FEET (e.g., "450 feet")
- Display pace in MINUTES PER MILE (e.g., "8:30 min/mi")
- Display temperatures in FAHRENHEIT (e.g., "72°F")
- Display splits in miles unless the activity has custom kilometer splits

Provide clear, actionable insights and trends across all activities based on properly converted data."""

        # Strip out images and unnecessary data from each activity to save tokens
        cleaned_activities = [strip_activity_data(act) for act in activities]

        prompt = f"Analyze this list of Strava activities: {cleaned_activities}"
        if analysis_query:
            prompt += f"\nFocus on: {analysis_query}"
        try:
            # Check if debug mode is enabled
            if DEBUG_SKIP_LLM:
                # Save prompt to file instead of calling OpenAI
                import os as debug_os

                # Create debug_prompts directory if it doesn't exist
                debug_dir = 'debug_prompts'
                debug_os.makedirs(debug_dir, exist_ok=True)

                # Generate filename with timestamp
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f'prompt_{timestamp}_list_analysis.txt'
                filepath = debug_os.path.join(debug_dir, filename)

                # Write prompt to file
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write("=" * 80 + "\n")
                    f.write("DEBUG MODE: LLM Call Skipped - Prompt Saved to File\n")
                    f.write("=" * 80 + "\n\n")
                    f.write(f"Analysis Type: List Analysis\n")
                    f.write(f"Analysis Query: {analysis_query or 'Not specified'}\n")
                    f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("\n" + "=" * 80 + "\n")
                    f.write("SYSTEM PROMPT\n")
                    f.write("=" * 80 + "\n\n")
                    f.write(system_prompt)
                    f.write("\n\n" + "=" * 80 + "\n")
                    f.write("USER PROMPT\n")
                    f.write("=" * 80 + "\n\n")
                    f.write(prompt)
                    f.write("\n\n" + "=" * 80 + "\n")
                    f.write("END OF PROMPT\n")
                    f.write("=" * 80 + "\n")

                print(f"DEBUG MODE: Prompt saved to {filepath}")

                # Return response with file path
                analysis = f"""# Debug Mode - LLM Call Skipped

**Analysis Query:** {analysis_query or 'Not specified'}

This is a mock response for list analysis. The actual LLM call was skipped because `DEBUG_SKIP_LLM` is enabled.

**Prompt saved to:** `{filepath}`

You can open this file to see the exact system prompt and user prompt that would have been sent to the LLM.

To make actual API calls, set `DEBUG_SKIP_LLM=false` in your .env file.
"""
                analysis_html = markdown2.markdown(analysis)
            else:
                # Call LLM API (OpenAI, Groq, or Gemini)
                if provider == 'gemini':
                    # Gemini API format
                    full_prompt = f"{system_prompt}\n\n{prompt}"
                    response = llm_client.generate_content(full_prompt)
                    analysis = response.text.strip()
                else:
                    # OpenAI/Groq API format
                    response = llm_client.chat.completions.create(
                        model=DEFAULT_MODEL,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt}
                        ]
                    )
                    analysis = response.choices[0].message.content.strip()

                analysis_html = markdown2.markdown(analysis)
        except Exception as e:
            analysis = f'LLM API error: {e}'
    return render_template('list_analysis.html', activities=activities, analysis=analysis, analysis_html=analysis_html, analysis_query=analysis_query, summary=summary)

@app.route('/select', methods=['GET', 'POST'])
def select_activity():
    if request.method == 'GET':
        # Show activities after pulling, for GET requests
        token = get_token()
        date = session.get('date')
        end_date = session.get('end_date', '')
        analysis_query = session.get('analysis_query', '')
        if not token or not date:
            return redirect(url_for('index'))
        start_dt = datetime.strptime(date, '%Y-%m-%d')
        if end_date:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        else:
            end_dt = start_dt
        after = int(start_dt.replace(hour=0, minute=0, second=0).timestamp())
        before = int(end_dt.replace(hour=23, minute=59, second=59).timestamp())
        headers = {'Authorization': f'Bearer {token}'}
        params = {'after': after, 'before': before, 'per_page': 100}
        resp = requests.get(STRAVA_ACTIVITIES_URL, headers=headers, params=params)
        activities = resp.json() if resp.ok else []
        for act in activities:
            if 'distance' in act:
                act['distance_miles'] = round(act['distance'] / 1609.34, 2)
            if 'moving_time' in act and act.get('distance_miles', 0) > 0:
                act['pace_min_per_mile'] = round((act['moving_time'] / 60) / act['distance_miles'], 2)
        return render_template('select.html',
                             activities=activities,
                             analysis_query=analysis_query,
                             groq_models=GROQ_MODELS,
                             openai_models=OPENAI_MODELS,
                             default_model=DEFAULT_MODEL)
    activity_id = request.form.get('activity_id')
    analysis_query = request.form.get('analysis_query', '').strip()
    if analysis_query:
        session['analysis_query'] = analysis_query
    if 'analyze_list' in request.form:
        # Use POST instead of redirect to /analyze_list to avoid Bad Request
        return analyze_list()
    if 'summarize' in request.form:
        # Always fetch activities before summarizing
        token = get_token()
        date = session.get('date')
        end_date = session.get('end_date', '')
        if not token or not date:
            return redirect(url_for('index'))
        start_dt = datetime.strptime(date, '%Y-%m-%d')
        if end_date:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        else:
            end_dt = start_dt
        after = int(start_dt.replace(hour=0, minute=0, second=0).timestamp())
        before = int(end_dt.replace(hour=23, minute=59, second=59).timestamp())
        headers = {'Authorization': f'Bearer {token}'}
        params = {'after': after, 'before': before, 'per_page': 100}
        resp = requests.get(STRAVA_ACTIVITIES_URL, headers=headers, params=params)
        activities = resp.json() if resp.ok else []
        for act in activities:
            if 'distance' in act:
                act['distance_miles'] = round(act['distance'] / 1609.34, 2)
            if 'moving_time' in act and act.get('distance_miles', 0) > 0:
                act['pace_min_per_mile'] = round((act['moving_time'] / 60) / act['distance_miles'], 2)
        # Summarize activities by week and type, only for selected types
        import collections
        from datetime import timedelta
        def seconds_to_hms(seconds):
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            return f"{h:02}:{m:02}:{s:02}"
        allowed_types = {'Ride', 'Run', 'Swim', 'WeightTraining', 'Workout'}
        week_data = collections.defaultdict(lambda: collections.defaultdict(int))
        week_totals = collections.defaultdict(int)
        activity_types = set()
        for act in activities:
            t = act.get('type', 'Unknown')
            if t not in allowed_types:
                continue
            dt = datetime.strptime(act['start_date'][:10], '%Y-%m-%d')
            week_start = dt - timedelta(days=dt.weekday())
            week_key = week_start.strftime('%Y-%m-%d')
            mt = act.get('moving_time', 0)
            week_data[week_key][t] += mt
            week_totals[week_key] += mt
            activity_types.add(t)
        # Sort weeks and types
        sorted_weeks = sorted(week_data.keys())
        sorted_types = sorted(activity_types)
        summary_rows = []
        for wk in sorted_weeks:
            row = {'week': wk}
            for t in sorted_types:
                row[t] = seconds_to_hms(week_data[wk][t]) if week_data[wk][t] else ''
            row['total'] = seconds_to_hms(week_totals[wk])
            summary_rows.append(row)
        summary = {
            'activity_types': sorted_types,
            'rows': summary_rows
        }
        return render_template('select.html',
                             activities=activities,
                             analysis_query=analysis_query,
                             summary=summary,
                             groq_models=GROQ_MODELS,
                             openai_models=OPENAI_MODELS,
                             gemini_models=GEMINI_MODELS,
                             default_model=DEFAULT_MODEL)
    return redirect(url_for('activity_detail', activity_id=activity_id))

@app.route('/athletes')
def athletes():
    """Display athlete summary from Google Sheets"""
    # Get sort parameters from query string
    sort_by = request.args.get('sort', 'yearly_distance')
    order = request.args.get('order', 'desc')

    # Fetch data from Google Sheets
    athletes_data = get_athletes_data()

    # Get athlete credentials to check who has valid Strava access
    athlete_creds = get_athlete_credentials()
    valid_strava_names = {cred['name'] for cred in athlete_creds}

    # Add has_strava flag to each athlete
    for athlete in athletes_data:
        athlete['has_strava'] = athlete['athlete'] in valid_strava_names

    # Find max yearly distance and max current week
    max_yearly_distance = max([a['yearly_distance'] for a in athletes_data]) if athletes_data else 0
    max_current_week = max([float(a['current_week']) if a['current_week'] else 0 for a in athletes_data]) if athletes_data else 0

    # Sort the data
    reverse = (order == 'desc')
    if sort_by == 'athlete':
        athletes_data.sort(key=lambda x: x['athlete'].lower(), reverse=reverse)
    elif sort_by == 'yearly_distance':
        athletes_data.sort(key=lambda x: x['yearly_distance'], reverse=reverse)
    elif sort_by == 'number_of_runs':
        athletes_data.sort(key=lambda x: x['number_of_runs'], reverse=reverse)
    elif sort_by == 'current_week':
        athletes_data.sort(key=lambda x: float(x['current_week']) if x['current_week'] else 0, reverse=reverse)

    return render_template('athletes.html', athletes=athletes_data, sort_by=sort_by, order=order,
                         max_yearly_distance=max_yearly_distance, max_current_week=max_current_week)

@app.route('/athlete/<athlete_name>')
def athlete_profile(athlete_name):
    """Display individual athlete profile with ability to fetch their activities"""
    # Get athlete summary from Sheet1
    athletes_data = get_athletes_data()
    athlete_summary = next((a for a in athletes_data if a['athlete'] == athlete_name), None)

    if not athlete_summary:
        return redirect(url_for('athletes'))

    # Get athlete credentials
    athlete_creds = get_athlete_credentials(athlete_name)
    if not athlete_creds:
        return redirect(url_for('athletes'))

    # Store selected athlete in session
    session['selected_athlete'] = athlete_name

    return render_template('athlete_profile.html', athlete=athlete_summary, athlete_name=athlete_name)

@app.route('/athlete/<athlete_name>/activities', methods=['POST'])
def fetch_athlete_activities(athlete_name):
    """Fetch activities for a specific athlete"""
    date = request.form.get('date')
    end_date = request.form.get('end_date', '').strip()
    analysis_query = request.form.get('analysis_query', '').strip()

    if not date:
        return redirect(url_for('athlete_profile', athlete_name=athlete_name))

    # Store in session
    session['date'] = date
    session['end_date'] = end_date
    session['analysis_query'] = analysis_query
    session['selected_athlete'] = athlete_name

    # Get valid token for this athlete
    token = get_athlete_token(athlete_name)
    if not token:
        return render_template('athlete_profile.html',
                             athlete=get_athletes_data(),
                             athlete_name=athlete_name,
                             error='Failed to get valid Strava token for this athlete')

    session['athlete_token'] = token

    # Fetch activities
    start_dt = datetime.strptime(date, '%Y-%m-%d')
    if end_date:
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    else:
        # Default to today if end_date not provided
        end_dt = datetime.now()

    after = int(start_dt.replace(hour=0, minute=0, second=0).timestamp())
    before = int(end_dt.replace(hour=23, minute=59, second=59).timestamp())

    headers = {'Authorization': f'Bearer {token}'}
    params = {'after': after, 'before': before, 'per_page': 100}
    resp = requests.get(STRAVA_ACTIVITIES_URL, headers=headers, params=params)
    activities = resp.json() if resp.ok else []

    # Convert distances to miles and add pace (min/mile)
    for act in activities:
        if 'distance' in act:
            act['distance_miles'] = round(act['distance'] / 1609.34, 2)
        if 'moving_time' in act and act.get('distance_miles', 0) > 0:
            pace_seconds = act['moving_time'] / act['distance_miles']
            pace_min = int(pace_seconds // 60)
            pace_sec = int(pace_seconds % 60)
            act['pace_min_per_mile'] = f"{pace_min}:{pace_sec:02d}"
        else:
            act['pace_min_per_mile'] = 'N/A'

    if not activities:
        athletes_data = get_athletes_data()
        athlete_summary = next((a for a in athletes_data if a['athlete'] == athlete_name), None)
        return render_template('athlete_profile.html',
                             athlete=athlete_summary,
                             athlete_name=athlete_name,
                             error='No activities found for this date range.')

    return render_template('select.html',
                         activities=activities,
                         analysis_query=analysis_query,
                         athlete_name=athlete_name,
                         groq_models=GROQ_MODELS,
                         openai_models=OPENAI_MODELS,
                         gemini_models=GEMINI_MODELS,
                         default_model=DEFAULT_MODEL)

@app.route('/athlete/<athlete_name>/upload_fit', methods=['POST'])
def upload_fit_file(athlete_name):
    """Handle FIT file upload and convert to activity data for analysis"""
    # Check if file was uploaded
    if 'fit_file' not in request.files:
        athletes_data = get_athletes_data()
        athlete_summary = next((a for a in athletes_data if a['athlete'] == athlete_name), None)
        return render_template('athlete_profile.html',
                             athlete=athlete_summary,
                             athlete_name=athlete_name,
                             error='No file uploaded. Please select a FIT file.')

    file = request.files['fit_file']
    activity_name = request.form.get('activity_name', '').strip()

    # Check if a file was selected
    if file.filename == '':
        athletes_data = get_athletes_data()
        athlete_summary = next((a for a in athletes_data if a['athlete'] == athlete_name), None)
        return render_template('athlete_profile.html',
                             athlete=athlete_summary,
                             athlete_name=athlete_name,
                             error='No file selected. Please choose a FIT file to upload.')

    # Check file extension
    if not file.filename.lower().endswith('.fit'):
        athletes_data = get_athletes_data()
        athlete_summary = next((a for a in athletes_data if a['athlete'] == athlete_name), None)
        return render_template('athlete_profile.html',
                             athlete=athlete_summary,
                             athlete_name=athlete_name,
                             error='Invalid file type. Only .fit files are accepted.')

    try:
        # Save uploaded file temporarily
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{athlete_name}_{timestamp}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)

        # Validate FIT file
        is_valid, error_message = validate_fit_file(filepath)
        if not is_valid:
            # Clean up invalid file
            os.remove(filepath)
            athletes_data = get_athletes_data()
            athlete_summary = next((a for a in athletes_data if a['athlete'] == athlete_name), None)
            return render_template('athlete_profile.html',
                                 athlete=athlete_summary,
                                 athlete_name=athlete_name,
                                 error=f'Invalid FIT file: {error_message}')

        # Parse FIT file
        activity = parse_fit_file(filepath)

        # Clean up file after parsing
        os.remove(filepath)

        if not activity:
            athletes_data = get_athletes_data()
            athlete_summary = next((a for a in athletes_data if a['athlete'] == athlete_name), None)
            return render_template('athlete_profile.html',
                                 athlete=athlete_summary,
                                 athlete_name=athlete_name,
                                 error='Failed to parse FIT file. The file may be corrupted or in an unsupported format.')

        # Override activity name if provided
        if activity_name:
            activity['name'] = activity_name

        # Convert to Strava-compatible format for display
        # Add distance_miles and pace_min_per_mile for display compatibility
        if 'distance' in activity and activity['distance'] > 0:
            activity['distance_miles'] = round(activity['distance'] / 1609.34, 2)
            if 'moving_time' in activity and activity['moving_time'] > 0:
                pace_seconds = activity['moving_time'] / activity['distance_miles']
                pace_min = int(pace_seconds // 60)
                pace_sec = int(pace_seconds % 60)
                activity['pace_min_per_mile'] = f"{pace_min}:{pace_sec:02d}"
            else:
                activity['pace_min_per_mile'] = 'N/A'
        else:
            activity['distance_miles'] = 0
            activity['pace_min_per_mile'] = 'N/A'

        # Store in session for analysis
        session['fit_activity'] = activity
        session['selected_athlete'] = athlete_name

        # Get athlete summary data
        athletes_data = get_athletes_data()
        athlete_summary = next((a for a in athletes_data if a['athlete'] == athlete_name), None)

        # Render profile page with FIT activity ready for analysis
        return render_template('athlete_profile.html',
                             athlete=athlete_summary,
                             athlete_name=athlete_name,
                             fit_activity=activity,
                             groq_models=GROQ_MODELS,
                             openai_models=OPENAI_MODELS,
                             gemini_models=GEMINI_MODELS,
                             default_model=DEFAULT_MODEL)

    except Exception as e:
        # Clean up file if error occurred
        if os.path.exists(filepath):
            os.remove(filepath)

        athletes_data = get_athletes_data()
        athlete_summary = next((a for a in athletes_data if a['athlete'] == athlete_name), None)
        return render_template('athlete_profile.html',
                             athlete=athlete_summary,
                             athlete_name=athlete_name,
                             error=f'Error processing FIT file: {str(e)}')

if __name__ == '__main__':
    app.run(debug=True, port=4200, host='localhost')

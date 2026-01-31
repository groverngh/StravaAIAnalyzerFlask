from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from dotenv import load_dotenv
import os
import requests
import openai
from datetime import datetime
from urllib.parse import urlencode
import markdown2
import json
import time
import threading
from google.oauth2 import service_account
from googleapiclient.discovery import build

load_dotenv()

# Global lock for rate limiting to prevent race conditions
rate_limit_lock = threading.Lock()

app = Flask(__name__)
app.secret_key = os.urandom(24)

STRAVA_ACTIVITIES_URL = 'https://www.strava.com/api/v3/athlete/activities'
STRAVA_ACTIVITY_DETAIL_URL = 'https://www.strava.com/api/v3/activities/{}'
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
STRAVA_CLIENT_ID = os.getenv('STRAVA_CLIENT_ID')
STRAVA_CLIENT_SECRET = os.getenv('STRAVA_CLIENT_SECRET')
STRAVA_REDIRECT_URI = os.getenv('STRAVA_REDIRECT_URI', 'http://localhost:4200/callback')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-5.1')
NUM_ANALYSIS_PER_DAY = int(os.getenv('NUM_ANALYSIS', '0'))  # 0 = unlimited
TOKEN_FILE = 'token_store.json'
GOOGLE_SHEETS_CREDENTIALS_FILE = 'njmaniacs-485422-8e16104bb447.json'
GOOGLE_SHEET_ID = '1POa75jrHHYwyfBAC0aObgc01HEFPnjl7ongLAJhqfa0'
GOOGLE_SHEET_NAME = 'Sheet1'
ATHLETE_CREDS_SHEET_NAME = 'Athelete'
AI_ANALYSIS_SHEET_NAME = 'AI Analysis'

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

def check_analysis_limit(ip_address):
    """Check if IP address has exceeded daily analysis limit

    Args:
        ip_address (str): Client IP address

    Returns:
        tuple: (allowed (bool), count (int), limit (int))
    """
    # If limit is -1, block all analyses
    if NUM_ANALYSIS_PER_DAY == -1:
        return False, 0, -1

    # If limit is 0, unlimited analyses allowed
    if NUM_ANALYSIS_PER_DAY == 0:
        return True, 0, 0

    try:
        service = get_sheets_service(readonly=True)

        # Fetch data from AI Analysis sheet
        sheet = service.spreadsheets()
        result = sheet.values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f'{AI_ANALYSIS_SHEET_NAME}!A:D'
        ).execute()

        values = result.get('values', [])
        if not values:
            # No data yet, allow analysis
            return True, 0, NUM_ANALYSIS_PER_DAY

        # Get today's date
        today = datetime.now().strftime('%Y-%m-%d')

        # Count analyses for this IP today
        count = 0
        for row in values[1:]:  # Skip header row (row 0)
            if len(row) >= 3:
                row_ip = row[0] if len(row) > 0 else ''
                row_date = row[2] if len(row) > 2 else ''

                if row_ip == ip_address and row_date == today:
                    count += 1

        # Debug logging
        print(f"[Rate Limit Check] IP: {ip_address}, Date: {today}, Count: {count}, Limit: {NUM_ANALYSIS_PER_DAY}")
        print(f"[Rate Limit Check] Total rows in sheet: {len(values)}, Data rows: {len(values)-1}")

        # Check if limit would be exceeded
        # count represents analyses ALREADY completed
        # If count >= limit, we've used our quota, so block
        allowed = count < NUM_ANALYSIS_PER_DAY

        print(f"[Rate Limit Check] Allowed: {allowed} (count {count} < limit {NUM_ANALYSIS_PER_DAY})")

        return allowed, count, NUM_ANALYSIS_PER_DAY

    except Exception as e:
        print(f"Error checking analysis limit: {e}")
        # On error, block the analysis (fail closed) to prevent abuse
        return False, 0, NUM_ANALYSIS_PER_DAY

def log_analysis_request(ip_address, athlete_name=None, activity_id=None):
    """Log analysis request to Google Sheets

    Args:
        ip_address (str): Client IP address
        athlete_name (str, optional): Athlete name if logged in
        activity_id (str, optional): Activity ID analyzed
    """
    try:
        service = get_sheets_service(readonly=False)

        # Get current timestamp
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        date = datetime.now().strftime('%Y-%m-%d')

        # Prepare row data
        values = [[
            ip_address,
            timestamp,
            date,
            athlete_name or 'Unknown',
            str(activity_id) if activity_id else ''
        ]]

        body = {
            'values': values
        }

        # Append to AI Analysis sheet
        result = service.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range=f'{AI_ANALYSIS_SHEET_NAME}!A:E',
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()

        print(f"[Rate Limit Log] Successfully logged: IP={ip_address}, Date={date}, Athlete={athlete_name}, Activity={activity_id}")
        return True
    except Exception as e:
        print(f"Error logging analysis request: {e}")
        return False

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
    return render_template('select.html', activities=activities, analysis_query=analysis_query)

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
            openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
            system_prompt = """You are a fitness data analyst. When analyzing activities:
- Use US units: miles (not kilometers), minutes per mile for pace (not min/km)
- Convert all distances to miles (1 km = 0.621371 miles)
- Show pace in minutes per mile format (e.g., 8:30 min/mi)
- Display splits in miles unless the activity has custom splits
- Use feet for elevation (not meters)
- Provide clear, actionable insights"""

            prompt = f"Analyze this Strava activity in detail: {activity}"
            if analysis_query:
                prompt += f"\nFocus on: {analysis_query}"
            response = openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ]
            )
            analysis = response.choices[0].message.content.strip()
            analysis_html = markdown2.markdown(analysis)
        except Exception as e:
            error = f'OpenAI API error: {e}'
    return render_template('activity.html', activity=activity, analysis=analysis, analysis_html=analysis_html, error=error)

@app.route('/api/analyze_activity/<int:activity_id>', methods=['POST'])
def api_analyze_activity(activity_id):
    """API endpoint for analyzing a single activity with detailed data"""
    # Get client IP address
    client_ip = get_client_ip()

    # Get analysis mode and training intent from request body (nerd, maniac, or nice)
    request_data = request.get_json() or {}
    analysis_mode = request_data.get('mode', 'nerd')
    training_intent = request_data.get('training_intent', '')

    # Initialize for test message display
    current_count = 0
    limit = 0

    # Check if analysis is blocked entirely (NUM_ANALYSIS=-1)
    if NUM_ANALYSIS_PER_DAY == -1:
        return jsonify({
            'error': 'AI analysis is currently disabled. Please contact the administrator.',
            'limit_reached': True,
            'current_count': 0,
            'limit': -1
        }), 429  # 429 Too Many Requests

    # Check if analysis limit is enforced (NUM_ANALYSIS > 0)
    if NUM_ANALYSIS_PER_DAY > 0:
        # Use a lock to make check+log atomic and prevent race conditions
        with rate_limit_lock:
            allowed, current_count, limit = check_analysis_limit(client_ip)
            if not allowed:
                return jsonify({
                    'error': f'Daily analysis limit reached. You have used {current_count}/{limit} analyses today. Limit resets at midnight.',
                    'limit_reached': True,
                    'current_count': current_count,
                    'limit': limit
                }), 429  # 429 Too Many Requests

            # Log the analysis request immediately within the lock
            # This ensures the count is incremented before the next request can check
            athlete_name = session.get('athlete_name', None)
            log_analysis_request(client_ip, athlete_name, activity_id)
    else:
        # NUM_ANALYSIS=0 means unlimited
        limit = 'unlimited'

    # Check if we're viewing a specific athlete's activities
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

    # Analyze with OpenAI
    try:
        openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)

        # Define system prompts based on analysis mode
        if analysis_mode == 'maniac':
            system_prompt = """You are my over-achieving endurance coach in "maniac mode."

Analyze this Strava activity with brutal honesty. Assume I want to be faster, stronger, and more disciplined than 99% of athletes.

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

IMPORTANT: Use US units - miles (not kilometers), minutes per mile for pace (not min/km), feet for elevation (not meters).

Do not motivate me emotionally. Fix me."""

        elif analysis_mode == 'nice':
            system_prompt = """You are my supportive endurance coach in "nice guy mode."

Analyze this Strava activity with a balanced, encouraging, and constructive tone. Assume I am committed and consistent, and I want to improve sustainably.

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

IMPORTANT: Use US units - miles (not kilometers), minutes per mile for pace (not min/km), feet for elevation (not meters).

Keep it honest, but kind."""

        elif analysis_mode == 'nerd':
            system_prompt = """You are my sports science–oriented data analyst in "data nerd mode."

Analyze this Strava activity purely through data, physiology, and execution quality. Assume I want objective insights, not motivation.

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

IMPORTANT: Use US units - miles (not kilometers), minutes per mile for pace (not min/km), feet for elevation (not meters).

Do not coach emotionally. Let the data speak."""

        else:
            # Fallback for any unexpected mode
            system_prompt = """You are a fitness data analyst. When analyzing activities:
- Use US units: miles (not kilometers), minutes per mile for pace (not min/km)
- Convert all distances to miles (1 km = 0.621371 miles)
- Show pace in minutes per mile format (e.g., 8:30 min/mi)
- Display splits in miles unless the activity has custom splits
- Use feet for elevation (not meters)
- Provide clear, actionable insights"""

        prompt = f"Analyze this Strava activity in detail: {activity}"
        if training_intent:
            prompt += f"\n\nStated training intent: {training_intent}"
            prompt += "\nEvaluate whether the execution matched the stated training intent."
        if analysis_query:
            prompt += f"\nFocus on: {analysis_query}"

        # Call OpenAI API for actual analysis
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
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
        return jsonify({'error': f'OpenAI API error: {str(e)}'}), 500

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
        openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
        system_prompt = """You are a fitness data analyst. When analyzing activities:
- Use US units: miles (not kilometers), minutes per mile for pace (not min/km)
- Convert all distances to miles (1 km = 0.621371 miles)
- Show pace in minutes per mile format (e.g., 8:30 min/mi)
- Display splits in miles unless the activity has custom splits
- Use feet for elevation (not meters)
- Provide clear, actionable insights and trends across all activities"""

        prompt = f"Analyze this list of Strava activities: {activities}"
        if analysis_query:
            prompt += f"\nFocus on: {analysis_query}"
        try:
            response = openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ]
            )
            analysis = response.choices[0].message.content.strip()
            analysis_html = markdown2.markdown(analysis)
        except Exception as e:
            analysis = f'OpenAI API error: {e}'
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
        return render_template('select.html', activities=activities, analysis_query=analysis_query)
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
        return render_template('select.html', activities=activities, analysis_query=analysis_query, summary=summary)
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

    return render_template('select.html', activities=activities, analysis_query=analysis_query, athlete_name=athlete_name)

if __name__ == '__main__':
    app.run(debug=True, port=4200, host='localhost')

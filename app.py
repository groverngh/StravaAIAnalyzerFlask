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

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

STRAVA_ACTIVITIES_URL = 'https://www.strava.com/api/v3/athlete/activities'
STRAVA_ACTIVITY_DETAIL_URL = 'https://www.strava.com/api/v3/activities/{}'
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
STRAVA_CLIENT_ID = os.getenv('STRAVA_CLIENT_ID')
STRAVA_CLIENT_SECRET = os.getenv('STRAVA_CLIENT_SECRET')
STRAVA_REDIRECT_URI = os.getenv('STRAVA_REDIRECT_URI', 'http://localhost:4200/callback')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4')
TOKEN_FILE = 'token_store.json'

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

@app.route('/', methods=['GET', 'POST'])
def index():
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
    return render_template('index.html')

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
        return render_template('index.html', error='Failed to get Strava access token.')

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
        return render_template('index.html', error='No activities found for this date range.')
    if len(activities) == 1:
        return redirect(url_for('activity_detail', activity_id=activities[0]['id']))
    return render_template('select.html', activities=activities, analysis_query=analysis_query)

@app.route('/activity/<int:activity_id>', methods=['GET', 'POST'])
def activity_detail(activity_id):
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

if __name__ == '__main__':
    app.run(debug=True, port=4200, host='localhost')

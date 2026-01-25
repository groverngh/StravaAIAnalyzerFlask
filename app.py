from flask import Flask, render_template, request, redirect, url_for, session
from dotenv import load_dotenv
import os
import requests
import openai
from datetime import datetime
from urllib.parse import urlencode
import markdown2

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

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        date = request.form['date']
        end_date = request.form.get('end_date', '').strip()
        analysis_query = request.form.get('analysis_query', '').strip()
        session['date'] = date
        session['end_date'] = end_date
        session['analysis_query'] = analysis_query
        # Start OAuth flow
        params = {
            'client_id': STRAVA_CLIENT_ID,
            'response_type': 'code',
            'redirect_uri': STRAVA_REDIRECT_URI,
            'approval_prompt': 'force',
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
    if not access_token:
        return render_template('index.html', error='Failed to get Strava access token.')
    session['token'] = access_token
    # Fetch activities for the date range
    start_dt = datetime.strptime(date, '%Y-%m-%d')
    if end_date:
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    else:
        end_dt = start_dt
    after = int(start_dt.replace(hour=0, minute=0, second=0).timestamp())
    before = int(end_dt.replace(hour=23, minute=59, second=59).timestamp())
    headers = {'Authorization': f'Bearer {access_token}'}
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
    token = session.get('token')
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
            prompt = f"Analyze this Strava activity: {activity}"
            if analysis_query:
                prompt += f"\nFocus on: {analysis_query}"
            response = openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You are a fitness data analyst."},
                    {"role": "user", "content": prompt}
                ]
            )
            analysis = response.choices[0].message.content.strip()
            analysis_html = markdown2.markdown(analysis)
        except Exception as e:
            error = f'OpenAI API error: {e}'
    return render_template('activity.html', activity=activity, analysis=analysis, analysis_html=analysis_html, error=error)

@app.route('/analyze_list', methods=['GET', 'POST'])
def analyze_list():
    token = session.get('token')
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
        prompt = f"Analyze this list of Strava activities: {activities}"
        if analysis_query:
            prompt += f"\nFocus on: {analysis_query}"
        try:
            response = openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You are a fitness data analyst."},
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
        token = session.get('token')
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
        token = session.get('token')
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

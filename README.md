# Strava AI Analyzer

A Flask web application that fetches Strava activities and analyzes them using OpenAI, with multi-athlete support via Google Sheets integration.

## Features

- 🏃 Fetch Strava activities for any date range
- 🤖 AI-powered activity analysis using OpenAI (GPT-4)
- 👥 Multi-athlete support with Google Sheets integration
- 📊 Athlete summary dashboard with yearly stats
- 🔄 Automatic token refresh for persistent authentication
- 📈 Individual athlete profiles with activity tracking
- 🇺🇸 US units (miles, min/mi pace, feet for elevation)

## Local Setup

1. **Install dependencies:**
   ```sh
   pip install -r requirements.txt
   ```

2. **Configure environment variables:**
   - Copy `.env.example` to `.env`
   - Add your API keys and credentials:
     ```
     STRAVA_CLIENT_ID=your_client_id
     STRAVA_CLIENT_SECRET=your_client_secret
     STRAVA_REDIRECT_URI=http://localhost:4200/callback
     OPENAI_API_KEY=your_openai_key
     OPENAI_MODEL=gpt-4
     ```

3. **Add Google Sheets credentials:**
   - Place your service account JSON file in the root directory
   - File should be named: `njmaniacs-485422-8e16104bb447.json`

4. **Run the app:**
   ```sh
   python3 app.py
   ```

5. **Open in your browser:**
   - Go to [http://localhost:4200](http://localhost:4200)

## Deployment to Render (Free)

### Prerequisites
- GitHub account
- Render account (sign up at https://render.com)
- Your Strava API app credentials
- OpenAI API key
- Google Sheets service account JSON

### Step 1: Push to GitHub

1. Initialize git repository (if not already done):
   ```sh
   git init
   git add .
   git commit -m "Initial commit"
   ```

2. Create a new repository on GitHub

3. Push your code:
   ```sh
   git remote add origin https://github.com/yourusername/your-repo-name.git
   git branch -M main
   git push -u origin main
   ```

### Step 2: Deploy on Render

1. Go to [Render Dashboard](https://dashboard.render.com/)
2. Click "New +" and select "Web Service"
3. Connect your GitHub repository
4. Configure the service:
   - **Name**: `strava-ai-analyzer` (or your choice)
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - **Plan**: Select "Free"

5. Click "Create Web Service"

### Step 3: Configure Environment Variables

In Render dashboard, go to "Environment" tab and add:

```
STRAVA_CLIENT_ID=your_strava_client_id
STRAVA_CLIENT_SECRET=your_strava_client_secret
STRAVA_REDIRECT_URI=https://your-app-name.onrender.com/callback
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4
```

**Important**: Replace `your-app-name` with your actual Render app name!

### Step 4: Upload Google Sheets Credentials

Since the Google Sheets JSON file contains secrets, don't commit it to GitHub. Instead:

1. In Render dashboard, go to "Environment" tab
2. Scroll to "Secret Files"
3. Click "Add Secret File"
4. Filename: `njmaniacs-485422-8e16104bb447.json`
5. Paste the contents of your Google Sheets service account JSON
6. Click "Save"

### Step 5: Update Strava OAuth Settings

1. Go to [Strava API Settings](https://www.strava.com/settings/api)
2. Update "Authorization Callback Domain" to include:
   - `your-app-name.onrender.com`
3. Save changes

### Step 6: Deploy!

Render will automatically deploy your app. Once deployed:
- Your app will be available at: `https://your-app-name.onrender.com`
- Render free tier may spin down after inactivity (takes ~30 seconds to restart)

## Google Sheets Setup

### Sheet1 (Athlete Summary)
Required columns:
- `Athelete` - Athlete name
- `Total Distance(miles)` - Yearly distance
- `Number of Runs` - Total runs
- `WeeklyVolGen` - Comma-separated weekly volumes

### Athelete Tab (Strava Credentials)
Required columns:
- `ID` - Strava ID (or "StravaSetupNeeded" if not configured)
- `Name` - Athlete name (must match Sheet1)
- `Refresh_token` - Strava refresh token
- `Access_token` - Strava access token
- `Expires_at(EPOC)` - Token expiration timestamp
- `Expires_in` - Seconds until expiration
- `Expires at` - Human-readable expiration date

## Alternative Free Deployment Options

### Railway
1. Sign up at https://railway.app
2. Click "New Project" → "Deploy from GitHub repo"
3. Select your repository
4. Add environment variables in "Variables" tab
5. Railway will auto-detect and deploy your Flask app

### Fly.io
1. Install flyctl: https://fly.io/docs/hands-on/install-flyctl/
2. Run `fly launch` in your project directory
3. Follow prompts to configure
4. Set secrets: `fly secrets set OPENAI_API_KEY=xxx STRAVA_CLIENT_ID=xxx ...`
5. Deploy: `fly deploy`

## Notes

- Tokens are automatically refreshed when expired
- App uses persistent token storage in `token_store.json`
- Analysis results are displayed in US units (miles, min/mi, feet)
- Free tier on Render may have cold starts (~30 seconds)

---

**Enjoy analyzing your Strava activities with AI! 🏃‍♂️🤖**

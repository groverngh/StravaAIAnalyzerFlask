# Strava AI Analyzer Flask App

This Flask web app lets you:
- Enter a date and Strava access token
- Fetch your Strava activities for that date
- Select an activity to analyze (if multiple)
- View activity details and analyze them with OpenAI

## Setup

1. **Install dependencies:**
   ```sh
   pip install -r requirements.txt
   ```

2. **Set your OpenAI API key:**
   - Edit the `.env` file and add your OpenAI API key:
     ```
     OPENAI_API_KEY=sk-...
     ```

3. **Run the app:**
   ```sh
   flask run
   ```
   or
   ```sh
   python app.py
   ```

4. **Open in your browser:**
   - Go to [http://localhost:5000](http://localhost:5000)

## Notes
- Your Strava access token is never stored.
- For production, use HTTPS and secure your secrets.
- You can get a Strava access token from https://www.strava.com/settings/api

---

**Enjoy analyzing your Strava activities with AI!**

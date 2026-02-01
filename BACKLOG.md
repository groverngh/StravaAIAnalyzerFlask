# Feature Backlog

This document tracks future features and enhancements for the Strava AI Analyzer.

## Completed Features

### ✅ FIT File Upload & Analysis
**Completed:** 2026-02-01
**Description:** Upload and analyze activities directly from FIT files (Garmin, Wahoo, Polar, etc.) without connecting to Strava.

**Implementation:**
- Created `fit_parser.py` module using fitparse library
- Parses FIT files and converts to Strava-compatible format
- Extracts all key metrics: distance, pace, elevation, heart rate, cadence, splits
- Added upload UI to athlete profile page
- Validates files before processing (size, format, content)
- Temporary file storage with automatic cleanup
- Full integration with existing AI analysis workflow

**Benefits:**
- Analyze activities from any fitness device
- No Strava connection required for FIT files
- Same AI analysis features as Strava activities
- Privacy-focused option for users who don't use Strava

---

## Planned Features

### 1. Weather API Integration
**Priority:** Medium
**Description:** Connect to an open-source weather API to fetch actual temperature and weather conditions during the run timeframe.

**Details:**
- Remove reliance on Strava watch temperature (affected by body heat)
- Use activity start time and location to fetch historical weather data
- Include temperature, humidity, wind speed, precipitation in analysis
- Potential APIs:
  - Open-Meteo (free, no API key required)
  - OpenWeatherMap (free tier available)
  - WeatherAPI.com (free tier available)

**Benefits:**
- More accurate environmental context for performance analysis
- Better understanding of how weather impacts performance
- Helps explain variations in pace, heart rate, etc.

---

### 2. Custom Activity Intent Input
**Priority:** High
**Description:** Allow users to type in custom training intent/goal for each activity instead of selecting from predefined dropdown options.

**Details:**
- Add free-text input field in the analysis modal
- Keep predefined options as suggestions/quick-select
- Allow users to specify nuanced training goals:
  - "Negative split practice"
  - "Zone 2 endurance with 3x1min pickups"
  - "Testing new racing shoes"
  - "Recovery run after marathon"
- Pass custom intent to LLM for more tailored analysis

**Benefits:**
- More personalized and relevant AI feedback
- Flexibility for varied training plans
- Better alignment between athlete goals and AI analysis

---

### 3. Athlete Profile HR Zones & Training Zones
**Priority:** High
**Description:** Pull athlete profile details including heart rate zones, power zones, and other personalized training metrics.

**Details:**
- Fetch athlete profile from Strava API `/athlete` endpoint
- Extract key data:
  - Heart rate zones (5 zones)
  - FTP (Functional Threshold Power) for cycling
  - Pace zones for running
  - Weight, max heart rate
- Include zones in activity analysis payload to LLM
- Enable zone-based analysis:
  - "You spent 45% of time in Zone 2 (target: 80%)"
  - "Heart rate drift analysis based on your zones"
  - "Power output relative to your FTP"

**Benefits:**
- Highly personalized training insights
- Zone adherence tracking
- Better understanding of training intensity distribution
- Helps identify if workout matched intended training stimulus

---

## Future Ideas (Not Prioritized)

- Multi-activity comparison (e.g., "Compare my last 5 long runs")
- Training load and recovery tracking
- Race prediction based on training history
- Export analysis reports to PDF
- Strava activity comments integration (auto-post analysis summary)
- Weekly/monthly training summary emails

---

**Last Updated:** 2026-02-01

# Telegram Job Portal Bot - Tamil Nadu Jobs

An automated Google Apps Script bot that fetches real-time Tamil Nadu job listings from major job portals using Google Gemini AI + Google Search Grounding and broadcasts them to Telegram every 10 minutes.

- **Telegram Channel**: [@JOB_PORTAL_TAMILNADU](https://t.me/JOB_PORTAL_TAMILNADU)
- **Schedule**: Every 10 Minutes (Automated Time-Driven Trigger)

---

## Key Features

1. **10-Minute Automated Trigger**: Runs `runEvery10Mins()` every 10 minutes automatically.
2. **Resilient Multi-Key & Model Fallback**: Prevents downtime by cycling through 11 validated Gemini models (`gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-2.0-flash`, etc.) and backup API keys (`GEMINI_API_KEY_2`, `GEMINI_API_KEYS`) when encountering rate limits (429) or service issues (503).
3. **Exponential Backoff**: Sleeps 2–4 seconds and retries when encountering rate limits before failing over.
4. **Strict Multi-Key Deduplication**: Prevents previously posted job listings from appearing again by storing SHA-1 hashes of both normalized URLs and Title+Company combinations across runs.
5. **Categorized HTML Formatting**: Cleanly groups job postings into IT & Software, Engineering, Healthcare, Sales, Finance, Govt & PSU, and Others with direct application links.

---

## Setup Instructions

1. Go to [Google Apps Script](https://script.google.com) and create a **New Project**.
2. Copy all code from [`Code.js`](./Code.js) and paste it into `Code.js`.
3. In **Project Settings** (⚙️) → **Script Properties**, add:
   - `GEMINI_API_KEY`: Your Google AI Studio API key
   - `TELEGRAM_BOT_TOKEN`: Your Telegram Bot API token from `@BotFather`
   - `TELEGRAM_CHAT_ID`: Your channel handle (e.g. `@JOB_PORTAL_TAMILNADU`)
   - *(Optional)* `GEMINI_API_KEY_2`: Secondary fallback API key
4. Run `setupTrigger()` once from the editor to schedule the 10-minute trigger.
5. Run `runEvery10Mins()` manually to test immediately!

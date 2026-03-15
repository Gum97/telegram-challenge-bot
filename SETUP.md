# AI Meeting Challenge Bot — Setup Guide

## 1. Create a Telegram Bot

1. Open [@BotFather](https://t.me/BotFather) → `/newbot`
2. Copy the `BOT_TOKEN`
3. Add the bot to your group and **make it an admin** (so it can post messages)
4. Get the group chat ID: forward a group message to [@userinfobot](https://t.me/userinfobot) or use the Telegram API

## 2. Google Sheets Setup

### Create the spreadsheet
Create a Google Sheet with **4 tabs** named exactly:

| Tab | Headers (row 1) |
|-----|----------------|
| `Teams` | `team_id`, `team_name`, `telegram_user_id`, `username`, `registered_at` |
| `Checkins` | `id`, `team_id`, `week`, `submitted_at`, `rank`, `points`, `screenshot_url`, `validated` |
| `Shares` | `id`, `team_id`, `week`, `submitted_at`, `content`, `score`, `scored_at`, `feedback` |
| `Leaderboard` | `team_id`, `team_name`, `checkin_points`, `sharing_points`, `total_points`, `last_updated` |

### Create a Service Account
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable **Google Sheets API** and **Google Drive API**
3. IAM & Admin → Service Accounts → Create service account
4. Create a JSON key → download as `credentials.json`
5. Share your Google Sheet with the service account email (Editor access)
6. Copy the spreadsheet ID from the URL: `https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/`

## 3. Install & Configure

```bash
cd /Users/gum97/.openclaw/workspace/telegram-challenge-bot

# Create virtualenv
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your actual values
nano .env

# Place your Google credentials file
cp ~/Downloads/your-service-account.json credentials.json
```

## 4. Run the Bot

```bash
source .venv/bin/activate
python bot.py
```

For production (keep running):
```bash
# Using nohup
nohup python bot.py > bot.log 2>&1 &

# Or with systemd / launchd on macOS
```

## 5. Bot Usage

| Command | Where | What |
|---------|-------|------|
| `/start TeamName` | DM or group | Register team |
| `/checkin <post content>` | DM only | Submit weekly check-in |
| `/share <post content>` | DM only | Submit AI sharing post |
| `/leaderboard` | Anywhere | View current rankings |

### Check-in format
```
/checkin [I took a screenshot and attached it] #post #team_1 #week_3
```
Required: mention of screenshot + `#post` + `#team_N` + `#week_N`

### Share format
```
/share This week I used Claude to auto-generate meeting summaries from Zoom transcripts.
Here's my workflow: 1) Export transcript... #week_3
```

## 6. Scoring

- **Check-in**: 10 pts/week, first-come-first-serve. AI validates hashtags + screenshot mention.
- **Sharing**: 0-100 pts per post, only best score counts. Scored on:
  - Novelty (0-33)
  - Practicality (0-33)
  - Workflow Clarity (0-34)

## 7. Weekly Leaderboard

Auto-posts to group every **Monday at 09:00 ICT**.
Manually trigger: `/leaderboard` in any chat.

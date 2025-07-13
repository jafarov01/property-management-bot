# Eivissa Operations Bot

An intelligent, multi-platform bot designed to digitize and automate the daily operations of a property management business in Budapest. This system acts as a centralized command center, processing check-in and cleaning lists from Slack, preventing overbookings, and providing real-time operational control via Telegram.

---

## Table of Contents

- [Core Features](#core-features)
- [System Architecture](#system-architecture)
- [Technology Stack](#technology-stack)
- [Setup & Installation (Local Development)](#setup--installation-local-development)
- [Deployment (Render)](#deployment-render)
- [Usage](#usage)
  - [Slack Workflow](#slack-workflow)
  - [Telegram Commands](#telegram-commands)
- [Configuration](#configuration)
- [Project Structure](#project-structure)

---

## Core Features

- **AI-Powered Parsing:** Utilizes Google's Gemini AI to parse unstructured, natural language messages from Slack, handling messy inputs, typos, and varied formats with high reliability.
- **Centralized Database:** Employs a PostgreSQL database as the single source of truth for all property and booking statuses, eliminating ambiguity and data fragmentation.
- **Robust Property Lifecycle:** Manages properties through a precise three-state lifecycle: `AVAILABLE` → `OCCUPIED` → `PENDING_CLEANING`, with an automated midnight task to reset cleaned properties.
- **Critical Overbooking Prevention:** The system's core feature. It intelligently blocks check-ins for properties that are not in an `AVAILABLE` state.
- **Intelligent Error Alerts:** When a check-in fails, the bot sends a context-aware alert to a dedicated Telegram topic, explaining the *exact* reason (e.g., occupied by another guest, under maintenance, awaiting cleaning).
- **Comprehensive Telegram Command Center:** Provides a rich set of commands for the management team to query statuses, manage operations, correct data, and gain business insights directly from their mobile devices.
- **Full Maintenance & Issue Logging:** Allows the team to log property issues, block rooms for maintenance, and track history, preventing bookings for out-of-service units.

---

## System Architecture

The bot operates on a robust, event-driven "Slack → Database → Telegram" workflow:

1. **Input (Slack):** A designated user posts check-in or cleaning lists into specific Slack channels.
2. **Processing (Python / FastAPI):**
   - A FastAPI server receives the event from Slack via webhook.
   - Message text is sent to the **Gemini AI API** to parse into structured JSON.
   - Application logic validates and updates the PostgreSQL database.
3. **Database (PostgreSQL):** Stores the state of all properties, bookings, and issues.
4. **Output (Telegram):**
   - Telegram bot notifies the management group with detailed updates.
   - Staff uses `/` commands to query and control the operation from Telegram.

---

## Technology Stack

- **Backend:** Python 3, FastAPI
- **Database:** PostgreSQL
- **ORM:** SQLAlchemy
- **AI Integration:** Google Gemini API (`gemini-1.5-flash`)
- **Bot Frameworks:**
  - `python-telegram-bot`
  - `slack-bolt`
- **Scheduler:** `apscheduler` (for daily reset tasks)
- **Deployment:** Render (Web Service + PostgreSQL)
- **Dev Tools:** `uvicorn`, `ngrok`

---

## Setup & Installation (Local Development)

### 1. Prerequisites

- Python 3.10+
- PostgreSQL (running locally)
- Git + code editor (e.g. VS Code)

### 2. Clone the Repository

```bash
git clone <your-repository-url>
cd eivissa-operations-bot
```

### 3. Set Up Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 4. Install Dependencies

```bash
pip install -r src/requirements.txt
```

### 5. Configure Environment

Create a `.env` file in the root directory (`eivissa-operations-bot/`) with all necessary values. See [Configuration](#configuration).

### 6. Run the App Locally

```bash
uvicorn src.main:app --reload
```

Visit: [http://localhost:8000](http://localhost:8000)

### 7. Setup ngrok for Webhooks

```bash
ngrok http 8000
```

Update `WEBHOOK_URL` in your `.env` and Slack app's event subscription.

---

## Deployment (Render)

### 1. Ensure Required Files

In `src/`:

- `requirements.txt`
- `Procfile`

### 2. Render Setup

#### PostgreSQL Database:

- Create PostgreSQL in **Frankfurt (EU Central)**.
- Copy the **external URL** for `DATABASE_URL`.

#### Web Service:

- Connect GitHub repo to a new service.
- **Region:** Frankfurt
- **Root Directory:** `src`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`

### 3. Environment Variables

Add all values from your local `.env` to the Render dashboard.

### 4. Finalize Slack

Set your Slack App's Request URL to:

```
https://<your-app-name>.onrender.com/slack/events
```

---

## Usage

### Slack Workflow

- **Check-ins:** Post like:
  ```
  A1 - John Doe - Arb - paid
  ```
- **Cleaning Lists:**
  ```
  Cleaning List for today:
  A1
  K4
  ```

### Telegram Commands

| Command | Description | Example |
|--------|-------------|---------|
| `/status` | Full summary of all properties | `/status` |
| `/check` | Status of one property | `/check A1` |
| `/available` | List all available properties | `/available` |
| `/occupied` | List all occupied properties | `/occupied` |
| `/pending_cleaning` | Properties awaiting cleaning | `/pending_cleaning` |
| `/early_checkout` | Mark occupied as pending cleaning | `/early_checkout C5` |
| `/set_clean` | Mark cleaned and available | `/set_clean D2` |
| `/cancel_booking` | Cancel active booking | `/cancel_booking A1` |
| `/edit_booking` | Edit active booking info | `/edit_booking K4 guest_name Maria` |
| `/relocate` | Move a guest | `/relocate B3 A9` |
| `/log_issue` | Report issue | `/log_issue C5 Shower broken` |
| `/block_property` | Block for maintenance | `/block_property G2 Painting` |
| `/unblock_property` | Unblock property | `/unblock_property G2` |
| `/booking_history` | Last 5 bookings | `/booking_history A1` |
| `/find_guest` | Locate guest by name | `/find_guest Smith` |
| `/daily_revenue` | Estimated revenue | `/daily_revenue 2025-07-13` |
| `/help` | Show command list | `/help` |

---

## Configuration

All via environment variables (`.env` file):

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot API token |
| `TELEGRAM_TARGET_CHAT_ID` | Telegram group ID (starts with `-`) |
| `SLACK_BOT_TOKEN` | `xoxb-` token from Slack |
| `SLACK_SIGNING_SECRET` | Slack app secret |
| `DATABASE_URL` | PostgreSQL connection string |
| `GEMINI_API_KEY` | Google Gemini API key |
| `WEBHOOK_URL` | Public base URL (ngrok or Render) |
| `SLACK_CHECKIN_CHANNEL_ID` | Slack channel ID for check-ins |
| `SLACK_CLEANING_CHANNEL_ID` | Slack channel ID for cleaning |
| `SLACK_USER_ID_OF_LIST_POSTER` | Slack user ID to trigger parsing |

---

## Project Structure

```
eivissa-operations-bot/
├── .env                # Environment config (not committed)
├── .gitignore
├── venv/               # Virtual environment
└── src/
    ├── config.py
    ├── database.py
    ├── main.py
    ├── models.py
    ├── slack_parser.py
    ├── telegram_client.py
    ├── Procfile
    └── requirements.txt
```

---

> 🛠 Built for real-world operational control by the Eivissa Budapest team.

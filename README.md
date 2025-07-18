# Eivissa Operations Bot

An intelligent, multi-platform bot designed to digitize and automate the daily operations of a property management business. This system acts as a centralized command center, processing check-in lists from Slack, parsing critical emails from Gmail, managing overbooking conflicts, and providing real-time operational control via Telegram.

-----

## Key Functionalities

  * **Multi-Platform Input**: Ingests operational data from both **Slack** channels and a dedicated **Gmail** inbox.
  * **AI-Powered Parsing**: Uses Google's Gemini AI to parse unstructured messages and emails into structured, actionable data.
  * **Advanced Relocation UI**: Provides an interactive Telegram alert for overbooking conflicts with `Swap`, `Cancel`, and `Show Available` options.
  * **Automated Reminders**: Features a two-stage reminder system for unhandled email alerts and a daily reminder for unresolved guest relocations.
  * **Centralized Control**: Offers a rich set of Telegram commands for status checks, manual state changes, and operational control.

-----

## Table of Contents

  - [System Architecture](https://www.google.com/search?q=%23system-architecture)
  - [Technology Stack](https://www.google.com/search?q=%23technology-stack)
  - [Usage Guide](https://www.google.com/search?q=%23usage-guide)
      - [Slack Workflow](https://www.google.com/search?q=%23slack-workflow)
      - [Telegram Commands](https://www.google.com/search?q=%23telegram-commands)
  - [Configuration](https://www.google.com/search?q=%23configuration)
  - [Project Structure](https://www.google.com/search?q=%23project-structure)
  - [Deployment on Render](https://www.google.com/search?q=%23deployment-on-render)

-----

## System Architecture

The bot operates on an event-driven workflow, integrating Slack, Gmail, and Telegram.

1.  **Input (Slack & Gmail)**:
      * A designated user posts check-in or cleaning lists into specific Slack channels.
      * The system monitors a Gmail inbox for new, unread emails from any sender.
2.  **Processing (Python / FastAPI)**:
      * A FastAPI server receives events via webhooks.
      * Message/email content is sent to the **Gemini AI API** for parsing.
      * Application logic validates data and updates the PostgreSQL database.
3.  **Database (PostgreSQL)**: The single source of truth for all property, booking, and alert statuses.
4.  **Output (Telegram)**:
      * The bot sends detailed updates, summaries, and critical alerts to specific topics within a Telegram group.
      * Staff uses slash commands (`/`) to query and control operations.

-----

## Technology Stack

  - **Backend**: Python 3, FastAPI
  - **Database**: PostgreSQL
  - **ORM**: SQLAlchemy
  - **AI Integration**: Google Gemini API (`gemini-1.5-flash`)
  - **Platform SDKs**:
      - `python-telegram-bot[ext]`
      - `slack-bolt`
  - **Scheduling**: `apscheduler`
  - **Deployment**: Render (Web Service + PostgreSQL)
  - **Core Libraries**: `uvicorn`, `python-dotenv`, `psycopg2-binary`, `aiohttp`

-----

## Usage Guide

### Slack Workflow

  - **Post Check-ins** in the designated check-in channel (e.g., `#check-ins-for-today`):
    ```
    A1 - John Doe - Arb - paid
    K4 - Maria Garcia - Bdc - 50 eur
    ```
  - **Post Cleaning Lists** in the designated cleaning channel (e.g., `#cleaning`):
    ```
    Cleaning List for today:
    A1
    K4
    C3
    ```

### Telegram Commands

All commands are sent to the main Telegram group.

| Command                  | Description                                                  | Example                                                  |
| ------------------------ | ------------------------------------------------------------ | -------------------------------------------------------- |
| `/status`                | Get a full summary of all property statuses.                 | `/status`                                                |
| `/check`                 | Get a detailed report for a single property.                 | `/check A1`                                              |
| `/available`             | List all properties that are clean and available.            | `/available`                                             |
| `/occupied`              | List all properties that are currently occupied.             | `/occupied`                                              |
| `/pending_cleaning`      | List all properties waiting to be cleaned.                   | `/pending_cleaning`                                      |
| `/early_checkout`        | Manually mark an occupied property as ready for cleaning.    | `/early_checkout C5`                                     |
| `/set_clean`             | Manually mark a property as clean and available.             | `/set_clean D2`                                          |
| `/cancel_booking`        | Cancel an active booking and make the property available.    | `/cancel_booking A1`                                     |
| `/relocate`              | Move a guest pending relocation to a new room.               | `/relocate A1 A2 2025-07-20`                             |
| `/block_property`        | Block a property for maintenance with a reason.              | `/block_property G2 Repainting walls`                    |
| `/unblock_property`      | Unblock a property and make it available.                    | `/unblock_property G2`                                   |
| `/booking_history`       | Show the last 5 bookings for a property.                     | `/booking_history A1`                                    |
| `/find_guest`            | Find which property a guest is staying in.                   | `/find_guest Smith`                                      |
| `/relocations`           | Show a history of recent guest relocations.                  | `/relocations`                                           |
| `/rename_property`       | Correct a property's code in the database.                   | `/rename_property C7 C8`                                 |
| `/edit_booking`          | Edit details of an active booking.                           | `/edit_booking K4 guest_name Maria`                      |
| `/log_issue`             | Log a new maintenance issue for a property.                  | `/log_issue C5 Shower drain is clogged`                  |
| `/daily_revenue`         | Calculate estimated revenue for a given date.                | `/daily_revenue 2025-07-13`                              |
| `/help`                  | Show this full command manual.                               | `/help`                                                  |

-----

## Configuration

All configuration is handled via environment variables, typically stored in a `.env` file for local development.

| Variable                      | Description                                                  |
| ----------------------------- | ------------------------------------------------------------ |
| `TELEGRAM_BOT_TOKEN`          | Your Telegram bot's API token.                               |
| `TELEGRAM_TARGET_CHAT_ID`     | The ID of your main Telegram group (starts with `-`).        |
| `SLACK_BOT_TOKEN`             | Your Slack bot's `xoxb-` token.                              |
| `SLACK_SIGNING_SECRET`        | Your Slack app's signing secret.                             |
| `DATABASE_URL`                | The connection string for your PostgreSQL database.          |
| `GEMINI_API_KEY`              | Your API key for the Google Gemini service.                  |
| `WEBHOOK_URL`                 | The public base URL of your deployed application (e.g., from Render). |
| `SLACK_CHECKIN_CHANNEL_ID`    | The Slack channel ID where check-in lists are posted.        |
| `SLACK_CLEANING_CHANNEL_ID`   | The Slack channel ID where cleaning lists are posted.        |
| `SLACK_USER_ID_OF_LIST_POSTER`| The Slack user ID authorized to post lists that trigger the bot. |
| `IMAP_SERVER`                 | The IMAP server for the email account (e.g., `imap.gmail.com`). |
| `IMAP_USERNAME`               | The username for the email account.                          |
| `IMAP_PASSWORD`               | The app-specific password for the email account.             |

**Note on `TELEGRAM_TOPIC_IDS`**: These are configured inside `app/config.py` and must match the topic IDs from your Telegram group for `GENERAL`, `ISSUES`, and `EMAILS`.

-----

## Project Structure

The project uses a modular structure for better organization and maintainability.

```
eivissa-operations-bot/
├── .env                # Local environment configuration
├── app/                # Main application package
│   ├── __init__.py
│   ├── config.py       # Loads and validates environment variables
│   ├── database.py     # Database engine and session setup
│   ├── email_parser.py # Logic for fetching and parsing emails
│   ├── main.py         # FastAPI app, webhook routing, and startup logic
│   ├── models.py       # SQLAlchemy database models
│   ├── scheduled_tasks.py # All APScheduler task definitions
│   ├── slack_handler.py   # Core logic for processing Slack messages
│   ├── slack_parser.py    # AI parsing logic for Slack content
│   ├── telegram_client.py # Functions for formatting Telegram messages
│   ├── telegram_handlers.py # All Telegram command and button handlers
│   └── utils/          # Reusable helper modules
│       ├── __init__.py
│       ├── db_manager.py  # Database session decorator
│       └── validators.py  # Command argument validation helpers
├── run.py              # Script to run the Uvicorn server
└── requirements.txt    # Python dependencies
```

-----

## Deployment on Render

### 1\. Initial Setup

  * **PostgreSQL Database**: Create a new PostgreSQL instance on Render. Choose a region close to your users (e.g., Frankfurt). Copy the **Internal Connection String** and set it as your `DATABASE_URL`.
  * **Web Service**: Create a new Web Service and connect it to your Git repository.
      * **Region**: Match your database region.
      * **Build Command**: `pip install -r requirements.txt`
      * **Start Command**: `python run.py`
  * **Environment Variables**: Add all variables from the [Configuration](https://www.google.com/search?q=%23configuration) section to the Environment tab of your Render Web Service.

### 2\. Database Migrations (Free Tier)

Render's free tier does not allow direct database access to run `ALTER TABLE` commands for schema changes. Use the **Temporary Migration Endpoint** method:

1.  Add the temporary endpoint code to `app/main.py` as instructed during development.
2.  Deploy this code. Once the service is live, access the secret URL (`https://<your-app-name>.onrender.com/_secret_...`) to apply the migration.
3.  **Immediately remove the endpoint code** from `app/main.py` and deploy again to secure your application.

### 3\. Finalizing Webhooks

  * **Telegram**: The application automatically sets the Telegram webhook on startup using your `WEBHOOK_URL`.
  * **Slack**: In your Slack App's configuration, navigate to "Event Subscriptions" and set the Request URL to:
    `https://<your-app-name>.onrender.com/slack/events`
# Local Development Setup

This guide will help you set up the Eivissa Operations Bot for local development and testing.

## Prerequisites

- Docker and Docker Compose
- Python 3.8+
- Git

## Quick Start

### 1. Verify Setup

```bash
# Verify all components are ready
python verify_setup.py
```

### 2. Start the Local Environment

```bash
# Option 1: Use the startup script
chmod +x start_local.sh
./start_local.sh

# Option 2: Manual startup
docker-compose up -d postgres
python setup_local_db.py
python run.py
```

This script will:
- Start PostgreSQL in a Docker container
- Create the database tables
- Seed test data
- Run database tests

### 2. Configure Environment Variables

Edit the `.env` file created from `.env.local`:

```bash
# Required for basic functionality
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
GEMINI_API_KEY=your_gemini_api_key_here

# Optional - for full functionality
SLACK_BOT_TOKEN=xoxb-your-slack-bot-token
SLACK_SIGNING_SECRET=your_slack_signing_secret
IMAP_USERNAME=your_email@gmail.com
IMAP_PASSWORD=your_app_specific_password
```

### 3. Start the Application

```bash
python run.py
```

## Manual Setup (Alternative)

If you prefer to set up manually:

### 1. Start PostgreSQL

```bash
docker-compose up -d postgres
```

### 2. Setup Database

```bash
python setup_local_db.py
```

### 3. Run Tests

```bash
# Test database operations
python test_database.py

# Test system integration
python test_system.py
```

## Testing the System

### Database Tests

The system includes comprehensive tests:

- **Database Operations**: CRUD operations, relationships, constraints
- **System Integration**: Property workflows, overbooking scenarios, maintenance
- **Data Integrity**: Enum constraints, unique constraints, transactions

### API Testing

Once the application is running, you can test:

1. **Health Check**: `curl http://localhost:8000/`
2. **Database Debug**: `curl http://localhost:8000/debug/describe_tables`

### Telegram Bot Testing

If you have a Telegram bot token configured:

1. Start the application: `python run.py`
2. Send `/help` to your bot to see available commands
3. Test basic commands like `/status`, `/available`

## Database Management

### View Database

```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U eivissa_user -d eivissa_operations

# List tables
\dt

# View properties
SELECT * FROM properties;

# View bookings
SELECT * FROM bookings;
```

### Reset Database

```bash
# Stop and remove containers
docker-compose down -v

# Start fresh
./start_local.sh
```

## Troubleshooting

### PostgreSQL Connection Issues

```bash
# Check if container is running
docker-compose ps

# Check logs
docker-compose logs postgres

# Restart PostgreSQL
docker-compose restart postgres
```

### Python Dependencies

```bash
# Install dependencies
pip install -r requirements.txt

# If using virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Database Schema Issues

```bash
# Recreate tables
python setup_local_db.py

# Or manually
python -c "
import asyncio
from app.database import async_engine
from app.models import Base

async def recreate():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

asyncio.run(recreate())
"
```

## Development Workflow

1. **Make Changes**: Edit code in the `app/` directory
2. **Test Changes**: Run `python test_system.py`
3. **Start Application**: Run `python run.py`
4. **Test Integration**: Use Telegram commands or API endpoints

## Production Deployment

For production deployment, see the main README.md file for Render deployment instructions.

## File Structure

```
├── docker-compose.yml      # PostgreSQL container setup
├── init.sql               # Database initialization
├── setup_local_db.py      # Database setup script
├── test_database.py       # Database tests
├── test_system.py         # System integration tests
├── start_local.sh         # Quick start script
├── .env.local             # Environment template
└── LOCAL_SETUP.md         # This file
```
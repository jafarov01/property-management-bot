#!/bin/bash

# Eivissa Operations Bot - Local Development Startup Script

echo "🚀 Starting Eivissa Operations Bot Local Development Environment"
echo "================================================================"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found. Creating from template..."
    cp .env.local .env
    echo "📝 Please edit .env file with your API keys and credentials"
    echo "   Required: TELEGRAM_BOT_TOKEN, GEMINI_API_KEY"
    echo "   Optional: SLACK_BOT_TOKEN, IMAP credentials"
    read -p "Press Enter after updating .env file..."
fi

# Start PostgreSQL container
echo "🐘 Starting PostgreSQL container..."
docker-compose up -d postgres

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL to be ready..."
timeout=30
while ! docker-compose exec postgres pg_isready -U eivissa_user -d eivissa_operations > /dev/null 2>&1; do
    sleep 1
    timeout=$((timeout - 1))
    if [ $timeout -eq 0 ]; then
        echo "❌ PostgreSQL failed to start within 30 seconds"
        exit 1
    fi
done

echo "✅ PostgreSQL is ready!"

# Setup database
echo "🗄️  Setting up database..."
python setup_local_db.py

# Run database tests
echo "🧪 Running database tests..."
python test_database.py

echo ""
echo "✅ Local environment is ready!"
echo ""
echo "📝 Next steps:"
echo "1. Make sure your .env file has valid API keys"
echo "2. Run: python run.py"
echo "3. Test with Telegram commands"
echo ""
echo "🛑 To stop: docker-compose down"
# FILE: run.py
import uvicorn
import logging
import os

from app.main import app

if __name__ == "__main__":
    logging.info("Starting Eivissa Operations Bot server...")
    # Render provides the PORT environment variable.
    port = int(os.environ.get("PORT", 8000))
    
    # Run the application using the imported 'app' object.
    # The 'reload' flag is often disabled in production for performance.
    # Render's auto-deploy handles reloading on code changes.
    uvicorn.run(app, host="0.0.0.0", port=port)
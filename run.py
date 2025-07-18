# FILE: run.py
import uvicorn
import logging
import os

if __name__ == "__main__":
    logging.info("Starting Eivissa Operations Bot server...")
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
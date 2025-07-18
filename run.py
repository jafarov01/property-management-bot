# FILE: run.py
import uvicorn
import logging

if __name__ == "__main__":
    logging.info("Starting Eivissa Operations Bot server...")
    # Points to the 'app' instance in the 'app.main' module
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
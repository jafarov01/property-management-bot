#!/usr/bin/env python3
"""
Eivissa Operations Bot - Application Runner

This script starts the FastAPI application with Uvicorn server.
"""

import os
import uvicorn

if __name__ == "__main__":
    # Set environment variable to enable scheduler in the main process
    os.environ["RUN_SCHEDULER"] = "true"
    
    # Start the FastAPI application
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # Enable auto-reload for development
        log_level="info"
    )
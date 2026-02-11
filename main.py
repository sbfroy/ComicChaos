#!/usr/bin/env python3
"""
Comic Chaos - Interactive Comic Strip Generator

Run this file to start the web server.
"""

import os
from pathlib import Path

from app import app
from src.config import LOGS_DIR


def main():
    """Entry point - starts the web server."""
    Path(LOGS_DIR).mkdir(parents=True, exist_ok=True)

    print("Starting Comic Chaos...")
    print("Open http://localhost:5000 in your browser")
    debug = os.getenv("DEBUG", "false").lower() == "true"
    app.run(debug=debug, port=5000)


if __name__ == "__main__":
    main()

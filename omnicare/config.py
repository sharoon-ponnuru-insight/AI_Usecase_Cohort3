"""Shared configuration for OmniCare.

Loads environment variables (via python-dotenv) and exposes constants used
across db.py, tools.py, callbacks.py, agents.py, and app.py.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load a local .env file if present (copy .env.example -> .env and fill in).
load_dotenv(Path(__file__).parent / ".env")

# NOTE: "gemini-3.5-flash" is not a currently published Gemini model name.
# Kept as a placeholder per project requirements; if API calls fail with a
# model-not-found error, swap this single constant to e.g. "gemini-flash-latest".
MODEL_NAME = "gemini-3.5-flash"

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "omnicare.db"

GOOGLE_GENAI_USE_VERTEXAI = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "0")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

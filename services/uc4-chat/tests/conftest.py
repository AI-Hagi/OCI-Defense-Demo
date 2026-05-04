"""Pytest config — make `app` importable and shut up structlog noise in tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Add service root to sys.path so `from app...` works without installing.
SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

# Force mock-LLM mode by default so OCI SDK is never required for tests.
os.environ.setdefault("CHAT_LLM_MODE", "mock")

"""
Configuration constants for MAUDE cloud package.
"""

import os
from pathlib import Path

# Default model (used by TUI)
DEFAULT_MODEL = os.environ.get("MAUDE_MODEL", "mistral")

# Data directory for collab, memory, conversations
DATA_DIR = Path(os.environ.get("MAUDE_DATA_DIR", Path.home() / ".config" / "maude" / "data"))

# Session ID for conversation sync
SESSION_ID = os.environ.get("MAUDE_SESSION_ID", "default")

# Max tool loop iterations per turn
MAX_ITERATIONS = int(os.environ.get("MAUDE_MAX_ITERATIONS", "40"))

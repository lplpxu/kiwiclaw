"""Shared constants for Agent Framework core"""
import os
from pathlib import Path

WORKDIR = Path.cwd()

TOKEN_THRESHOLD = int(os.getenv("TOKEN_THRESHOLD", "100000"))
POLL_INTERVAL = 5
IDLE_TIMEOUT = 60
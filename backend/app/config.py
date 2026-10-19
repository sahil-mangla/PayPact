"""Environment configuration — loaded before any module instantiates PayPalClient."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Resolve .env relative to this file (backend/.env)
_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=_env_path, override=True)

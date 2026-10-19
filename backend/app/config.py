"""Environment configuration — loaded before any module instantiates PayPalClient."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Resolve .env relative to this file (backend/.env) if it exists
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path, override=False)


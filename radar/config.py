"""Static paths and IST time helpers for Hackathon Radar."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
IST = ZoneInfo("Asia/Kolkata")


def ist_now() -> datetime:
    """Current time, timezone-aware in IST."""
    return datetime.now(IST)


def fmt_ist(dt: datetime) -> str:
    """Render a datetime in IST as 'YYYY-MM-DD HH:MM IST'."""
    return dt.astimezone(IST).strftime("%Y-%m-%d %H:%M IST")

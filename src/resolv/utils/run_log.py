"""Shared run log — echoes pipeline events to stdout and appends them to per-minute UTC files in logs/."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

_LOG_DIRECTORY = Path("logs")


def log_event(message: str) -> None:
    """Echo a UTC time-stamped message to stdout and append it to a per-minute UTC log file.

    Each line is prefixed with the UTC time of day (HH:MM:SSZ); the date lives
    in the file name. Windows forbids ':' in file names, so the file name's
    time separator is '-' (DD-MM-YYYYTHH-MMZ). Messages logged within the same
    minute are appended to the same file, separated by a delimiter line.
    """
    now_utc = datetime.now(timezone.utc)
    timestamped_message = f"{now_utc.strftime('%H:%M:%S')}Z {message}"
    print(timestamped_message, flush=True)
    _LOG_DIRECTORY.mkdir(exist_ok=True)
    log_file_name = now_utc.strftime("%d-%m-%YT%H-%MZ") + ".log"
    with (_LOG_DIRECTORY / log_file_name).open("a", encoding="utf-8") as log_file:
        log_file.write(timestamped_message + "\n\n" + "=" * 80 + "\n\n")

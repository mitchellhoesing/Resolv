"""Shared run log — appends pipeline events to per-minute UTC files in logs/."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

_LOG_DIRECTORY = Path("logs")


def log_event(message: str) -> None:
    """Append a message to a per-minute UTC log file.

    Windows forbids ':' in file names, so the time separator is '-'
    (DD-MM-YYYYTHH-MMZ). Messages logged within the same minute are
    appended to the same file, separated by a delimiter line.
    """
    _LOG_DIRECTORY.mkdir(exist_ok=True)
    log_file_name = datetime.now(timezone.utc).strftime("%d-%m-%YT%H-%MZ") + ".log"
    with (_LOG_DIRECTORY / log_file_name).open("a", encoding="utf-8") as log_file:
        log_file.write(message + "\n\n" + "=" * 80 + "\n\n")

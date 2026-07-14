"""Unit tests for the shared run log helper."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from resolv.utils.run_log import log_event


def test_log_event_appends_to_timestamped_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    log_event("first event")
    log_event("second event")

    log_files = list((tmp_path / "logs").glob("*.log"))
    assert len(log_files) == 1
    # DD-MM-YYYYTHH-MMZ, e.g. 08-07-2026T14-32Z
    assert re.fullmatch(r"\d{2}-\d{2}-\d{4}T\d{2}-\d{2}Z\.log", log_files[0].name)
    contents = log_files[0].read_text(encoding="utf-8")
    # Each line is prefixed with the UTC time of day, e.g. 14:32:07Z
    assert re.search(r"\d{2}:\d{2}:\d{2}Z first event", contents)
    assert re.search(r"\d{2}:\d{2}:\d{2}Z second event", contents)
    assert "=" * 80 in contents

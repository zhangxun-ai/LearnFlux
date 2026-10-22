"""Beijing display rules and legacy UTC timestamp regression tests."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import subprocess

import pytest

from video_transcript_api.utils.timeutil import (
    datetime_for_api,
    format_datetime_for_display,
    format_datetime_with_timezone,
    get_configured_timezone,
    parse_timezone_offset,
)


@pytest.mark.parametrize("value", [
    "2026-10-22 00:30:00",
    "2026-10-22T00:30:00",
    "2026-10-22T00:30:00Z",
    "2026-10-22T00:30:00+00:00",
    "2026-10-22T08:30:00+08:00",
    "2026-10-21T19:30:00-05:00",
    datetime(2026, 10, 22, 0, 30),
    datetime(2026, 10, 22, 8, 30, tzinfo=timezone(timedelta(hours=8))),
])
def test_same_instant_has_one_beijing_display(value):
    assert format_datetime_with_timezone(value) == "2026-10-22 08:30:00"
    assert datetime_for_api(value) == "2026-10-22T08:30:00+08:00"


def test_beijing_calendar_rollover_and_fractional_seconds():
    assert format_datetime_with_timezone("2026-10-21T16:00:00Z") == "2026-10-22 00:00:00"
    assert datetime_for_api("2026-10-21 16:00:00.123456") == "2026-10-22T00:00:00.123456+08:00"
    assert format_datetime_for_display("2026-10-21T16:00:00Z") == "2026年10月22日 00:00 (UTC+8)"


def test_display_timezone_is_always_beijing(monkeypatch):
    for host_timezone in ["UTC", "America/Los_Angeles", "Asia/Shanghai"]:
        monkeypatch.setenv("TZ", host_timezone)
        assert get_configured_timezone().utcoffset(None) == timedelta(hours=8)


@pytest.mark.parametrize("value", [None, "", "invalid", "2026-13-45 25:61:99"])
def test_invalid_api_timestamps_do_not_invent_an_instant(value):
    assert datetime_for_api(value) is None
    assert format_datetime_with_timezone(value) == (value or "")


@pytest.mark.parametrize("value,hours", [("UTC+8", 8), ("utc+8", 8), ("UTC", 0), ("UTC-05:30", -5.5)])
def test_legacy_offset_parser(value, hours):
    assert parse_timezone_offset(value).utcoffset(None).total_seconds() == hours * 3600


def test_browser_time_rules_across_host_timezones():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for browser time behavior tests")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, "tests/frontend/timezone_behavior.cjs"], cwd=root,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

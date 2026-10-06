"""Tests for the dashboard's data loader."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from dashboard import data
from pylitterbot import Account
from pylitterbot.robot.litterrobot5 import LitterRobot5

from .common import LITTER_ROBOT_5_DATA

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 2, 20, tzinfo=timezone.utc)


def _activity(index: int, hours_ago: int) -> dict[str, Any]:
    return {
        "messageId": f"msg-{index}",
        "type": "PET_VISIT",
        "timestamp": (NOW - timedelta(hours=hours_ago)).isoformat(),
    }


class FakeRobot:
    """Stand-in exposing only get_activities."""

    def __init__(self, activities: list[dict[str, Any]], honor_offset: bool = True):
        """Initialize with newest-first activities."""
        self.activities = activities
        self.honor_offset = honor_offset
        self.calls: list[tuple[int, int]] = []

    async def get_activities(self, limit: int, offset: int) -> list[dict[str, Any]]:
        """Return a page of activities."""
        self.calls.append((limit, offset))
        start = offset if self.honor_offset else 0
        return self.activities[start : start + limit]


async def test_fetch_activities_pages_until_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tests paging stops once a page reaches past the lookback window."""
    monkeypatch.setattr(data, "ACTIVITY_PAGE_SIZE", 2)
    robot = FakeRobot([_activity(i, hours_ago=i * 10) for i in range(10)])
    result = await data._fetch_activities(robot, NOW - timedelta(hours=25), 100)  # type: ignore[arg-type]
    assert [a["messageId"] for a in result] == ["msg-0", "msg-1", "msg-2"]
    assert robot.calls == [(2, 0), (2, 2)]


async def test_fetch_activities_respects_max_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tests paging stops at max_records."""
    monkeypatch.setattr(data, "ACTIVITY_PAGE_SIZE", 2)
    robot = FakeRobot([_activity(i, hours_ago=i) for i in range(10)])
    result = await data._fetch_activities(robot, NOW - timedelta(days=30), 3)  # type: ignore[arg-type]
    assert len(result) == 3
    assert len(robot.calls) == 2


async def test_fetch_activities_ignored_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tests paging stops if the endpoint keeps returning the same page."""
    monkeypatch.setattr(data, "ACTIVITY_PAGE_SIZE", 2)
    robot = FakeRobot([_activity(i, hours_ago=i) for i in range(10)], False)
    result = await data._fetch_activities(robot, NOW - timedelta(days=30), 100)  # type: ignore[arg-type]
    assert len(result) == 2
    assert len(robot.calls) == 2


async def test_robot_summary(mock_account: Account) -> None:
    """Tests the robot summary contains only plain values."""
    robot = LitterRobot5(data=LITTER_ROBOT_5_DATA, account=mock_account)
    summary = data._robot_summary(robot)
    assert summary["serial"] == LITTER_ROBOT_5_DATA["serial"]
    assert isinstance(summary["status"], str)
    assert isinstance(summary["waste_drawer_level"], (int, float))
    assert summary["litter_level_state"] is None or isinstance(
        summary["litter_level_state"], str
    )

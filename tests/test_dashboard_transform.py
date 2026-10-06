"""Tests for the dashboard's pandas transforms."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pytest

pytest.importorskip("pandas")

import pandas as pd  # noqa: E402

from dashboard import transform  # noqa: E402

PETS: list[dict[str, Any]] = [
    {"id": "PET-1", "name": "Mochi"},
    {"id": "PET-2", "name": "Biscuit"},
]

ACTIVITIES: list[dict[str, Any]] = [
    {
        "messageId": "msg-001",
        "type": "PET_VISIT",
        "timestamp": "2026-02-14T23:12:12Z",
        "petWeight": 937.0,
        "wasteType": "Urine",
        "duration": 31,
        "petIds": ["PET-1"],
        "wasteWeight": 40.0,
    },
    {
        "messageId": "msg-002",
        "type": "CYCLE_COMPLETED",
        "timestamp": "2026-02-14T23:29:21Z",
        "subtype": "robotCycleStateIdle",
    },
    {
        "messageId": "msg-003",
        "type": "PET_VISIT",
        "timestamp": "2026-02-16T08:00:00.000000Z",
        "petWeight": 1210.0,
        "wasteType": "Feces",
        "petIds": ["PET-2"],
    },
    {
        "messageId": "msg-004",
        "type": "PET_VISIT",
        "timestamp": "2026-02-16T09:00:00Z",
        "petIds": [],
    },
    {
        "messageId": "msg-005",
        "type": "CYCLE_COMPLETED",
        "timestamp": "2026-02-16T09:20:00Z",
    },
]


@pytest.fixture
def df() -> pd.DataFrame:
    """Return the parsed activity frame in UTC."""
    return transform.activities_df(ACTIVITIES, PETS, tz="UTC")


def test_activities_df(df: pd.DataFrame) -> None:
    """Tests cat mapping, unit conversion and ordering."""
    assert len(df) == 5
    assert df["timestamp"].is_monotonic_decreasing
    assert set(df["cat"].dropna()) == {"Mochi", "Biscuit", transform.UNASSIGNED}
    assert df.loc[df["type"] == "CYCLE_COMPLETED", "cat"].isna().all()

    mochi = df[df["cat"] == "Mochi"].iloc[0]
    assert mochi["weight_lb"] == pytest.approx(9.37)
    assert mochi["waste_type"] == "Urine"
    assert mochi["duration_s"] == 31


def test_activities_df_timezone() -> None:
    """Tests that dates follow the robot's timezone, not UTC."""
    df = transform.activities_df(ACTIVITIES[:1], PETS, tz="America/Denver")
    assert df.iloc[0]["date"] == date(2026, 2, 14)
    assert df.iloc[0]["hour"] == 16


def test_activities_df_multiple_cats() -> None:
    """Tests that a shared visit is counted once per cat."""
    activity = {**ACTIVITIES[0], "petIds": ["PET-1", "PET-2"]}
    df = transform.activities_df([activity], PETS, tz="UTC")
    assert sorted(df["cat"]) == ["Biscuit", "Mochi"]
    assert df["event_index"].nunique() == 1


def test_activities_df_empty() -> None:
    """Tests that no activity yields an empty frame with the expected columns."""
    df = transform.activities_df([], PETS)
    assert df.empty
    assert list(df.columns) == transform.ACTIVITY_COLUMNS
    assert transform.daily_cycles(df).empty
    assert transform.daily_visits_by_cat(df).empty


def test_daily_cycles(df: pd.DataFrame) -> None:
    """Tests that days without cycles are filled with 0."""
    cycles = transform.daily_cycles(df)
    assert cycles["date"].tolist() == [
        date(2026, 2, 14),
        date(2026, 2, 15),
        date(2026, 2, 16),
    ]
    assert cycles["cycles"].tolist() == [1, 0, 1]


def test_daily_visits_by_cat(df: pd.DataFrame) -> None:
    """Tests per-cat daily visit counts."""
    visits = transform.daily_visits_by_cat(df).set_index(["date", "cat"])["visits"]
    assert visits[(date(2026, 2, 14), "Mochi")] == 1
    assert visits[(date(2026, 2, 15), "Mochi")] == 0
    assert visits[(date(2026, 2, 16), "Biscuit")] == 1
    assert visits[(date(2026, 2, 16), transform.UNASSIGNED)] == 1
    assert visits.sum() == 3


def test_visits_by_waste_type(df: pd.DataFrame) -> None:
    """Tests the waste type breakdown, including missing waste types."""
    counts = transform.visits_by_waste_type(df).set_index(["cat", "waste_type"])
    assert counts.loc[("Mochi", "Urine"), "visits"] == 1
    assert counts.loc[("Biscuit", "Feces"), "visits"] == 1
    assert counts.loc[(transform.UNASSIGNED, "Unknown"), "visits"] == 1


def test_visits_since(df: pd.DataFrame) -> None:
    """Tests counting a cat's visits since a point in time."""
    since = pd.Timestamp("2026-02-15", tz="UTC")
    assert transform.visits_since(df, "Mochi", since) == 0
    assert transform.visits_since(df, "Biscuit", since) == 1


def test_weights_df() -> None:
    """Tests weight history is sorted and labelled by cat."""
    weights = [
        {
            "pet_id": "PET-1",
            "pet_name": "Mochi",
            "timestamp": datetime(2026, 2, 2, tzinfo=timezone.utc),
            "weight": 9.4,
        },
        {
            "pet_id": "PET-1",
            "pet_name": "Mochi",
            "timestamp": datetime(2026, 2, 1, tzinfo=timezone.utc),
            "weight": 9.3,
        },
    ]
    df = transform.weights_df(weights, tz="UTC")
    assert df["weight"].tolist() == [9.3, 9.4]
    assert list(df.columns) == ["timestamp", "cat", "weight"]
    assert transform.weights_df([]).empty

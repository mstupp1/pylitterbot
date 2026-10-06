"""Pure pandas transforms for the dashboard (no network access)."""

from __future__ import annotations

from datetime import datetime, tzinfo
from typing import Any

import pandas as pd

UNASSIGNED = "Unassigned"
PET_VISIT = "PET_VISIT"
CYCLE_COMPLETED = "CYCLE_COMPLETED"

ACTIVITY_COLUMNS = [
    "event_index",
    "timestamp",
    "date",
    "hour",
    "type",
    "subtype",
    "cat",
    "waste_type",
    "duration_s",
    "weight_lb",
    "waste_weight",
]


def resolve_tz(tz: str | tzinfo | None) -> str | tzinfo:
    """Return the robot's timezone, falling back to the local system timezone."""
    return tz or datetime.now().astimezone().tzinfo or "UTC"


def activities_df(
    raw: list[dict[str, Any]],
    pets: list[dict[str, Any]],
    tz: str | tzinfo | None = None,
) -> pd.DataFrame:
    """Return one row per activity per cat, with times in the robot's timezone.

    A visit attributed to several cats appears once per cat. Use `event_index`
    to count distinct events.
    """
    if not raw:
        return pd.DataFrame(columns=ACTIVITY_COLUMNS)

    names = {pet["id"]: pet["name"] for pet in pets}
    df = pd.DataFrame(raw).reset_index(names="event_index")
    for column in ("subtype", "wasteType", "duration", "petWeight", "wasteWeight"):
        if column not in df:
            df[column] = None
    if "petIds" not in df:
        df["petIds"] = None

    df["timestamp"] = pd.to_datetime(
        df["timestamp"], utc=True, format="ISO8601", errors="coerce"
    ).dt.tz_convert(resolve_tz(tz))
    df = df.dropna(subset=["timestamp"])

    df["petIds"] = df["petIds"].apply(
        lambda ids: list(ids) if isinstance(ids, list) and ids else [None]
    )
    df = df.explode("petIds")
    # Only pet visits belong to a cat; other events (cycles, etc.) have none.
    df["cat"] = df["petIds"].map(lambda pet_id: names.get(pet_id, UNASSIGNED))
    df.loc[df["type"] != PET_VISIT, "cat"] = None

    df["date"] = df["timestamp"].dt.date
    df["hour"] = df["timestamp"].dt.hour
    # The LR5 API reports pet weight as pounds * 100.
    df["weight_lb"] = pd.to_numeric(df["petWeight"], errors="coerce") / 100
    df = df.rename(
        columns={
            "wasteType": "waste_type",
            "duration": "duration_s",
            "wasteWeight": "waste_weight",
        }
    )
    return (
        df[ACTIVITY_COLUMNS]
        .sort_values("timestamp", ascending=False)
        .reset_index(drop=True)
    )


def _date_range(df: pd.DataFrame, start: Any = None, end: Any = None) -> pd.Index:
    start = start or (df["date"].min() if not df.empty else None)
    end = end or (df["date"].max() if not df.empty else None)
    if start is None or end is None:
        return pd.Index([], name="date")
    return pd.Index(pd.date_range(start, end, freq="D").date, name="date")


def daily_cycles(df: pd.DataFrame, start: Any = None, end: Any = None) -> pd.DataFrame:
    """Return completed clean cycles per day, with empty days as 0."""
    cycles = df[df["type"] == CYCLE_COMPLETED].drop_duplicates("event_index")
    counts = (
        cycles.groupby("date").size().reindex(_date_range(df, start, end), fill_value=0)
    )
    return counts.rename("cycles").reset_index()


def daily_visits_by_cat(
    df: pd.DataFrame, start: Any = None, end: Any = None
) -> pd.DataFrame:
    """Return pet visits per day per cat, with empty days as 0."""
    visits = df[df["type"] == PET_VISIT]
    counts = visits.groupby(["date", "cat"]).size().unstack(fill_value=0)
    counts = counts.reindex(_date_range(df, start, end), fill_value=0)
    return counts.reset_index().melt(
        id_vars="date", var_name="cat", value_name="visits"
    )


def visits_by_waste_type(df: pd.DataFrame) -> pd.DataFrame:
    """Return pet visit counts per cat and waste type."""
    visits = df[df["type"] == PET_VISIT].fillna({"waste_type": "Unknown"})
    return visits.groupby(["cat", "waste_type"]).size().rename("visits").reset_index()


def visits_since(df: pd.DataFrame, cat: str, since: pd.Timestamp) -> int:
    """Return how many visits a cat made at or after `since`."""
    mask = (df["type"] == PET_VISIT) & (df["cat"] == cat) & (df["timestamp"] >= since)
    return int(mask.sum())


def weights_df(
    weights: list[dict[str, Any]], tz: str | tzinfo | None = None
) -> pd.DataFrame:
    """Return weight measurements in long format for a per-cat trend line."""
    if not weights:
        return pd.DataFrame(columns=["timestamp", "cat", "weight"])
    df = pd.DataFrame(weights)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(
        resolve_tz(tz)
    )
    return (
        df.rename(columns={"pet_name": "cat"})[["timestamp", "cat", "weight"]]
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

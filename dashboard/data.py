"""Fetch a read-only snapshot of a Litter-Robot 5 and its pets.

Only read calls are made here (connect, load, get_activities and
fetch_weight_history). Nothing in this module sends commands to the robot.
"""

from __future__ import annotations

import asyncio
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import certifi
from aiohttp import ClientSession, TCPConnector

from pylitterbot import Account
from pylitterbot.exceptions import LitterRobotException
from pylitterbot.robot.litterrobot5 import LitterRobot5
from pylitterbot.utils import to_timestamp

ACTIVITY_PAGE_SIZE = 200
WEIGHT_HISTORY_LIMIT = 100


@dataclass
class DashboardSnapshot:
    """Plain-data snapshot of the robot, pets and recent activity."""

    robot: dict[str, Any]
    pets: list[dict[str, Any]]
    weights: list[dict[str, Any]]
    activities: list[dict[str, Any]]
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _enum_name(value: Any) -> str | None:
    return getattr(value, "name", None) if value is not None else None


def _robot_summary(robot: LitterRobot5) -> dict[str, Any]:
    """Convert the robot's read-only properties to primitives."""
    return {
        "name": robot.name,
        "serial": robot.serial,
        "model": robot.model,
        "timezone": robot.timezone,
        "status": robot.status.text,
        "status_code": robot.status_code,
        "is_online": robot.is_online,
        "is_sleeping": robot.is_sleeping,
        "last_seen": robot.last_seen,
        "waste_drawer_level": robot.waste_drawer_level,
        "is_waste_drawer_full": robot.is_waste_drawer_full,
        "cycle_count": robot.cycle_count,
        "cycle_capacity": robot.cycle_capacity,
        "litter_level": robot.litter_level,
        "litter_level_state": _enum_name(robot.litter_level_state),
        "optimal_litter_level": robot.optimal_litter_level,
        "hopper_status": robot.hopper_status_text,
        "hopper_status_code": _enum_name(robot.hopper_status),
        "is_laser_dirty": robot.is_laser_dirty,
        "is_gas_sensor_fault_detected": robot.is_gas_sensor_fault_detected,
        "is_usb_fault_detected": robot.is_usb_fault_detected,
        "is_drawer_removed": robot.is_drawer_removed,
        "is_bonnet_removed": robot.is_bonnet_removed,
        "wifi_rssi": robot.wifi_rssi,
        "firmware": robot.firmware,
        "next_filter_replacement_date": robot.next_filter_replacement_date,
        "scoops_saved_count": robot.scoops_saved_count,
        "odometer_power_cycles": robot.odometer_power_cycles,
        "odometer_empty_cycles": robot.odometer_empty_cycles,
        "odometer_filter_cycles": robot.odometer_filter_cycles,
        "pet_weight": robot.pet_weight,
    }


def _activity_key(activity: dict[str, Any]) -> Any:
    return (
        activity.get("messageId")
        or activity.get("eventId")
        or (activity.get("type"), activity.get("timestamp"))
    )


async def _fetch_activities(
    robot: LitterRobot5, since: datetime, max_records: int
) -> list[dict[str, Any]]:
    """Page through activities until older than `since` or `max_records`."""
    activities: list[dict[str, Any]] = []
    seen: set[Any] = set()
    offset = 0
    while len(activities) < max_records:
        page = await robot.get_activities(limit=ACTIVITY_PAGE_SIZE, offset=offset)
        new = [a for a in page if _activity_key(a) not in seen]
        if not new:
            # Empty page, or the endpoint ignored `offset` and repeated itself.
            break
        seen.update(_activity_key(a) for a in new)
        activities.extend(new)
        offset += len(page)
        timestamps = [
            ts for a in new if (ts := to_timestamp(a.get("timestamp"))) is not None
        ]
        if len(page) < ACTIVITY_PAGE_SIZE or (timestamps and min(timestamps) < since):
            break
    return [
        a
        for a in activities[:max_records]
        if (ts := to_timestamp(a.get("timestamp"))) is not None and ts >= since
    ]


async def _fetch(
    username: str, password: str, days: int, max_records: int
) -> DashboardSnapshot:
    # Use certifi's CA bundle: python.org builds of Python on macOS don't use
    # the system keychain, so the default context fails to verify Whisker's
    # certificates (CERTIFICATE_VERIFY_FAILED).
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    websession = ClientSession(connector=TCPConnector(ssl=ssl_context))
    account = Account(websession=websession)
    try:
        await account.connect(
            username=username,
            password=password,
            load_robots=True,
            load_pets=True,
            robot_types=[LitterRobot5],
        )
        robots = account.get_robots(LitterRobot5)
        if not robots:
            raise LitterRobotException(
                "No Litter-Robot 5 was found on this Whisker account."
            )
        robot = robots[0]

        since = datetime.now(timezone.utc) - timedelta(days=days)
        activities, weight_histories = await asyncio.gather(
            _fetch_activities(robot, since, max_records),
            asyncio.gather(
                *(
                    pet.fetch_weight_history(limit=WEIGHT_HISTORY_LIMIT)
                    for pet in account.pets
                ),
                return_exceptions=True,
            ),
        )

        pets = [
            {
                "id": pet.id,
                "name": pet.name,
                "breed": pet.breed,
                "age": pet.age,
                "image_url": pet.image_url,
                "last_weight_reading": pet.last_weight_reading,
            }
            for pet in account.pets
        ]
        weights = [
            {
                "pet_id": pet.id,
                "pet_name": pet.name,
                "timestamp": measurement.timestamp,
                "weight": measurement.weight,
            }
            for pet, history in zip(account.pets, weight_histories)
            if not isinstance(history, BaseException)
            for measurement in history
        ]
        return DashboardSnapshot(
            robot=_robot_summary(robot),
            pets=pets,
            weights=weights,
            activities=activities,
        )
    finally:
        await account.disconnect()
        await websession.close()


def load_snapshot(
    username: str, password: str, days: int = 30, max_records: int = 2000
) -> DashboardSnapshot:
    """Fetch a snapshot synchronously (Streamlit scripts have no event loop)."""
    return asyncio.run(_fetch(username, password, days, max_records))

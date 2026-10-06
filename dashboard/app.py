"""Read-only Streamlit dashboard for a Litter-Robot 5 and two cats.

Run with: streamlit run dashboard/app.py
"""

from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard import transform  # noqa: E402
from dashboard.data import DashboardSnapshot, load_snapshot  # noqa: E402
from pylitterbot.exceptions import (  # noqa: E402
    LitterRobotException,
    LitterRobotLoginException,
)

# Categorical slots in fixed order (cat 1, cat 2, ...); "Unassigned" is neutral.
CAT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7"]
UNASSIGNED_COLOR = "#8a8984"
# Status colors are reserved for state and always paired with an icon + label.
STATUS_GOOD, STATUS_WARNING, STATUS_CRITICAL = "#0ca30c", "#fab219", "#d03b3b"

st.set_page_config(page_title="Litter-Robot Dashboard", page_icon="🐈", layout="wide")


@st.cache_data(ttl=300, show_spinner="Fetching data from Whisker…")
def get_snapshot(username: str, _password: str, days: int) -> DashboardSnapshot:
    """Fetch and cache a snapshot (the password is excluded from the cache key)."""
    return load_snapshot(username, _password, days=days)


def cat_color_map(pets: list[dict[str, Any]]) -> dict[str, str]:
    """Give each cat a stable color by its position in the pet list."""
    colors = {
        pet["name"]: CAT_COLORS[i % len(CAT_COLORS)] for i, pet in enumerate(pets)
    }
    colors[transform.UNASSIGNED] = UNASSIGNED_COLOR
    return colors


def style_figure(fig: go.Figure, height: int = 320) -> go.Figure:
    """Apply shared, recessive chart styling."""
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=40, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None),
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridwidth=1, zeroline=False)
    return fig


def gauge(title: str, value: float, color: str) -> go.Figure:
    """Return a 0-100% gauge."""
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=value,
            number={"suffix": "%"},
            title={"text": title},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": color, "thickness": 0.6},
                "borderwidth": 0,
            },
        )
    )
    fig.update_layout(height=220, margin=dict(l=40, r=40, t=48, b=8))
    return fig


def check(label: str, ok: bool, detail: str | None = None) -> None:
    """Render one sensor check with an icon and label (never color alone)."""
    icon = "✅" if ok else "⚠️"
    st.markdown(f"{icon} **{label}**" + (f"  \n{detail}" if detail else ""))


def fmt_dt(value: Any, tz: Any) -> str:
    """Format a datetime in the robot's timezone."""
    if value is None:
        return "—"
    return str(pd.Timestamp(value).tz_convert(tz).strftime("%b %d, %Y %I:%M %p"))


def fmt_ago(value: Any, now: pd.Timestamp) -> str:
    """Format a datetime as a short relative time."""
    if value is None:
        return "—"
    minutes = int((now - pd.Timestamp(value)).total_seconds() // 60)
    if minutes < 60:
        return f"{max(minutes, 0)} min ago"
    if minutes < 48 * 60:
        return f"{minutes // 60} hr ago"
    return f"{minutes // (24 * 60)} days ago"


# --- Sidebar -----------------------------------------------------------------

load_dotenv(ROOT / ".env")
env_username = os.getenv("LITTER_ROBOT_USERNAME", "")
env_password = os.getenv("LITTER_ROBOT_PASSWORD", "")

with st.sidebar:
    st.title("🐈 Litter-Robot")
    if env_username and env_password:
        st.caption(f"Signed in from `.env` as **{env_username}**")
        username, password = env_username, env_password
    else:
        st.caption("No `.env` credentials found. Enter your Whisker login.")
        username = st.text_input("Email", value=env_username)
        password = st.text_input("Password", type="password")
    days = st.select_slider("Lookback (days)", options=[7, 14, 30, 90], value=30)
    if st.button("Refresh", width="stretch"):
        st.cache_data.clear()

if not (username and password):
    st.info("Enter your Whisker email and password in the sidebar to load data.")
    st.stop()

try:
    snapshot = get_snapshot(username, password, days)
except LitterRobotLoginException:
    st.error("Login failed. Check your Whisker email and password.")
    st.stop()
except LitterRobotException as err:
    st.error(f"Couldn't load data from Whisker: {err}")
    st.stop()

robot = snapshot.robot
tz = transform.resolve_tz(robot.get("timezone"))
colors = cat_color_map(snapshot.pets)
cat_order = [pet["name"] for pet in snapshot.pets] + [transform.UNASSIGNED]
activity = transform.activities_df(snapshot.activities, snapshot.pets, tz)
weights = transform.weights_df(snapshot.weights, tz)
now = pd.Timestamp.now(tz=tz)
start, end = (now - timedelta(days=days - 1)).date(), now.date()

with st.sidebar:
    st.caption(f"Last fetched {fmt_dt(snapshot.fetched_at, tz)}")
    st.caption(f"{len(snapshot.activities)} activity records over {days} days")

st.title(robot["name"])
online = robot["is_online"]
st.badge(
    f"{robot['status']} · {'Online' if online else 'Offline'}",
    icon="✅" if online else "⚠️",
    color="green" if online else "red",
)

health_tab, cats_tab, activity_tab = st.tabs(
    ["Robot health", "Cats", "Usage & activity"]
)

# --- Robot health --------------------------------------------------------------

with health_tab:
    drawer = robot["waste_drawer_level"] or 0
    drawer_color = (
        STATUS_CRITICAL
        if robot["is_waste_drawer_full"] or drawer >= 90
        else STATUS_WARNING
        if drawer >= 70
        else STATUS_GOOD
    )
    litter_state = robot["litter_level_state"]
    litter_color = {
        "OPTIMAL": STATUS_GOOD,
        "EMPTY": STATUS_CRITICAL,
    }.get(litter_state or "", STATUS_WARNING)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.plotly_chart(gauge("Waste drawer", drawer, drawer_color), width="stretch")
        st.caption(
            f"{robot['cycle_count']} of ~{robot['cycle_capacity']} cycles since last emptied"
        )
    with col2:
        st.plotly_chart(
            gauge("Litter level", robot["litter_level"] or 0, litter_color),
            width="stretch",
        )
        st.caption(f"State: {(litter_state or 'unknown').title()}")
    with col3:
        st.metric("Last seen", fmt_ago(robot["last_seen"], now))
        st.metric("Scoops saved", f"{robot['scoops_saved_count']:,}")
        st.metric("Lifetime clean cycles", f"{robot['odometer_power_cycles']:,}")

    st.subheader("Sensors")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        check(
            "Laser / curtain",
            not robot["is_laser_dirty"],
            "Dirty" if robot["is_laser_dirty"] else "Clean",
        )
        check("Gas sensor", not robot["is_gas_sensor_fault_detected"])
    with c2:
        check(
            "Drawer",
            not robot["is_drawer_removed"],
            "Removed" if robot["is_drawer_removed"] else "In place",
        )
        check(
            "Bonnet",
            not robot["is_bonnet_removed"],
            "Removed" if robot["is_bonnet_removed"] else "In place",
        )
    with c3:
        check("USB", not robot["is_usb_fault_detected"])
        check(
            "Hopper",
            robot["hopper_status_code"] in (None, "ENABLED", "DISABLED", "READY"),
            robot["hopper_status"] or "Not reporting",
        )
    with c4:
        rssi = robot["wifi_rssi"]
        check("Wi-Fi", rssi > -75, f"{rssi} dBm")
        check(
            "Filter",
            robot["next_filter_replacement_date"] is None
            or pd.Timestamp(robot["next_filter_replacement_date"]) > now,
            f"Replace by {fmt_dt(robot['next_filter_replacement_date'], tz)}",
        )
    st.caption(f"Firmware {robot['firmware']} · Serial {robot['serial']}")

# --- Cats ----------------------------------------------------------------------

with cats_tab:
    if not snapshot.pets:
        st.info("No pets are set up on this Whisker account.")
    today = now.normalize()
    cols = st.columns(max(len(snapshot.pets), 1))
    for col, pet in zip(cols, snapshot.pets):
        with col, st.container(border=True):
            if pet["image_url"]:
                st.image(pet["image_url"], width=120)
            st.markdown(
                f"<span style='color:{colors[pet['name']]}'>●</span> **{pet['name']}**",
                unsafe_allow_html=True,
            )
            details = [
                d for d in (pet["breed"], pet["age"] and f"{pet['age']} yrs") if d
            ]
            st.caption(" · ".join(details) or " ")
            m1, m2, m3 = st.columns(3)
            weight = pet["last_weight_reading"]
            m1.metric("Weight", f"{weight:.1f} lb" if weight else "—")
            m2.metric(
                "Visits today", transform.visits_since(activity, pet["name"], today)
            )
            m3.metric(
                "Last 7 days",
                transform.visits_since(
                    activity, pet["name"], today - timedelta(days=6)
                ),
            )

    st.subheader("Weight trend")
    if weights.empty:
        st.info("No weight history yet.")
    else:
        fig = px.line(
            weights,
            x="timestamp",
            y="weight",
            color="cat",
            markers=True,
            color_discrete_map=colors,
            category_orders={"cat": cat_order},
            labels={"timestamp": "", "weight": "Weight (lb)", "cat": "Cat"},
        )
        fig.update_traces(line_width=2, marker_size=8)
        st.plotly_chart(style_figure(fig), width="stretch")

# --- Usage & activity ------------------------------------------------------------

with activity_tab:
    visits = transform.daily_visits_by_cat(activity, start, end)
    cycles = transform.daily_cycles(activity, start, end)

    kpis = st.columns(len(snapshot.pets) + 1)
    for kpi, pet in zip(kpis, snapshot.pets):
        per_day = visits.loc[visits["cat"] == pet["name"], "visits"].sum() / days
        kpi.metric(f"{pet['name']} visits / day", f"{per_day:.1f}")
    kpis[-1].metric("Clean cycles / day", f"{cycles['cycles'].sum() / days:.1f}")

    left, right = st.columns(2)
    with left:
        st.markdown("**Daily visits by cat**")
        if visits.empty:
            st.info("No visits in this period.")
        else:
            fig = px.bar(
                visits,
                x="date",
                y="visits",
                color="cat",
                color_discrete_map=colors,
                category_orders={"cat": cat_order},
                labels={"date": "", "visits": "Visits", "cat": "Cat"},
            )
            fig.update_traces(marker_line_width=0)
            fig.update_layout(bargap=0.25)
            st.plotly_chart(style_figure(fig), width="stretch")
    with right:
        st.markdown("**Daily clean cycles**")
        if cycles.empty:
            st.info("No clean cycles in this period.")
        else:
            fig = px.line(
                cycles,
                x="date",
                y="cycles",
                markers=True,
                labels={"date": "", "cycles": "Cycles"},
            )
            fig.update_traces(line_width=2, marker_size=8, line_color=CAT_COLORS[0])
            st.plotly_chart(style_figure(fig), width="stretch")

    left, right = st.columns(2)
    pet_visits = activity[activity["type"] == transform.PET_VISIT]
    with left:
        st.markdown("**Visits by hour of day**")
        if not pet_visits.empty:
            by_hour = (
                pet_visits.groupby(["hour", "cat"])
                .size()
                .rename("visits")
                .reset_index()
            )
            fig = px.bar(
                by_hour,
                x="hour",
                y="visits",
                color="cat",
                barmode="group",
                color_discrete_map=colors,
                category_orders={"cat": cat_order},
                labels={"hour": "Hour of day", "visits": "Visits", "cat": "Cat"},
            )
            fig.update_xaxes(dtick=3, range=[-0.5, 23.5])
            fig.update_layout(hovermode="closest")
            st.plotly_chart(style_figure(fig), width="stretch")
    with right:
        waste = transform.visits_by_waste_type(activity)
        if not waste.empty:
            st.markdown("**Visits by waste type**")
            st.dataframe(
                waste.pivot(index="cat", columns="waste_type", values="visits")
                .fillna(0)
                .astype(int)
                .rename_axis(index="Cat", columns=None),
                width="stretch",
            )

    st.subheader("Activity log")
    f1, f2 = st.columns(2)
    types = sorted(activity["type"].dropna().unique())
    selected_types = f1.multiselect("Activity type", types, default=types)
    cats = [c for c in cat_order if c in set(activity["cat"])]
    selected_cats = f2.multiselect("Cat", cats, default=cats)
    log = activity[
        activity["type"].isin(selected_types)
        & (activity["cat"].isin(selected_cats) | activity["cat"].isna())
    ]
    st.dataframe(
        log.drop(columns=["event_index", "date", "hour"]).assign(
            timestamp=log["timestamp"].dt.strftime("%Y-%m-%d %I:%M %p")
        ),
        width="stretch",
        hide_index=True,
        column_config={
            "timestamp": "Time",
            "type": "Type",
            "subtype": "Subtype",
            "cat": "Cat",
            "waste_type": "Waste type",
            "duration_s": st.column_config.NumberColumn("Duration (s)"),
            "weight_lb": st.column_config.NumberColumn("Weight (lb)", format="%.2f"),
            "waste_weight": st.column_config.NumberColumn("Waste weight (raw)"),
        },
    )

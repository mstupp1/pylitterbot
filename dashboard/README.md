# Litter-Robot 5 dashboard

A local, **read-only** Streamlit dashboard for one Litter-Robot 5 and its cats.
It shows robot health, per-cat visits and weight trends, and an activity log,
using the same Whisker API the app uses. It never sends commands to the robot.

## Setup

```sh
uv sync --extra dashboard        # or: pip install -e ".[dashboard]"
cp .env.example .env             # then fill in your Whisker email and password
uv run streamlit run dashboard/app.py
```

If `.env` is missing, the sidebar asks for your login instead. Data is cached
for 5 minutes. Use **Refresh** in the sidebar to fetch it again.

## Notes

- Per-cat visits come from `PET_VISIT` activity records (`petIds`). Visits the
  robot couldn't match to a cat show as **Unassigned**.
- Visit weight is the API's `petWeight / 100` (pounds), the same conversion
  `LitterRobot5.pet_weight` uses. `wasteWeight` is shown raw because its units
  aren't documented.
- Dates and hours use the robot's configured timezone.

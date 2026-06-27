# Amazfit Sync

Python utility for fetching Amazfit/Zepp data into local JSON storage and then exporting normalized daily notes to Obsidian.

## Current status

This project works in two stages:

1. Fetch and persist raw API payloads plus normalized JSON.
2. Render deterministic Markdown files for Obsidian from normalized data.

The public contract for modern Amazfit/Zepp endpoints is not documented, and reverse-engineered flows are a starting point, not a guaranteed specification.

Source used as implementation baseline:

- [Reverse engineering of the Mi Fit API](https://raw.githubusercontent.com/micw/hacking-mifit-api/master/README.md)

## What the tool does

- Reads credentials from `.env`
- Loads local auth state from `data/auth_state.json`
- Prefers existing `app_token` and `user_id` from local state or `.env`
- Falls back to Zepp login exchange only when cached app credentials are missing or rejected
- Probes a catalog of reverse-engineered data endpoints across multiple API hosts
- Fetches daily step totals, distance, calories, and sleep data from the `band_data.json` summary endpoint
- Extracts hourly step distribution and activity bout details from the detail endpoint
- Fetches body weight from the private `weightRecords` endpoint
- Fetches workout history and per-workout details from run endpoints
- Saves successful responses into `data/raw/...`
- Builds normalized day-centric bundles in monthly files under `data/normalized/YYYY/YYYY-MM.json`
- Carries forward the last measured weight to days without a new measurement
- Computes 14-day rolling trends for steps, sleep, resting HR, weight, and goal hit rate
- Exports Markdown day notes into the configured Obsidian directory

## Important limitation

The data endpoints are a best-effort implementation based on older Huami/Mi Fit behavior. For modern Amazfit devices, some endpoints may:

- still work as-is
- require different hostnames
- require a different access-token exchange flow
- require direct bearer-auth endpoints instead of the old `apptoken` flow

Because of that, the first command you should run is `probe`, not `sync`.

## Environment variables

**Recommended method — extract tokens from browser (no mobile logout):**
Run `python extract_tokens_web.py` and follow the instructions. It will guide you to log into https://watchface.zepp.com/ in your browser and extract `app_token` + `user_id` from cookies. This does **not** log you out of the Zepp mobile app.

**Alternative — huami-token (logs out mobile app):**
Use https://github.com/argrento/huami-token to get all tokens. Then run `python refresh_tokens.py` which auto-updates `.env`.

Required:

- `AMAZFIT_APP_TOKEN` — app-level credential for data endpoints
- `AMAZFIT_USER_ID` — your Zepp account user ID
- `AMAZFIT_ACCESS_TOKEN` — only needed for first-time Zepp login exchange (not needed once app_token is cached)

Optional but useful:

- `AMAZFIT_COUNTRY_CODE` — default `US`
- `AMAZFIT_ACCOUNT_BASE_URL`
- `AMAZFIT_API_HOSTS` — comma-separated list of API hosts to probe
- `AMAZFIT_TOKEN_REFRESH_URL` — optional, no known working refresh endpoint exists
- `AMAZFIT_AUTH_STATE_PATH` — path to local auth state file (default `data/auth_state.json`)
- `AMAZFIT_BEARER_API_BASE_URL` — for direct bearer-auth probing
- `AMAZFIT_BEARER_PROBE_ENDPOINTS` — comma-separated bearer endpoints to probe
- `AMAZFIT_ZEPP_LOGIN_URL` — Zepp login exchange URL
- `AMAZFIT_EXTRA_APP_ENDPOINTS` — additional apptoken-style endpoints
- `AMAZFIT_DATA_DIR` — runtime JSON storage directory (default `data`)
- `OBSIDIAN_EXPORT_DIR` — Obsidian vault path for exported markdown
- `AMAZFIT_FROM_DATE` — default start date for sync (default `1970-01-01`)
- `AMAZFIT_TO_DATE` — default end date for sync (defaults to today)

When `AMAZFIT_DEVICE_ID` is not provided, the tool generates a stable device identifier once and stores it in the local auth state file.

`OBSIDIAN_EXPORT_DIR` can be either a relative path like `exports/obsidian` or an absolute path like `D:/Obsidian-Dima/activity-reports`.

## Install

Requires:

- Python 3.12+
- `uv`

```bash
uv sync
```

Run the CLI through `uv run main.py ...`.

## CLI usage

Show help:

```bash
uv run main.py --help
```

Probe endpoints first:

```bash
uv run main.py probe
```

Fetch data and write raw plus normalized JSON:

```bash
uv run main.py sync
```

Without explicit dates, `sync` starts from the latest day already present in normalized data and fetches through today inclusive. If no normalized bundles exist yet, it falls back to `AMAZFIT_FROM_DATE` / `AMAZFIT_TO_DATE` or built-in defaults.

Fetch a specific date range:

```bash
uv run main.py --from 2026-03-01 --to 2026-03-15 sync
```

Fetch only raw payloads (skip normalization):

```bash
uv run main.py dump-raw
```

Export merged normalized bundles to Obsidian Markdown:

```bash
uv run main.py export-obsidian
```

Without explicit dates, `export-obsidian` always rewrites yesterday's report and backfills any missing reports from the previous 14 days.

Export from a specific normalized bundle file:

```bash
uv run main.py export-obsidian --bundle data/normalized/2026/2026-03.json
```

Export a specific date range (overwrites all files in range):

```bash
uv run main.py --from 2026-03-10 --to 2026-03-12 export-obsidian
```

## Output layout

Runtime artifacts are ignored by git and stored locally:

```text
data/
  raw/
    band_summary/
    band_detail/
    weight_records/
    run_history/
    run_detail/
    ...
  normalized/
    2026/
      2026-03.json
    2025/
      2025-12.json
  reports/
    latest_validation.json
    validation_<timestamp>.json
  auth_state.json

exports/
  obsidian/
    2026-03-01-physical.md
    2026-03-02-physical.md
```

## Normalized JSON shape

The normalized bundle is day-centric:

```json
{
  "generated_at": "2026-03-15T12:00:00+00:00",
  "date_range": {
    "from": "2026-03-01",
    "to": "2026-03-15"
  },
  "resources": [
    "band_detail",
    "band_summary",
    "run_detail",
    "run_history",
    "weight_records"
  ],
  "days": [
    {
      "date": "2026-03-01",
      "daily_summary": {
        "timezone_offset_minutes": 180,
        "goal_steps": 8000,
        "steps_total": 8543,
        "distance_meters": 6200,
        "calories_kcal": 312,
        "walk_minutes": 74,
        "run_distance_meters": 0,
        "run_calories_kcal": 0
      },
      "sleep": {
        "sleep_start_epoch": 1740873600,
        "sleep_end_epoch": 1740909600,
        "deep_sleep_minutes": 120,
        "light_sleep_minutes": 280,
        "resting_heart_rate": 58,
        "stages": []
      },
      "activity": {
        "goal_completion_pct": 106.8,
        "activity_bout_count": 12,
        "active_stage_minutes": 95,
        "longest_activity_bout_minutes": 22,
        "peak_steps_per_minute": 92.5,
        "peak_activity_hour": "14:00"
      },
      "recovery": {
        "sleep_minutes": 400,
        "time_in_bed_minutes": 600,
        "resting_heart_rate": 58
      },
      "trends": {
        "window_days_14d": 14,
        "steps_rolling_avg_14d": 7200.5,
        "sleep_minutes_rolling_avg_14d": 380.2,
        "resting_hr_rolling_avg_14d": 59.1,
        "weight_rolling_avg_14d": 91.5,
        "goal_hit_rate_14d": 64.3,
        "resting_hr_delta_14d": -1.1,
        "weight_delta_14d": -0.3
      },
      "heart_rate": [],
      "workouts": [],
      "body_metrics": [],
      "body": {
        "measured_at": "2026-03-01T08:30:00+00:00",
        "weight_kg": 91.8,
        "bmi": 27.1,
        "body_fat_pct": 22.5
      },
      "extras": {
        "step_stages": [],
        "step_stage_summary": []
      },
      "source_payload_ref": [
        "data/raw/band_summary/..."
      ]
    }
  ]
}
```

On days without a weight measurement, the `body` field inherits the last measured values from a previous day.

## Obsidian export format

Each exported day is rendered to one markdown file named `YYYY-MM-DD-physical.md`.

By default, the command always rewrites yesterday and creates any missing files from the previous 14 days. When `--from` / `--to` are provided, only days inside that inclusive range are rendered and all selected files are rewritten.

Each file contains YAML frontmatter and the following sections:

- **Trends (14d)** — 14-day rolling baseline vs today with deltas for steps, sleep, resting HR, and weight
- **Steps** — total steps, distance, walk minutes, peak steps per minute
- **Steps By Hour** — hourly step breakdown (from device step stage summary)
- **Body** — weight, BMI, body fat percentage (inherited from last measurement if not measured that day)
- **Activity** — calories, detected activity sessions, active minutes, longest bout, peak activity hour
- **Sleep** — sleep start/end, time in bed, total/deep/light sleep minutes, resting heart rate

The raw/normalized JSON is the source of truth. Markdown is a presentation/export layer.

## Practical workflow

1. Get your `AMAZFIT_ACCESS_TOKEN` using https://github.com/argrento/huami-token or run `python extract_tokens_web.py` for browser-based extraction (recommended).
2. Fill `.env` with `AMAZFIT_APP_TOKEN` and `AMAZFIT_USER_ID`.
3. Run `uv sync`.
4. Run `uv run main.py probe`.
5. Inspect `data/reports/latest_validation.json`.
6. If at least one endpoint works, run `uv run main.py sync`.
7. Inspect the monthly files in `data/normalized/`.
8. Run `uv run main.py export-obsidian`.
9. Point Obsidian to your export directory or copy the generated notes into your vault.

## Security notes

- Raw API payloads are stored locally — treat `data/` as sensitive.
- Token refresh is only attempted if `AMAZFIT_TOKEN_REFRESH_URL` is explicitly configured.
- Cached app credentials are preferred over password-style or access-token login flows.
- Probe results are written even when endpoints fail, so you can inspect exact HTTP status codes.

## Verified endpoints in this workspace

Working:
- `https://api-mifit.zepp.com/v1/data/band_data.json` (summary and detail)
- `https://api-mifit.zepp.com/v1/sport/run/history.json`
- `https://api-mifit.zepp.com/v1/sport/run/detail.json`
- `https://api-mifit.zepp.com/users/<user_id>/members/-1/weightRecords`

Not working (404/400):
- `sleep_data.json`
- `activity_data.json`
- `workout_data.json`
- `body_data.json`
- `heart_rate.json`

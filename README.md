# Amazfit Sync

Python utility for fetching Amazfit/Zepp data into local JSON storage and then exporting normalized daily notes to Obsidian.

## Current status

This project is intentionally built in two stages:

1. Fetch and persist raw API payloads plus normalized JSON.
2. Render deterministic Markdown files for Obsidian from normalized data.

That split is necessary because the public contract for modern Amazfit/Zepp endpoints is not documented well enough, and the reverse-engineered Mi Fit flow is only a starting point, not a guaranteed specification.

Source used as implementation baseline:

- [Reverse engineering of the Mi Fit API](https://raw.githubusercontent.com/micw/hacking-mifit-api/master/README.md)

## What the tool does

- Reads credentials from `.env`
- Loads local auth state from `data/auth_state.json` by default
- Prefers existing `app_token` and `user_id` from local state or `.env`
- Falls back to access-token refresh and Zepp login exchange only when cached app credentials are missing or rejected
- Probes a small catalog of reverse-engineered data endpoints
- Fetches body weight from the private `weightRecords` endpoint when the account exposes it
- Saves successful responses into `data/raw/...`
- Builds normalized day-centric bundles in monthly files under `data/normalized/YYYY/YYYY-MM.json`
- Exports Markdown day notes into `exports/obsidian/`

## Important limitation

The data endpoints in this repo are a best-effort implementation based on older Huami/Mi Fit behavior. For an actual `Amazfit Bip 6`, some endpoints may:

- still work as-is
- require different hostnames
- require a different access-token exchange flow
- require direct bearer-auth endpoints instead of the old `apptoken` flow

Because of that, the first command you should run is `probe`, not `sync`.

Weight import is also reverse-engineered. In this repo it uses a private endpoint under `/users/{user_id}/members/-1/weightRecords`, not the official public Huami Web API.

## Environment variables

**Recommended method — extract tokens from browser (no mobile logout):**
Run `python extract_tokens_web.py` and follow the instructions. It will guide you to log into https://watchface.zepp.com/ in your browser and extract `app_token` + `user_id` from cookies. This does **not** log you out of the Zepp mobile app.

**Alternative — huami-token (logs out mobile app):**
Use https://github.com/argrento/huami-token to get all tokens. Then run `python refresh_tokens.py` which auto-updates `.env`.

Required:

- `AMAZFIT_APP_TOKEN` — app-level credential for data endpoints
- `AMAZFIT_USER_ID` — your Zepp account user ID
- `AMAZFIT_ACCESS_TOKEN` — only needed for first-time Zepp login exchange (not needed once app_token is cached)
- `AMAZFIT_REFRESH_TOKEN` — optional, no known working refresh endpoint exists

Optional but useful:

- `AMAZFIT_APP_TOKEN`
- `AMAZFIT_USER_ID`
- `AMAZFIT_COUNTRY_CODE`
- `AMAZFIT_ACCOUNT_BASE_URL`
- `AMAZFIT_API_HOSTS`
- `AMAZFIT_TOKEN_REFRESH_URL`
- `AMAZFIT_AUTH_STATE_PATH`
- `AMAZFIT_BEARER_API_BASE_URL`
- `AMAZFIT_BEARER_PROBE_ENDPOINTS`
- `AMAZFIT_ZEPP_LOGIN_URL`
- `AMAZFIT_EXTRA_APP_ENDPOINTS`
- `AMAZFIT_DATA_DIR`
- `OBSIDIAN_EXPORT_DIR`
- `AMAZFIT_FROM_DATE`
- `AMAZFIT_TO_DATE`

If both `AMAZFIT_ACCESS_TOKEN` and `AMAZFIT_APP_TOKEN` are present, the tool now prefers the cached app credentials first. It only falls back to refresh or Zepp login exchange when the cached app token is missing or when a data endpoint responds with `401`.

When `AMAZFIT_DEVICE_ID` is not provided, the tool generates a stable device identifier once and stores it in the local auth state file. It no longer sends a different random device identifier on every run.

`OBSIDIAN_EXPORT_DIR` can be either a relative path like `exports/obsidian` or an absolute path like `D:/Obsidian-Dima/activity-reports`.

If the default reverse-engineered endpoint catalog is wrong for your account/device, add your own paths:

- `AMAZFIT_EXTRA_APP_ENDPOINTS` for old `apptoken`-style requests
- `AMAZFIT_BEARER_PROBE_ENDPOINTS` together with `AMAZFIT_BEARER_API_BASE_URL` for direct bearer-auth probing

## Install

Requires:

- Python 3.12+
- `uv`

Install the project environment with:

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

Without explicit dates, `sync` reuses the latest day already present in normalized data as the start date and fetches through today inclusive. If no normalized bundles exist yet, it falls back to `AMAZFIT_FROM_DATE` / `AMAZFIT_TO_DATE` or the built-in defaults.

Fetch a specific date range:

```bash
uv run main.py --from 2026-03-01 --to 2026-03-15 sync
```

Fetch only raw payloads:

```bash
uv run main.py dump-raw
```

Export merged normalized bundles to Obsidian Markdown:

```bash
uv run main.py export-obsidian
```

Without explicit dates, `export-obsidian` always rewrites yesterday's report and also backfills any missing reports from the previous 14 days.

Export from a specific normalized bundle file:

```bash
uv run main.py export-obsidian --bundle data/normalized/2026/2026-03.json
```

Export a specific normalized date range:

```bash
uv run main.py --from 2026-03-10 --to 2026-03-12 export-obsidian
```

## Output layout

Runtime artifacts are ignored by git and stored locally:

```text
data/
  raw/
    band_summary/
    weight_records/
    heart_rate/
    ...
  normalized/
    2026/
      2026-03.json
    2025/
      2025-12.json
  reports/
    latest_validation.json
    validation_<timestamp>.json

exports/
  obsidian/
    2026-03-01-physical.md
    2026-03-02-physical.md
```

## Normalized JSON shape

The normalized bundle is day-centric and intentionally stable even if raw payloads change:

```json
{
  "generated_at": "2026-03-15T12:00:00+00:00",
  "date_range": {
    "from": "2026-03-01",
    "to": "2026-03-15"
  },
  "resources": [
    "band_summary"
  ],
  "days": [
    {
      "date": "2026-03-01",
      "daily_summary": {
        "steps_total": 1119,
        "distance_meters": 757
      },
      "sleep": {
        "deep_sleep_minutes": 194,
        "light_sleep_minutes": 250
      },
      "heart_rate": [],
      "workouts": [],
      "body_metrics": [],
      "body": {
        "weight_kg": 91.8,
        "bmi": 27.1
      },
      "extras": {},
      "source_payload_ref": [
        "data/raw/band_summary/..."
      ]
    }
  ]
}
```

## Obsidian export behavior

Each exported day is rendered to one markdown file named `YYYY-MM-DD-physical.md`.

By default, the command always rewrites yesterday and creates any missing files from the previous 14 days. When `--from` / `--to` are provided, only days inside that inclusive range are rendered and the selected files are rewritten.

Each exported file contains:

- frontmatter with date and core metrics
- weight and body summary when available
- summary section
- sleep section
- optional JSON blocks for workouts, heart rate, body metrics, and extras
- source payload references for traceability

This is intentionally simple. The raw/normalized JSON is the source of truth. Markdown is a presentation/export layer.

## Practical workflow

1. Get your `AMAZFIT_ACCESS_TOKEN` and `AMAZFIT_REFRESH_TOKEN` using https://github.com/argrento/huami-token.
2. Fill `.env`.
3. Run `uv sync`.
4. Run `uv run main.py probe`.
5. Inspect `data/reports/latest_validation.json`.
6. If at least one endpoint works, run `uv run main.py sync`.
7. Inspect the monthly files in `data/normalized/`.
8. Run `uv run main.py export-obsidian`.
9. Point Obsidian to `exports/obsidian` or copy the generated notes into your vault structure.

## Security notes

- `.env` is ignored by git.
- `data/auth_state.json` is also local-only and may contain live tokens, so treat it as sensitive.
- The tool does not print token values.
- Raw API payloads are stored locally, so treat `data/` as sensitive.
- Token refresh is only attempted if `AMAZFIT_TOKEN_REFRESH_URL` is explicitly configured.
- Cached app credentials are preferred over password-style or access-token login flows to reduce unnecessary account re-logins and device/session churn.
- Probe results are written even when endpoint validation fails, so you can inspect exact HTTP status codes.

## What was verified in this repo

- Python modules compile successfully.
- CLI starts successfully and exposes the intended commands.
- Live probe was executed in this workspace and produced a structured validation report in `data/reports/latest_validation.json`.
- The old Huami login exchange was not correct for tokens obtained from `huami-token`.
- After switching to the newer Zepp login exchange, live sync succeeded in this workspace.
- Confirmed working endpoints in this workspace:
  - `https://api-mifit.zepp.com/v1/data/band_data.json`
  - `https://api-mifit.zepp.com/v1/sport/run/history.json`
  - `https://api-mifit.zepp.com/v1/sport/run/detail.json`
  - `https://api-mifit.zepp.com/users/<user_id>/members/-1/weightRecords`
- Confirmed non-working guesses in this workspace:
  - `sleep_data.json` -> `404`
  - `activity_data.json` -> `404`
  - `workout_data.json` -> `404`
  - `body_data.json` -> `404`
  - `heart_rate.json` -> `400`

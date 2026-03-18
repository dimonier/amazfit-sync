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
- Prefers exchanging `AMAZFIT_ACCESS_TOKEN` into a fresh `app_token` and `user_id` using the newer Zepp login flow
- Probes a small catalog of reverse-engineered data endpoints
- Fetches body weight from the private `weightRecords` endpoint when the account exposes it
- Saves successful responses into `data/raw/...`
- Builds normalized day-centric bundles in monthly files under `data/normalized/YYYY/YYYY-MM.json`
- Exports one Markdown file per day into `exports/obsidian/`

## Important limitation

The data endpoints in this repo are a best-effort implementation based on older Huami/Mi Fit behavior. For an actual `Amazfit Bip 6`, some endpoints may:

- still work as-is
- require different hostnames
- require a different access-token exchange flow
- require direct bearer-auth endpoints instead of the old `apptoken` flow

Because of that, the first command you should run is `probe`, not `sync`.

Weight import is also reverse-engineered. In this repo it uses a private endpoint under `/users/{user_id}/members/-1/weightRecords`, not the official public Huami Web API.

## Project structure

```text
main.py
amazfit_sync/
  amazfit_api.py
  config.py
  models.py
  normalize.py
  obsidian_export.py
  pipeline.py
  storage.py
.env.example
```

## Environment variables

Copy `.env.example` to `.env` and fill it.

Required in the common path:

- `AMAZFIT_ACCESS_TOKEN`
- `AMAZFIT_REFRESH_TOKEN` - optional in code path, but usually worth keeping

Optional but useful:

- `AMAZFIT_APP_TOKEN`
- `AMAZFIT_USER_ID`
- `AMAZFIT_COUNTRY_CODE`
- `AMAZFIT_ACCOUNT_BASE_URL`
- `AMAZFIT_API_HOSTS`
- `AMAZFIT_TOKEN_REFRESH_URL`
- `AMAZFIT_BEARER_API_BASE_URL`
- `AMAZFIT_BEARER_PROBE_ENDPOINTS`
- `AMAZFIT_ZEPP_LOGIN_URL`
- `AMAZFIT_EXTRA_APP_ENDPOINTS`
- `AMAZFIT_DATA_DIR`
- `OBSIDIAN_EXPORT_DIR`
- `AMAZFIT_FROM_DATE`
- `AMAZFIT_TO_DATE`

If both `AMAZFIT_ACCESS_TOKEN` and `AMAZFIT_APP_TOKEN` are present, the tool prefers the access-token exchange and generates a fresh app token for the current session. This is deliberate because stale app tokens often fail with `401 invalid token`.

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

Although `pyproject.toml` defines a project script named `amazfit-sync`, `uv sync` currently skips installing entry points because this project is not packaged yet. That means `uv run amazfit-sync ...` does not work in the current repo state.

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

Export from a specific normalized bundle file:

```bash
uv run main.py export-obsidian --bundle data/normalized/2026/2026-03.json
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
    2026-03-01.md
    2026-03-02.md
    index.md
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

Each day is rendered to one markdown file:

- frontmatter with date and core metrics
- weight and body summary when available
- summary section
- sleep section
- optional JSON blocks for workouts, heart rate, body metrics, and extras
- source payload references for traceability

This is intentionally simple. The raw/normalized JSON is the source of truth. Markdown is a presentation/export layer.

## Practical workflow

1. Fill `.env`.
2. Run `uv sync`.
3. Run `uv run main.py probe`.
4. Inspect `data/reports/latest_validation.json`.
5. If at least one endpoint works, run `uv run main.py sync`.
6. Inspect the monthly files in `data/normalized/`.
7. Run `uv run main.py export-obsidian`.
8. Point Obsidian to `exports/obsidian` or copy the generated notes into your vault structure.

## Security notes

- `.env` is ignored by git.
- The tool does not print token values.
- Raw API payloads are stored locally, so treat `data/` as sensitive.
- Token refresh is only attempted if `AMAZFIT_TOKEN_REFRESH_URL` is explicitly configured.
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

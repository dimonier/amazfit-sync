from __future__ import annotations

import argparse
from contextlib import suppress
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Sequence

from amazfit_sync.amazfit_api import AmazfitApiClient, AmazfitApiError
from amazfit_sync.config import AppConfig, ConfigError, load_config
from amazfit_sync.models import RawPayloadRecord
from amazfit_sync.normalize import normalize_records
from amazfit_sync.obsidian_export import export_bundle_to_obsidian
from amazfit_sync.storage import JsonStorage, build_validation_report

FULL_HISTORY_FROM_DATE = "1970-01-01"
FULL_HISTORY_TO_DATE = "9999-12-31"


def _log(message: str) -> None:
    print(message, flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        require_api_credentials = args.command != "export-obsidian"
        config = load_config(
            Path(args.env_file) if args.env_file else None,
            require_api_credentials=require_api_credentials,
        )
        config = _apply_runtime_overrides(config, args)
        storage = JsonStorage(config.data_dir)
        storage.ensure_dirs()

        if args.command == "sync":
            return _run_sync(config, storage)
        if args.command == "dump-raw":
            return _run_dump_raw(config, storage)
        if args.command == "export-obsidian":
            return _run_export(config, storage, args.bundle)
        if args.command == "probe":
            return _run_probe(config, storage)
    except (ConfigError, AmazfitApiError, FileNotFoundError) as exc:
        _log(f"ERROR: {exc}")
        return 1

    _log("ERROR: Unknown command.")
    return 1


def _run_sync(config: AppConfig, storage: JsonStorage) -> int:
    _log(
        "Starting sync "
        f"for {config.default_from_date.isoformat()}..{config.default_to_date.isoformat()}"
    )
    result = _fetch_and_store(config, storage)
    all_raw_records = storage.load_raw_payloads()
    _log(f"Normalizing {len(all_raw_records)} stored raw payload(s) into monthly bundles")
    bundle = normalize_records(
        all_raw_records,
        from_date=FULL_HISTORY_FROM_DATE,
        to_date=FULL_HISTORY_TO_DATE,
        validation_report_path=result["validation_report_path"],
    )
    bundle_paths = storage.save_normalized_bundle(bundle)
    successful = [item for item in result["probe_results"] if item.ok]
    _log(f"Saved validation report to {result['validation_report_path']}")
    _log(f"Successful endpoint fetches: {len(successful)} / {len(result['probe_results'])}")
    _log(f"Saved {len(result['raw_records'])} raw payload(s)")
    _log(f"Saved {len(bundle_paths)} normalized monthly bundle(s) to {storage.normalized_dir}")
    return 0


def _run_dump_raw(config: AppConfig, storage: JsonStorage) -> int:
    _log(
        "Starting raw dump "
        f"for {config.default_from_date.isoformat()}..{config.default_to_date.isoformat()}"
    )
    result = _fetch_and_store(config, storage)
    successful = [item for item in result["probe_results"] if item.ok]
    _log(f"Saved validation report to {result['validation_report_path']}")
    _log(f"Successful endpoint fetches: {len(successful)} / {len(result['probe_results'])}")
    _log(f"Saved {len(result['raw_records'])} raw payload(s)")
    return 0


def _run_probe(config: AppConfig, storage: JsonStorage) -> int:
    _log(
        "Starting probe "
        f"for {config.default_from_date.isoformat()}..{config.default_to_date.isoformat()}"
    )
    result = _fetch_and_store(config, storage, persist_raw=False)
    _log(f"Saved validation report to {result['validation_report_path']}")
    successful = [item for item in result["probe_results"] if item.ok]
    _log(f"Successful endpoint probes: {len(successful)} / {len(result['probe_results'])}")
    return 0


def _run_export(config: AppConfig, storage: JsonStorage, bundle_path: str | None) -> int:
    bundle = storage.load_normalized_bundle(Path(bundle_path) if bundle_path else None)
    written_paths = export_bundle_to_obsidian(bundle, config.obsidian_export_dir)
    _log(f"Exported {len(written_paths)} markdown file(s) to {config.obsidian_export_dir}")
    return 0


def _fetch_and_store(
    config: AppConfig,
    storage: JsonStorage,
    *,
    persist_raw: bool = True,
) -> dict[str, object]:
    raw_records = []
    detail_records = []
    probe_results = []
    exchange_status = "not_attempted"
    exchange_error = None

    client = AmazfitApiClient(config)
    try:
        with suppress(AmazfitApiError):
            _log("Checking whether the access token can be refreshed")
            refreshed = client.try_refresh_access_token()
            if refreshed:
                _log(
                    "Refreshed access token successfully. "
                    "Update your .env if you want to persist the new token values."
                )

        try:
            _log("Resolving app credentials")
            credentials = client.resolve_app_credentials()
            exchange_status = f"ok:{credentials['credential_source']}"
            _log(f"Resolved app credentials using {credentials['credential_source']}")
        except AmazfitApiError as exc:
            exchange_status = "failed"
            exchange_error = str(exc)
            validation_report = build_validation_report(
                from_date=config.default_from_date.isoformat(),
                to_date=config.default_to_date.isoformat(),
                probe_results=probe_results,
                exchange_status=exchange_status,
                exchange_error=exchange_error,
            )
            validation_path = storage.save_validation_report(validation_report)
            raise AmazfitApiError(
                f"{exchange_error} Validation report saved to {validation_path.as_posix()}"
            ) from exc

        _log("Fetching endpoint payloads")
        probe_results, raw_records = client.probe_and_fetch(
            from_date=config.default_from_date,
            to_date=config.default_to_date,
            credentials=credentials,
            progress=_log,
        )
        successful_probes = [probe for probe in probe_results if probe.ok]
        _log(f"Completed endpoint fetches: {len(successful_probes)} / {len(probe_results)} successful")
        if persist_raw:
            _log(f"Persisting {len(raw_records)} raw payload(s)")
            for record, probe in zip(raw_records, successful_probes, strict=False):
                _persist_raw_record(storage, record)
                probe.raw_path = record.raw_path

            history_record = next((record for record in raw_records if record.resource == "run_history"), None)
            if history_record is not None:
                _log("Fetching run detail payloads linked from run_history")
                detail_records = client.fetch_run_detail_records(
                    history_record,
                    app_token=credentials["app_token"],
                    progress=_log,
                )
                _log(f"Fetched {len(detail_records)} run detail payload(s)")
                if detail_records:
                    _log(f"Persisting {len(detail_records)} run detail payload(s)")
                for record in detail_records:
                    _persist_raw_record(storage, record)
    finally:
        client.close()

    validation_report = build_validation_report(
        from_date=config.default_from_date.isoformat(),
        to_date=config.default_to_date.isoformat(),
        probe_results=probe_results,
        exchange_status=exchange_status,
        exchange_error=exchange_error,
    )
    validation_path = storage.save_validation_report(validation_report)
    _log(f"Validation report written to {validation_path.as_posix()}")

    return {
        "raw_records": [*raw_records, *detail_records],
        "probe_results": probe_results,
        "validation_report_path": validation_path.as_posix(),
    }


def _persist_raw_record(storage: JsonStorage, record: RawPayloadRecord) -> None:
    raw_path = storage.save_raw_payload(record)
    record.raw_path = raw_path.as_posix()


def _apply_runtime_overrides(config: AppConfig, args: argparse.Namespace) -> AppConfig:
    from_date = _parse_optional_date(args.from_date) or config.default_from_date
    to_date = _parse_optional_date(args.to_date) or config.default_to_date
    if from_date > to_date:
        raise ConfigError("--from cannot be after --to.")

    data_dir = Path(args.data_dir) if args.data_dir else config.data_dir
    obsidian_dir = Path(args.obsidian_dir) if args.obsidian_dir else config.obsidian_export_dir

    return replace(
        config,
        default_from_date=from_date,
        default_to_date=to_date,
        data_dir=data_dir,
        obsidian_export_dir=obsidian_dir,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amazfit-sync",
        description="Fetch Amazfit data into raw/normalized JSON and export it to Obsidian.",
    )
    parser.add_argument("--env-file", help="Optional path to a specific .env file.")
    parser.add_argument("--from", dest="from_date", help="Override start date (YYYY-MM-DD).")
    parser.add_argument("--to", dest="to_date", help="Override end date (YYYY-MM-DD).")
    parser.add_argument("--data-dir", help="Override runtime JSON storage directory.")
    parser.add_argument("--obsidian-dir", help="Override Obsidian markdown export directory.")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("sync", help="Fetch data and write raw plus normalized JSON.")
    subparsers.add_parser("dump-raw", help="Fetch data and only write raw JSON.")
    subparsers.add_parser("probe", help="Probe configured endpoints without writing raw payloads.")

    export_parser = subparsers.add_parser(
        "export-obsidian",
        help="Render Obsidian markdown from normalized period bundles.",
    )
    export_parser.add_argument(
        "--bundle",
        help="Optional explicit path to a normalized bundle JSON file.",
    )
    return parser


def _parse_optional_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ConfigError("Date arguments must use YYYY-MM-DD format.") from exc

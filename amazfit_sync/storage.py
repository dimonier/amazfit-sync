from __future__ import annotations

from collections import defaultdict
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from amazfit_sync.models import EndpointProbeResult, NormalizedBundle, RawPayloadRecord


class JsonStorage:
    """Persist runtime artifacts in deterministic JSON files."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.raw_dir = root_dir / "raw"
        self.normalized_dir = root_dir / "normalized"
        self.reports_dir = root_dir / "reports"

    def ensure_dirs(self) -> None:
        for path in (self.root_dir, self.raw_dir, self.normalized_dir, self.reports_dir):
            path.mkdir(parents=True, exist_ok=True)

    def save_raw_payload(self, record: RawPayloadRecord) -> Path:
        safe_host = _slugify(record.host)
        safe_resource = _slugify(record.resource)
        filename = (
            f"{safe_resource}_{safe_host}_{_timestamp_slug(record.fetched_at)}.json"
        )
        target = self.raw_dir / safe_resource / filename
        self._write_json(target, record.to_dict())
        return target

    def save_validation_report(
        self,
        report: dict[str, Any],
        latest_name: str = "latest_validation.json",
    ) -> Path:
        timestamp = _timestamp_slug(_utc_now())
        snapshot = self.reports_dir / f"validation_{timestamp}.json"
        self._write_json(snapshot, report)
        latest = self.reports_dir / latest_name
        self._write_json(latest, report)
        return snapshot

    def save_normalized_bundle(
        self,
        bundle: NormalizedBundle,
    ) -> list[Path]:
        payload = bundle.to_dict()
        period_payloads = self._split_normalized_payloads_by_month(payload)
        written_paths: list[Path] = []
        for period_key, period_payload in sorted(period_payloads.items()):
            target = self._month_bundle_path(period_key)
            self._write_json(target, period_payload)
            written_paths.append(target)
        return written_paths

    def load_normalized_bundle(self, path: Path | None = None) -> dict[str, Any]:
        if path is not None:
            return json.loads(path.read_text(encoding="utf-8"))

        payloads = self._load_period_payloads()
        if not payloads:
            payloads = self._load_legacy_normalized_payloads()
        if not payloads:
            raise FileNotFoundError(f"Normalized bundle not found in {self.normalized_dir.as_posix()}")
        return self._merge_normalized_payloads(payloads)

    def latest_normalized_path(self) -> Path:
        period_paths = self._period_bundle_paths()
        if not period_paths:
            raise FileNotFoundError(f"Normalized bundles not found in {self.normalized_dir.as_posix()}")
        return period_paths[-1]

    def load_raw_payloads(self) -> list[RawPayloadRecord]:
        records: list[RawPayloadRecord] = []
        if not self.raw_dir.exists():
            return records

        for path in sorted(self.raw_dir.glob("**/*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            payload["raw_path"] = payload.get("raw_path") or self._display_path(path)
            records.append(RawPayloadRecord(**payload))
        return records

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def _load_period_payloads(self) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for candidate in self._period_bundle_paths():
            payloads.append(json.loads(candidate.read_text(encoding="utf-8")))
        return payloads

    def _load_legacy_normalized_payloads(self) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        if not self.normalized_dir.exists():
            return payloads

        legacy_paths = sorted(self.normalized_dir.glob("bundle_*.json"))
        latest_path = self.normalized_dir / "latest.json"
        for candidate in [*legacy_paths, latest_path]:
            if not candidate.exists():
                continue
            payloads.append(json.loads(candidate.read_text(encoding="utf-8")))
        return payloads

    def _period_bundle_paths(self) -> list[Path]:
        if not self.normalized_dir.exists():
            return []
        return sorted(path for path in self.normalized_dir.glob("*/*.json") if path.is_file())

    def _month_bundle_path(self, period_key: str) -> Path:
        year = period_key[:4]
        return self.normalized_dir / year / f"{period_key}.json"

    def _display_path(self, path: Path) -> str:
        for base in (self.root_dir.parent, self.root_dir):
            try:
                return path.relative_to(base).as_posix()
            except ValueError:
                continue
        return path.as_posix()

    def _merge_normalized_payloads(self, payloads: list[dict[str, Any]]) -> dict[str, Any]:
        merged_days: dict[str, dict[str, Any]] = {}
        resources: set[str] = set()
        unknown_resources: list[dict[str, Any]] = []
        unknown_signatures: set[str] = set()
        generated_at: str | None = None
        validation_report_path: str | None = None
        fallback_date_range: dict[str, str] | None = None

        for payload in payloads:
            if not isinstance(payload, dict):
                continue

            payload_date_range = payload.get("date_range")
            if isinstance(payload_date_range, dict):
                from_date = payload_date_range.get("from")
                to_date = payload_date_range.get("to")
                if isinstance(from_date, str) and isinstance(to_date, str):
                    fallback_date_range = {"from": from_date, "to": to_date}

            generated_at_value = payload.get("generated_at")
            if isinstance(generated_at_value, str):
                generated_at = generated_at_value

            validation_report_value = payload.get("validation_report_path")
            if isinstance(validation_report_value, str):
                validation_report_path = validation_report_value

            for resource in payload.get("resources", []):
                if isinstance(resource, str):
                    resources.add(resource)

            for item in payload.get("unknown_resources", []):
                if not isinstance(item, dict):
                    continue
                signature = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if signature in unknown_signatures:
                    continue
                unknown_signatures.add(signature)
                unknown_resources.append(item)

            for day in payload.get("days", []):
                if not isinstance(day, dict):
                    continue
                day_date = day.get("date")
                if isinstance(day_date, str):
                    merged_days[day_date] = day

        ordered_dates = sorted(merged_days)
        if ordered_dates:
            date_range = {"from": ordered_dates[0], "to": ordered_dates[-1]}
        else:
            date_range = fallback_date_range or {"from": "", "to": ""}

        return {
            "generated_at": generated_at or _utc_now(),
            "date_range": date_range,
            "resources": sorted(resources),
            "days": [merged_days[day_date] for day_date in ordered_dates],
            "validation_report_path": validation_report_path,
            "unknown_resources": unknown_resources,
        }

    def _split_normalized_payloads_by_month(
        self,
        payload: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        days_by_period: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for day in payload.get("days", []):
            if not isinstance(day, dict):
                continue
            day_date = day.get("date")
            if not isinstance(day_date, str) or len(day_date) < 7:
                continue
            days_by_period[day_date[:7]].append(day)

        period_payloads: dict[str, dict[str, Any]] = {}
        for period_key, days in days_by_period.items():
            ordered_days = sorted(
                (day for day in days if isinstance(day.get("date"), str)),
                key=lambda day: day["date"],
            )
            if not ordered_days:
                continue

            period_payloads[period_key] = {
                "generated_at": payload.get("generated_at") or _utc_now(),
                "period": {"unit": "month", "value": period_key},
                "date_range": {
                    "from": ordered_days[0]["date"],
                    "to": ordered_days[-1]["date"],
                },
                "resources": sorted(
                    resource for resource in payload.get("resources", []) if isinstance(resource, str)
                ),
                "days": ordered_days,
                "validation_report_path": payload.get("validation_report_path"),
                "unknown_resources": [
                    item for item in payload.get("unknown_resources", []) if isinstance(item, dict)
                ],
            }

        return period_payloads


def build_validation_report(
    *,
    from_date: str,
    to_date: str,
    probe_results: list[EndpointProbeResult],
    exchange_status: str,
    exchange_error: str | None = None,
) -> dict[str, Any]:
    return {
        "generated_at": _utc_now(),
        "date_range": {"from": from_date, "to": to_date},
        "exchange_status": exchange_status,
        "exchange_error": exchange_error,
        "probe_results": [result.to_dict() for result in probe_results],
    }


def _timestamp_slug(value: str) -> str:
    sanitized = value.replace(":", "").replace("-", "").replace("T", "_")
    return sanitized.replace("+0000", "Z").replace("+00:00", "Z").replace("Z", "Z")


def _slugify(value: str) -> str:
    return (
        value.lower()
        .replace("https://", "")
        .replace("http://", "")
        .replace("/", "_")
        .replace(".", "_")
        .replace("-", "_")
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

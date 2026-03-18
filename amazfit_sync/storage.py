from __future__ import annotations

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
        latest_name: str = "latest.json",
    ) -> Path:
        timestamp = _timestamp_slug(bundle.generated_at)
        snapshot = self.normalized_dir / f"bundle_{timestamp}.json"
        payload = self._merge_normalized_payloads(
            [
                *self._load_normalized_payloads(),
                bundle.to_dict(),
            ]
        )
        self._write_json(snapshot, payload)
        latest = self.normalized_dir / latest_name
        self._write_json(latest, payload)
        return snapshot

    def load_normalized_bundle(self, path: Path | None = None) -> dict[str, Any]:
        if path is not None:
            return json.loads(path.read_text(encoding="utf-8"))

        payloads = self._load_normalized_payloads()
        if not payloads:
            raise FileNotFoundError(f"Normalized bundle not found in {self.normalized_dir.as_posix()}")

        merged_payload = self._merge_normalized_payloads(payloads)
        latest_path = self.normalized_dir / "latest.json"
        current_latest = payloads[-1] if latest_path.exists() else None
        if current_latest != merged_payload:
            self._write_json(latest_path, merged_payload)
        return merged_payload

    def latest_normalized_path(self) -> Path:
        return self.normalized_dir / "latest.json"

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def _load_normalized_payloads(self) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        if not self.normalized_dir.exists():
            return payloads

        latest_path = self.normalized_dir / "latest.json"
        snapshot_paths = sorted(self.normalized_dir.glob("bundle_*.json"))
        for candidate in [*snapshot_paths, latest_path]:
            if not candidate.exists():
                continue
            payloads.append(json.loads(candidate.read_text(encoding="utf-8")))
        return payloads

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

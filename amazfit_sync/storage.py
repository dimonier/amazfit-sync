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
        payload = bundle.to_dict()
        self._write_json(snapshot, payload)
        latest = self.normalized_dir / latest_name
        self._write_json(latest, payload)
        return snapshot

    def load_normalized_bundle(self, path: Path | None = None) -> dict[str, Any]:
        target = path or (self.normalized_dir / "latest.json")
        return json.loads(target.read_text(encoding="utf-8"))

    def latest_normalized_path(self) -> Path:
        return self.normalized_dir / "latest.json"

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )


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

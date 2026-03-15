from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import json
from typing import Any

from amazfit_sync.amazfit_api import decode_summary_blob
from amazfit_sync.models import DayRecord, NormalizedBundle, RawPayloadRecord


def normalize_records(
    raw_records: list[RawPayloadRecord],
    *,
    from_date: str,
    to_date: str,
    validation_report_path: str | None = None,
) -> NormalizedBundle:
    """Convert raw endpoint responses into a stable day-centric structure."""
    day_map: dict[str, DayRecord] = {}
    unknown_resources: list[dict[str, Any]] = []
    resources_seen: set[str] = set()
    range_start = date.fromisoformat(from_date)
    range_end = date.fromisoformat(to_date)

    for record in raw_records:
        resources_seen.add(record.resource)
        try:
            if record.resource in {"band_summary", "band_detail"}:
                _merge_band_data(day_map, record)
            else:
                handled = _merge_generic_resource(day_map, record)
                if not handled:
                    unknown_resources.append(
                        {
                            "resource": record.resource,
                            "raw_path": record.raw_path,
                            "host": record.host,
                            "endpoint": record.endpoint,
                        }
                    )
        except Exception as exc:  # pragma: no cover - defensive normalization guard
            unknown_resources.append(
                {
                    "resource": record.resource,
                    "raw_path": record.raw_path,
                    "host": record.host,
                    "endpoint": record.endpoint,
                    "error": str(exc),
                }
            )

    days = [
        _dedupe_day(day_map[key])
        for key in sorted(day_map)
        if range_start <= date.fromisoformat(key) <= range_end
    ]
    return NormalizedBundle(
        generated_at=datetime.now(timezone.utc).isoformat(),
        date_range={"from": from_date, "to": to_date},
        resources=sorted(resources_seen),
        days=days,
        validation_report_path=validation_report_path,
        unknown_resources=unknown_resources,
    )


def _merge_band_data(day_map: dict[str, DayRecord], record: RawPayloadRecord) -> None:
    for item in _extract_items(record.payload):
        day = _derive_item_date(item)
        if not day:
            continue
        day_record = _ensure_day(day_map, day)
        _append_source(day_record, record.raw_path)

        encoded_summary = _first_present(item, "summary", "value", "data")
        if isinstance(encoded_summary, str):
            summary_payload = decode_summary_blob(encoded_summary)
        elif isinstance(encoded_summary, dict):
            summary_payload = encoded_summary
        else:
            summary_payload = item

        timezone_offset = summary_payload.get("tz")
        if timezone_offset is not None:
            day_record.daily_summary["timezone_offset_minutes"] = timezone_offset

        goal = summary_payload.get("goal")
        if goal is not None:
            day_record.daily_summary["goal_steps"] = goal

        stp = summary_payload.get("stp") or {}
        if isinstance(stp, dict):
            day_record.daily_summary.update(
                {
                    "steps_total": stp.get("ttl"),
                    "distance_meters": stp.get("dis"),
                    "calories_kcal": stp.get("cal"),
                    "walk_minutes": stp.get("wk"),
                    "run_distance_meters": stp.get("runDist"),
                    "run_calories_kcal": stp.get("runCal"),
                }
            )
            if "stage" in stp:
                day_record.extras.setdefault("step_stages", stp.get("stage") or [])

        slp = summary_payload.get("slp") or {}
        if isinstance(slp, dict):
            day_record.sleep.update(
                {
                    "sleep_start_epoch": slp.get("st"),
                    "sleep_end_epoch": slp.get("ed"),
                    "deep_sleep_minutes": slp.get("dp"),
                    "light_sleep_minutes": slp.get("lt"),
                    "resting_heart_rate": slp.get("rhr"),
                    "stages": slp.get("stage") or [],
                }
            )


def _merge_generic_resource(
    day_map: dict[str, DayRecord],
    record: RawPayloadRecord,
) -> bool:
    grouped_items: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in _extract_items(record.payload):
        if not isinstance(item, dict):
            continue
        day = _derive_item_date(item)
        if not day:
            continue
        grouped_items[day].append(item)

    if not grouped_items:
        return False

    for day, items in grouped_items.items():
        day_record = _ensure_day(day_map, day)
        _append_source(day_record, record.raw_path)
        if "heart" in record.resource:
            day_record.heart_rate.extend(items)
        elif (
            "workout" in record.resource
            or "activity" in record.resource
            or "run" in record.resource
            or "sport" in record.resource
        ):
            day_record.workouts.extend(items)
        elif "body" in record.resource:
            day_record.body_metrics.extend(items)
        elif "sleep" in record.resource:
            day_record.extras.setdefault(record.resource, []).extend(items)
        else:
            day_record.extras.setdefault(record.resource, []).extend(items)
    return True


def _extract_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("summary", "items", "list", "records", "result"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
            return [data]
        if isinstance(data, list):
            return data
        for key in ("data", "list", "items", "records", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return [payload]
    return []


def _derive_item_date(item: dict[str, Any]) -> str | None:
    for key in ("date", "day", "record_date", "recordDate", "summary_date", "date_time"):
        value = item.get(key)
        if isinstance(value, str) and len(value) >= 10:
            return value[:10]

    for key in (
        "start_time",
        "end_time",
        "time",
        "timestamp",
        "created_at",
        "updated_at",
    ):
        value = item.get(key)
        if isinstance(value, str):
            if value.isdigit():
                try:
                    return datetime.fromtimestamp(int(value), tz=timezone.utc).date().isoformat()
                except (OSError, OverflowError, ValueError):
                    continue
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
            except ValueError:
                continue
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat()
            except (OSError, OverflowError, ValueError):
                continue
    return None


def _ensure_day(day_map: dict[str, DayRecord], day: str) -> DayRecord:
    if day not in day_map:
        day_map[day] = DayRecord(date=day)
    return day_map[day]


def _append_source(day_record: DayRecord, raw_path: str | None) -> None:
    if raw_path and raw_path not in day_record.source_payload_ref:
        day_record.source_payload_ref.append(raw_path)


def _first_present(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None


def _dedupe_day(day_record: DayRecord) -> DayRecord:
    day_record.heart_rate = _dedupe_payload_list(day_record.heart_rate)
    day_record.workouts = _dedupe_payload_list(day_record.workouts)
    day_record.body_metrics = _dedupe_payload_list(day_record.body_metrics)
    day_record.source_payload_ref = sorted(set(day_record.source_payload_ref))

    deduped_extras: dict[str, Any] = {}
    for key, value in day_record.extras.items():
        if isinstance(value, list):
            deduped_extras[key] = _dedupe_payload_list(value)
        else:
            deduped_extras[key] = value
    day_record.extras = deduped_extras
    return day_record


def _dedupe_payload_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique_items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        signature = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if signature in seen:
            continue
        seen.add(signature)
        unique_items.append(item)
    return unique_items

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
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
            elif record.resource == "run_detail":
                _merge_run_detail(day_map, record)
            elif record.resource == "weight_records":
                _merge_generic_resource(day_map, record)
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
    _populate_day_metrics(days)
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
            if "stepStageSummary" in stp:
                day_record.extras.setdefault("step_stage_summary", []).extend(
                    stp.get("stepStageSummary") or []
                )

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


def _merge_run_detail(day_map: dict[str, DayRecord], record: RawPayloadRecord) -> None:
    detail = _extract_run_detail_payload(record.payload)
    if not detail:
        return

    day = (
        record.params.get("summary_date")
        or _date_from_value(record.params.get("summary_end_time"))
        or _derive_item_date(detail)
    )
    if not day:
        return

    day_record = _ensure_day(day_map, day)
    _append_source(day_record, record.raw_path)
    day_record.extras.setdefault("run_details", []).append(detail)


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
        elif "body" in record.resource or "weight" in record.resource:
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


def _extract_run_detail_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    detail = dict(data)
    summary_date = payload.get("summary_date")
    if summary_date is not None:
        detail.setdefault("summary_date", summary_date)
    return detail


def _derive_item_date(item: dict[str, Any]) -> str | None:
    for key in (
        "date",
        "day",
        "record_date",
        "recordDate",
        "summary_date",
        "date_time",
        "generatedTime",
        "createTime",
    ):
        value = item.get(key)
        parsed = _date_from_value(value)
        if parsed:
            return parsed

    for key in (
        "start_time",
        "end_time",
        "time",
        "timestamp",
        "created_at",
        "updated_at",
    ):
        parsed = _date_from_value(item.get(key))
        if parsed:
            return parsed
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


def _populate_day_metrics(days: list[DayRecord]) -> None:
    for day_record in days:
        day_record.activity = _build_activity_metrics(
            day_record.daily_summary,
            day_record.extras.get("step_stages", []),
        )
        day_record.recovery = _build_recovery_metrics(day_record.sleep)
        day_record.body = _build_body_metrics(day_record.body_metrics)

    _populate_trends(days)


def _build_activity_metrics(
    daily_summary: dict[str, Any],
    step_stages: Any,
) -> dict[str, Any]:
    steps_total = _coerce_float(daily_summary.get("steps_total"))
    goal_steps = _coerce_float(daily_summary.get("goal_steps"))

    goal_completion_pct = None
    if goal_steps and goal_steps > 0 and steps_total is not None:
        goal_completion_pct = round((steps_total / goal_steps) * 100, 1)

    stages = _normalize_step_stages(step_stages)
    active_stage_minutes = sum(stage["duration_minutes"] for stage in stages) or None
    longest_activity_bout_minutes = max(
        (stage["duration_minutes"] for stage in stages),
        default=None,
    )
    peak_steps_per_minute = max((stage["steps_per_minute"] for stage in stages), default=None)
    if peak_steps_per_minute is not None:
        peak_steps_per_minute = round(peak_steps_per_minute, 1)

    return {
        "goal_completion_pct": goal_completion_pct,
        "activity_bout_count": len(stages),
        "active_stage_minutes": active_stage_minutes,
        "longest_activity_bout_minutes": longest_activity_bout_minutes,
        "peak_steps_per_minute": peak_steps_per_minute,
        "peak_activity_hour": _build_peak_activity_hour(stages),
    }


def _build_recovery_metrics(sleep: dict[str, Any]) -> dict[str, Any]:
    deep_sleep_minutes = _coerce_int(sleep.get("deep_sleep_minutes"))
    light_sleep_minutes = _coerce_int(sleep.get("light_sleep_minutes"))
    sleep_minutes = None
    if deep_sleep_minutes is not None or light_sleep_minutes is not None:
        sleep_minutes = int(deep_sleep_minutes or 0) + int(light_sleep_minutes or 0)

    sleep_start_epoch = _coerce_int(sleep.get("sleep_start_epoch"))
    sleep_end_epoch = _coerce_int(sleep.get("sleep_end_epoch"))
    time_in_bed_minutes = None
    if (
        sleep_start_epoch is not None
        and sleep_end_epoch is not None
        and sleep_end_epoch >= sleep_start_epoch
    ):
        time_in_bed_minutes = int((sleep_end_epoch - sleep_start_epoch) / 60)

    return {
        "sleep_minutes": sleep_minutes,
        "time_in_bed_minutes": time_in_bed_minutes,
        "resting_heart_rate": _coerce_int(sleep.get("resting_heart_rate")),
    }


def _build_body_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {}

    latest_item = max(items, key=_body_metric_sort_key)
    summary = latest_item.get("summary")
    if not isinstance(summary, dict):
        summary = latest_item

    weight_kg = _coerce_float(summary.get("weight"))
    if weight_kg is None:
        weight_grams = _coerce_float(summary.get("weight_grams"))
        if weight_grams is not None:
            weight_kg = weight_grams / 1000.0

    return {
        "measured_at": _datetime_from_value(
            _first_present(latest_item, "generatedTime", "createTime", "timestamp", "time")
        ),
        "weight_kg": _round_float(weight_kg, digits=1),
        "bmi": _round_float(_coerce_float(summary.get("bmi")), digits=1),
        "body_fat_pct": _round_float(_coerce_float(summary.get("fatRate")), digits=1),
        "body_water_pct": _round_float(_coerce_float(summary.get("bodyWaterRate")), digits=1),
        "bone_mass_kg": _round_float(_coerce_float(summary.get("boneMass")), digits=2),
        "muscle_pct": _round_float(_coerce_float(summary.get("muscleRate")), digits=1),
        "protein_pct": _round_float(_coerce_float(summary.get("proteinRatio")), digits=1),
        "metabolism_kcal": _coerce_int(summary.get("metabolism")),
        "visceral_fat": _round_float(_coerce_float(summary.get("visceralFat")), digits=1),
        "body_score": _coerce_int(summary.get("bodyScore")),
        "source": _coerce_int(summary.get("source")),
        "data_source_type": _coerce_int(summary.get("dataSourceType")),
        "device_source": _coerce_int(latest_item.get("deviceSource")),
    }


def _body_metric_sort_key(item: dict[str, Any]) -> tuple[int, int]:
    generated_at = _timestamp_to_epoch(item.get("generatedTime"))
    created_at = _timestamp_to_epoch(item.get("createTime"))
    return (
        generated_at or created_at or 0,
        created_at or generated_at or 0,
    )


def _populate_trends(days: list[DayRecord]) -> None:
    dated_days = [(date.fromisoformat(day_record.date), day_record) for day_record in days]

    for idx, (current_date, day_record) in enumerate(dated_days):
        window_start = current_date - timedelta(days=14)
        prior_days = [
            previous
            for previous_date, previous in dated_days[:idx]
            if previous_date >= window_start
        ]

        steps_avg = _average(
            _coerce_float(previous.daily_summary.get("steps_total")) for previous in prior_days
        )
        sleep_avg = _average(
            _coerce_float(previous.recovery.get("sleep_minutes")) for previous in prior_days
        )
        resting_hr_avg = _average(
            _coerce_float(previous.recovery.get("resting_heart_rate")) for previous in prior_days
        )
        weight_avg = _average(_coerce_float(previous.body.get("weight_kg")) for previous in prior_days)
        goal_hit_rate = _goal_hit_rate(prior_days)

        current_rhr = _coerce_float(day_record.recovery.get("resting_heart_rate"))
        resting_hr_delta = None
        if current_rhr is not None and resting_hr_avg is not None:
            resting_hr_delta = round(current_rhr - resting_hr_avg, 1)

        current_weight = _coerce_float(day_record.body.get("weight_kg"))
        weight_delta = None
        if current_weight is not None and weight_avg is not None:
            weight_delta = round(current_weight - weight_avg, 1)

        day_record.trends = {
            "window_days_14d": len(prior_days),
            "steps_rolling_avg_14d": steps_avg,
            "sleep_minutes_rolling_avg_14d": sleep_avg,
            "resting_hr_rolling_avg_14d": resting_hr_avg,
            "weight_rolling_avg_14d": weight_avg,
            "goal_hit_rate_14d": goal_hit_rate,
            "resting_hr_delta_14d": resting_hr_delta,
            "weight_delta_14d": weight_delta,
        }


def _normalize_step_stages(step_stages: Any) -> list[dict[str, float | int]]:
    if not isinstance(step_stages, list):
        return []

    normalized: list[dict[str, float | int]] = []
    for stage in step_stages:
        if not isinstance(stage, dict):
            continue

        start = _coerce_int(stage.get("start"))
        stop = _coerce_int(stage.get("stop"))
        steps = _coerce_int(stage.get("step"))
        if start is None or stop is None or steps is None:
            continue

        stage_start = max(0, min(start, 1439))
        stage_stop = max(stage_start + 1, min(stop, 1440))
        duration = max(stage_stop - stage_start, 1)
        normalized.append(
            {
                "start": stage_start,
                "stop": stage_stop,
                "steps": steps,
                "duration_minutes": duration,
                "steps_per_minute": steps / duration,
            }
        )
    return normalized


def _build_peak_activity_hour(stages: list[dict[str, float | int]]) -> str | None:
    if not stages:
        return None

    hourly_totals = [0.0] * 24
    for stage in stages:
        start = int(stage["start"])
        stop = int(stage["stop"])
        steps_per_minute = float(stage["steps_per_minute"])
        for minute in range(start, stop):
            hourly_totals[minute // 60] += steps_per_minute

    peak_hour = max(range(24), key=lambda hour: hourly_totals[hour], default=None)
    if peak_hour is None or hourly_totals[peak_hour] <= 0:
        return None
    return f"{peak_hour:02d}:00"


def _goal_hit_rate(days: list[DayRecord]) -> float | None:
    values = [
        activity_value
        for day_record in days
        if (activity_value := _coerce_float(day_record.activity.get("goal_completion_pct"))) is not None
    ]
    if not values:
        return None
    hits = sum(1 for value in values if value >= 100.0)
    return round((hits / len(values)) * 100, 1)


def _average(values: Any) -> float | None:
    numeric_values = [float(value) for value in values if value is not None]
    if not numeric_values:
        return None
    return round(sum(numeric_values) / len(numeric_values), 1)


def _date_from_value(value: Any) -> str | None:
    if isinstance(value, str):
        if len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-":
            return value[:10]
        if value.isdigit():
            try:
                return datetime.fromtimestamp(int(value), tz=timezone.utc).date().isoformat()
            except (OSError, OverflowError, ValueError):
                return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            return None

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat()
        except (OSError, OverflowError, ValueError):
            return None
    return None


def _datetime_from_value(value: Any) -> str | None:
    if isinstance(value, str):
        if value.isdigit():
            try:
                return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
            except (OSError, OverflowError, ValueError):
                return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        except ValueError:
            return None

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        except (OSError, OverflowError, ValueError):
            return None
    return None


def _timestamp_to_epoch(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _round_float(value: float | None, *, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

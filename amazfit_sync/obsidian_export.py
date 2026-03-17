from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def export_bundle_to_obsidian(bundle: dict[str, Any], output_dir: Path) -> list[Path]:
    """Write curated markdown files for yesterday and recent missing backfill days."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []
    yesterday = date.today() - timedelta(days=1)
    backfill_start = yesterday - timedelta(days=14)
    prepared_days = _prepare_days_for_export(bundle.get("days", []))

    for day in prepared_days:
        day_date = date.fromisoformat(day["date"])
        target = output_dir / f"{day['date']}-physical.md"
        legacy_target = output_dir / f"{day['date']}.md"

        if day_date == yesterday:
            _write_day_markdown(target, day)
            written_paths.append(target)
            if legacy_target.exists():
                legacy_target.unlink()
            continue

        if not (backfill_start <= day_date < yesterday):
            continue
        if target.exists() or legacy_target.exists():
            continue

        _write_day_markdown(target, day)
        written_paths.append(target)

    return written_paths


def _render_day_markdown(day: dict[str, Any]) -> str:
    daily_summary = day.get("daily_summary", {})
    sleep = day.get("sleep", {})
    activity = day.get("activity", {})
    recovery = day.get("recovery", {})
    trends = day.get("trends", {})
    extras = day.get("extras", {})
    timezone_offset = _coerce_int(daily_summary.get("timezone_offset_minutes")) or 0
    sleep_window = _build_sleep_window(sleep, timezone_offset)
    hourly_steps = _build_hourly_steps(
        extras.get("step_stage_summary", []),
        extras.get("step_stages", []),
    )

    frontmatter = _build_frontmatter(day, daily_summary, activity, recovery)
    lines = frontmatter + [
        f"# {day['date']} physical activity report based on Amazfit smart watch",
        "",
        "## Trends (14d)",
    ]

    if _has_trend_data(trends):
        current_steps = _coerce_number(daily_summary.get("steps_total"))
        steps_baseline = _coerce_number(trends.get("steps_rolling_avg_14d"))
        current_sleep_minutes = _coerce_int(recovery.get("sleep_minutes"))
        sleep_baseline_minutes = _coerce_number(trends.get("sleep_minutes_rolling_avg_14d"))
        current_resting_hr = _coerce_number(recovery.get("resting_heart_rate"))
        resting_hr_baseline = _coerce_number(trends.get("resting_hr_rolling_avg_14d"))

        lines.extend(
            [
                (
                    "- Steps: "
                    f"baseline {_format_plain_number(steps_baseline)} | "
                    f"today {_display_number(current_steps)} "
                    f"({_format_signed_plain_delta(current_steps, steps_baseline)})"
                ),
                (
                    "- Sleep: "
                    f"baseline {_format_duration_value(sleep_baseline_minutes)} | "
                    f"today {_format_duration_value(current_sleep_minutes)} "
                    f"({_format_signed_duration_delta(current_sleep_minutes, sleep_baseline_minutes)})"
                ),
                (
                    "- Resting HR: "
                    f"baseline {_format_plain_number(resting_hr_baseline)} | "
                    f"today {_format_plain_number(current_resting_hr)} "
                    f"({_format_signed_plain_delta(current_resting_hr, resting_hr_baseline)})"
                ),
                "",
            ]
        )
    else:
        lines.extend(["- Not enough prior days for 14-day trends.", ""])

    lines.extend(
        [
        "## Steps",
        f"- Steps: {_display_number(daily_summary.get('steps_total'))}",
        f"- Distance: {_format_measurement(daily_summary.get('distance_meters'), 'm')}",
        f"- Walk minutes: {_format_measurement(daily_summary.get('walk_minutes'), 'min')}",
        "",
        "## Steps By Hour",
        "Hour and steps done within the hour",
        ]
    )

    if hourly_steps:
        lines.extend([f"- {hour}: {steps}" for hour, steps in hourly_steps.items()])
    else:
        lines.append("- No hourly step distribution available.")

    lines.extend(
        [
            "",
            "## Activity",
        f"- Calories: {_format_measurement(daily_summary.get('calories_kcal'), 'kcal')}",
        f"- Run distance: {_format_measurement(daily_summary.get('run_distance_meters'), 'm')}",
        f"- Activity bouts: {_display_number(activity.get('activity_bout_count'))}",
        f"- Active stage minutes: {_format_measurement(activity.get('active_stage_minutes'), 'min')}",
        f"- Longest activity bout: {_format_measurement(activity.get('longest_activity_bout_minutes'), 'min')}",
        f"- Peak activity hour: {_display_value(activity.get('peak_activity_hour'))}",
        f"- Peak steps per minute: {_format_measurement(activity.get('peak_steps_per_minute'), 'steps/min')}",
        "",
        "## Sleep",
        f"- Sleep start: {_display_value(sleep_window.get('start'))}",
        f"- Sleep end: {_display_value(sleep_window.get('end'))}",
        f"- Time in bed: {_display_value(sleep_window.get('time_in_bed'))}",
        f"- Total sleep: {_format_duration_value(recovery.get('sleep_minutes'))}",
        f"- Deep sleep: {_format_duration_value(sleep.get('deep_sleep_minutes'))}",
        f"- Light sleep: {_format_duration_value(sleep.get('light_sleep_minutes'))}",
        f"- Resting heart rate: {_format_measurement(recovery.get('resting_heart_rate'), 'bpm')}",
        ]
    )

    lines.append("")
    return "\n".join(lines)


def _write_day_markdown(target: Path, day: dict[str, Any]) -> None:
    target.write_text(_render_day_markdown(day), encoding="utf-8")


def _prepare_days_for_export(days: Any) -> list[dict[str, Any]]:
    if not isinstance(days, list):
        return []

    prepared_days: list[dict[str, Any]] = []
    for source_day in days:
        if not isinstance(source_day, dict):
            continue

        day = dict(source_day)
        day["daily_summary"] = dict(source_day.get("daily_summary", {}))
        day["sleep"] = dict(source_day.get("sleep", {}))
        day["extras"] = dict(source_day.get("extras", {}))
        day["activity"] = dict(source_day.get("activity") or _fallback_activity(day))
        day["recovery"] = dict(source_day.get("recovery") or _fallback_recovery(day))
        day["trends"] = dict(source_day.get("trends") or {})
        prepared_days.append(day)

    _populate_missing_trends(prepared_days)
    return prepared_days


def _build_frontmatter(
    day: dict[str, Any],
    daily_summary: dict[str, Any],
    activity: dict[str, Any],
    recovery: dict[str, Any],
) -> list[str]:
    payload = {
        "date": day["date"],
        "steps_total": _coerce_int(daily_summary.get("steps_total")),
        "distance_meters": _coerce_int(daily_summary.get("distance_meters")),
        "calories_kcal": _coerce_int(daily_summary.get("calories_kcal")),
        "walk_minutes": _coerce_int(daily_summary.get("walk_minutes")),
        "run_distance_meters": _coerce_int(daily_summary.get("run_distance_meters")),
        "sleep_minutes": _coerce_int(recovery.get("sleep_minutes")),
        "time_in_bed_minutes": _coerce_int(recovery.get("time_in_bed_minutes")),
        "resting_heart_rate": _coerce_int(recovery.get("resting_heart_rate")),
        "activity_bout_count": _coerce_int(activity.get("activity_bout_count")),
        "active_stage_minutes": _coerce_int(activity.get("active_stage_minutes")),
        "longest_activity_bout_minutes": _coerce_int(activity.get("longest_activity_bout_minutes")),
        "peak_activity_hour": activity.get("peak_activity_hour"),
        "peak_steps_per_minute": _coerce_number(activity.get("peak_steps_per_minute")),
    }
    lines = ["---"]
    for key, value in payload.items():
        if value is None:
            continue
        lines.append(f"{key}: {_yaml_value(value)}")
    lines.extend(["---", ""])
    return lines


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_number(value: Any) -> int | float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number.is_integer():
        return int(number)
    return round(number, 1)


def _build_sleep_window(sleep: dict[str, Any], timezone_offset_minutes: int) -> dict[str, str | None]:
    timezone_offset_minutes = _normalize_timezone_offset_minutes(timezone_offset_minutes)
    start_epoch = _coerce_int(sleep.get("sleep_start_epoch"))
    end_epoch = _coerce_int(sleep.get("sleep_end_epoch"))

    time_in_bed_minutes = None
    if start_epoch is not None and end_epoch is not None and end_epoch >= start_epoch:
        time_in_bed_minutes = int((end_epoch - start_epoch) / 60)

    return {
        "start": _format_epoch(start_epoch, timezone_offset_minutes),
        "end": _format_epoch(end_epoch, timezone_offset_minutes),
        "time_in_bed": _format_minutes(time_in_bed_minutes),
    }


def _format_epoch(epoch_seconds: int | None, timezone_offset_minutes: int) -> str | None:
    if epoch_seconds is None:
        return None
    tz = timezone(timedelta(minutes=timezone_offset_minutes))
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).astimezone(tz).strftime(
        "%Y-%m-%d %H:%M"
    )


def _format_minutes(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    hours, remainder = divmod(minutes, 60)
    return f"{hours:02d}:{remainder:02d}"


def _display_number(value: Any) -> str:
    coerced = _coerce_number(value)
    return "n/a" if coerced is None else str(coerced)


def _display_value(value: Any) -> str:
    return "n/a" if value is None else str(value)


def _format_measurement(value: Any, unit: str) -> str:
    coerced = _coerce_number(value)
    if coerced is None:
        return "n/a"
    return f"{coerced} {unit}"


def _format_duration_value(value: Any) -> str:
    minutes = _coerce_int(value)
    if minutes is None:
        number = _coerce_number(value)
        if number is None:
            return "n/a"
        minutes = int(round(float(number)))
    return _format_minutes_compact(minutes)


def _format_signed_measurement(value: Any, unit: str) -> str:
    coerced = _coerce_number(value)
    if coerced is None:
        return "n/a"
    if isinstance(coerced, float) and coerced.is_integer():
        coerced = int(coerced)
    prefix = "+" if coerced > 0 else ""
    return f"{prefix}{coerced} {unit}"


def _format_percent(value: Any) -> str:
    coerced = _coerce_number(value)
    if coerced is None:
        return "n/a"
    return f"{coerced}%"


def _format_plain_number(value: Any) -> str:
    coerced = _coerce_number(value)
    if coerced is None:
        return "n/a"
    return str(coerced)


def _format_signed_delta(current: Any, baseline: Any, unit: str) -> str:
    current_number = _coerce_number(current)
    baseline_number = _coerce_number(baseline)
    if current_number is None or baseline_number is None:
        return "n/a"
    return _format_signed_measurement(float(current_number) - float(baseline_number), unit)


def _format_signed_plain_delta(current: Any, baseline: Any) -> str:
    current_number = _coerce_number(current)
    baseline_number = _coerce_number(baseline)
    if current_number is None or baseline_number is None:
        return "n/a"

    delta = float(current_number) - float(baseline_number)
    if delta.is_integer():
        delta_text = str(int(delta))
    else:
        delta_text = str(round(delta, 1))
    if delta > 0:
        return f"+{delta_text}"
    return delta_text


def _format_signed_duration_delta(current: Any, baseline: Any) -> str:
    current_minutes = _coerce_number(current)
    baseline_minutes = _coerce_number(baseline)
    if current_minutes is None or baseline_minutes is None:
        return "n/a"

    delta_minutes = int(round(float(current_minutes) - float(baseline_minutes)))
    prefix = "+" if delta_minutes > 0 else ""
    return f"{prefix}{_format_minutes_compact(delta_minutes)}"


def _has_trend_data(trends: dict[str, Any]) -> bool:
    return any(
        trends.get(key) is not None
        for key in (
            "steps_rolling_avg_14d",
            "sleep_minutes_rolling_avg_14d",
            "resting_hr_rolling_avg_14d",
            "goal_hit_rate_14d",
            "resting_hr_delta_14d",
        )
    )


def _yaml_value(value: Any) -> str:
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def _fallback_activity(day: dict[str, Any]) -> dict[str, Any]:
    daily_summary = day.get("daily_summary", {})
    steps_total = _coerce_number(daily_summary.get("steps_total"))
    goal_steps = _coerce_number(daily_summary.get("goal_steps"))
    goal_completion_pct = None
    if goal_steps and goal_steps > 0 and steps_total is not None:
        goal_completion_pct = round((float(steps_total) / float(goal_steps)) * 100, 1)

    stages = _normalize_step_stages(day.get("extras", {}).get("step_stages", []))
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
        "peak_activity_hour": _peak_activity_hour(stages),
        "peak_steps_per_minute": peak_steps_per_minute,
    }


def _fallback_recovery(day: dict[str, Any]) -> dict[str, Any]:
    sleep = day.get("sleep", {})
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


def _populate_missing_trends(days: list[dict[str, Any]]) -> None:
    dated_days = [(date.fromisoformat(day["date"]), day) for day in days]
    for idx, (current_date, day) in enumerate(dated_days):
        if _has_trend_data(day.get("trends", {})):
            continue

        window_start = current_date - timedelta(days=14)
        prior_days = [
            previous
            for previous_date, previous in dated_days[:idx]
            if previous_date >= window_start
        ]

        steps_avg = _average(
            _coerce_number(previous.get("daily_summary", {}).get("steps_total")) for previous in prior_days
        )
        sleep_avg = _average(
            _coerce_number(previous.get("recovery", {}).get("sleep_minutes")) for previous in prior_days
        )
        resting_hr_avg = _average(
            _coerce_number(previous.get("recovery", {}).get("resting_heart_rate")) for previous in prior_days
        )
        goal_hit_rate = _goal_hit_rate(prior_days)
        current_rhr = _coerce_number(day.get("recovery", {}).get("resting_heart_rate"))
        resting_hr_delta = None
        if current_rhr is not None and resting_hr_avg is not None:
            resting_hr_delta = round(float(current_rhr) - float(resting_hr_avg), 1)

        day["trends"] = {
            "window_days_14d": len(prior_days),
            "steps_rolling_avg_14d": steps_avg,
            "sleep_minutes_rolling_avg_14d": sleep_avg,
            "resting_hr_rolling_avg_14d": resting_hr_avg,
            "goal_hit_rate_14d": goal_hit_rate,
            "resting_hr_delta_14d": resting_hr_delta,
        }


def _normalize_step_stages(step_stages: Any) -> list[dict[str, float | int]]:
    if not isinstance(step_stages, list):
        return []

    stages: list[dict[str, float | int]] = []
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
        stages.append(
            {
                "start": stage_start,
                "stop": stage_stop,
                "duration_minutes": duration,
                "steps_per_minute": steps / duration,
            }
        )
    return stages


def _peak_activity_hour(stages: list[dict[str, float | int]]) -> str | None:
    if not stages:
        return None

    hourly_totals = [0.0] * 24
    for stage in stages:
        for minute in range(int(stage["start"]), int(stage["stop"])):
            hourly_totals[minute // 60] += float(stage["steps_per_minute"])

    peak_hour = max(range(24), key=lambda hour: hourly_totals[hour], default=None)
    if peak_hour is None or hourly_totals[peak_hour] <= 0:
        return None
    return f"{peak_hour:02d}:00"


def _goal_hit_rate(days: list[dict[str, Any]]) -> float | None:
    values = [
        value
        for day in days
        if (value := _coerce_number(day.get("activity", {}).get("goal_completion_pct"))) is not None
    ]
    if not values:
        return None
    hits = sum(1 for value in values if float(value) >= 100.0)
    return round((hits / len(values)) * 100, 1)


def _average(values: Any) -> float | None:
    numeric_values = [float(value) for value in values if value is not None]
    if not numeric_values:
        return None
    return round(sum(numeric_values) / len(numeric_values), 1)


def _build_hourly_steps(step_stage_summary: Any, step_stages: Any) -> dict[int, int]:
    hourly_from_summary = _build_hourly_steps_from_summary(step_stage_summary)
    if hourly_from_summary:
        return hourly_from_summary
    return _build_hourly_steps_from_stages(step_stages)


def _build_hourly_steps_from_summary(step_stage_summary: Any) -> dict[int, int]:
    if not isinstance(step_stage_summary, list):
        return {}

    hourly_totals: dict[int, int] = {}
    for bucket in step_stage_summary:
        if not isinstance(bucket, dict):
            continue

        time_bucket = _coerce_int(bucket.get("time"))
        steps = _coerce_int(bucket.get("step"))
        if time_bucket is None or steps is None:
            continue

        if not 0 <= time_bucket < 24 * 6:
            continue

        hour = time_bucket // 6
        hourly_totals[hour] = hourly_totals.get(hour, 0) + steps

    return {hour: total for hour, total in sorted(hourly_totals.items()) if total > 0}


def _build_hourly_steps_from_stages(step_stages: Any) -> dict[int, int]:
    if not isinstance(step_stages, list):
        return {}

    minute_totals = [0.0] * 1440
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
        steps_per_minute = steps / duration
        for minute in range(stage_start, stage_stop):
            minute_totals[minute] += steps_per_minute

    hourly_totals: dict[int, int] = {}
    for hour in range(24):
        start_idx = hour * 60
        total = round(sum(minute_totals[start_idx : start_idx + 60]))
        if total > 0:
            hourly_totals[hour] = total
    return hourly_totals


def _normalize_timezone_offset_minutes(value: int) -> int:
    if abs(value) >= 24 * 60:
        return int(value / 60)
    return value


def _format_minutes_compact(minutes: int) -> str:
    sign = "-" if minutes < 0 else ""
    absolute_minutes = abs(minutes)
    hours, remainder = divmod(absolute_minutes, 60)
    return f"{sign}{hours:02d}:{remainder:02d}"

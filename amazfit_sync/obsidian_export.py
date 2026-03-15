from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def export_bundle_to_obsidian(bundle: dict[str, Any], output_dir: Path) -> list[Path]:
    """Write one deterministic markdown file per normalized day."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []

    for day in bundle.get("days", []):
        date = day["date"]
        target = output_dir / f"{date}-physical.md"
        target.write_text(_render_day_markdown(day), encoding="utf-8")
        written_paths.append(target)

        legacy_target = output_dir / f"{date}.md"
        if legacy_target.exists():
            legacy_target.unlink()

    index_path = output_dir / "index.md"
    if index_path.exists():
        index_path.unlink()
    return written_paths


def _render_day_markdown(day: dict[str, Any]) -> str:
    daily_summary = day.get("daily_summary", {})
    sleep = day.get("sleep", {})
    workouts = day.get("workouts", [])
    body_metrics = day.get("body_metrics", [])
    heart_rate = day.get("heart_rate", [])
    extras = day.get("extras", {})
    timezone_offset = _coerce_int(daily_summary.get("timezone_offset_minutes")) or 0
    sleep_metrics = _build_sleep_metrics(sleep, timezone_offset)
    hourly_steps = _build_hourly_steps(extras.get("step_stages", []))
    lines = [
        f"# Amazfit {day['date']}",
        "",
        "## Summary",
        f"- Steps: {_display(daily_summary.get('steps_total'))}",
        f"- Active walking minutes: {_display(daily_summary.get('walk_minutes'))}",
        "",
        "## Sleep",
        f"- Sleep start: {_display(sleep_metrics.get('start'))}",
        f"- Sleep end: {_display(sleep_metrics.get('end'))}",
        f"- Time in bed: {_display(sleep_metrics.get('time_in_bed'))}",
        f"- Total asleep minutes: {_display(sleep_metrics.get('asleep_minutes'))}",
        f"- Deep sleep minutes: {_display(sleep.get('deep_sleep_minutes'))}",
        f"- Light sleep minutes: {_display(sleep.get('light_sleep_minutes'))}",
        f"- Awake/restless minutes: {_display(sleep_metrics.get('awake_minutes'))}",
        f"- Sleep efficiency: {_display(sleep_metrics.get('efficiency'))}",
        f"- Resting heart rate: {_display(sleep.get('resting_heart_rate'))}",
        "",
        "## Steps By Hour",
    ]

    if hourly_steps:
        lines.extend(_render_hourly_step_lines(hourly_steps))
    else:
        lines.extend(["- No hourly step distribution available.", ""])

    if heart_rate:
        lines.extend(
            [
                "",
                "## Heart Rate",
                f"- Samples: {len(heart_rate)}",
                "```json",
                json.dumps(heart_rate[:20], indent=2, ensure_ascii=False),
                "```",
            ]
        )

    if workouts:
        lines.extend(
            [
                "",
                "## Workouts",
                "```json",
                json.dumps(workouts[:20], indent=2, ensure_ascii=False),
                "```",
            ]
        )

    if body_metrics:
        lines.extend(
            [
                "",
                "## Body Metrics",
                "```json",
                json.dumps(body_metrics[:20], indent=2, ensure_ascii=False),
                "```",
            ]
        )

    lines.append("")
    return "\n".join(lines)


def _sum_sleep_minutes(sleep: dict[str, Any]) -> int | None:
    deep = sleep.get("deep_sleep_minutes")
    light = sleep.get("light_sleep_minutes")
    if deep is None and light is None:
        return None
    return int(deep or 0) + int(light or 0)


def _display(value: Any) -> str:
    return "n/a" if value is None else str(value)


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_sleep_metrics(sleep: dict[str, Any], timezone_offset_minutes: int) -> dict[str, str | int | None]:
    timezone_offset_minutes = _normalize_timezone_offset_minutes(timezone_offset_minutes)
    start_epoch = _coerce_int(sleep.get("sleep_start_epoch"))
    end_epoch = _coerce_int(sleep.get("sleep_end_epoch"))
    asleep_minutes = _sum_sleep_minutes(sleep)
    stage_minutes = _sum_stage_minutes(sleep.get("stages", []))
    awake_minutes = None
    if stage_minutes is not None and asleep_minutes is not None:
        awake_minutes = max(stage_minutes - asleep_minutes, 0)

    time_in_bed_minutes = None
    if start_epoch is not None and end_epoch is not None and end_epoch >= start_epoch:
        time_in_bed_minutes = int((end_epoch - start_epoch) / 60)

    efficiency = None
    if asleep_minutes is not None and time_in_bed_minutes:
        efficiency = f"{(asleep_minutes / time_in_bed_minutes) * 100:.1f}%"

    return {
        "start": _format_epoch(start_epoch, timezone_offset_minutes),
        "end": _format_epoch(end_epoch, timezone_offset_minutes),
        "time_in_bed": _format_minutes(time_in_bed_minutes),
        "asleep_minutes": asleep_minutes,
        "awake_minutes": awake_minutes,
        "efficiency": efficiency,
    }


def _sum_stage_minutes(stages: Any) -> int | None:
    if not isinstance(stages, list) or not stages:
        return None
    total = 0
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        start = _coerce_int(stage.get("start"))
        stop = _coerce_int(stage.get("stop"))
        if start is None or stop is None:
            continue
        total += max(stop - start, 0)
    return total


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


def _build_hourly_steps(step_stages: Any) -> dict[str, int]:
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

    hourly: dict[str, int] = {}
    for hour in range(24):
        label = f"{hour:02d}:00-{hour:02d}:59"
        start_idx = hour * 60
        hourly[label] = round(sum(minute_totals[start_idx : start_idx + 60]))

    return {label: steps for label, steps in hourly.items() if steps > 0}


def _render_hourly_step_lines(hourly_steps: dict[str, int]) -> list[str]:
    return [f"- {label}: {steps}" for label, steps in hourly_steps.items()]


def _normalize_timezone_offset_minutes(value: int) -> int:
    if abs(value) >= 24 * 60:
        return int(value / 60)
    return value

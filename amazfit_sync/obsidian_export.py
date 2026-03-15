from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def export_bundle_to_obsidian(bundle: dict[str, Any], output_dir: Path) -> list[Path]:
    """Write one deterministic markdown file per normalized day."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []

    for day in bundle.get("days", []):
        date = day["date"]
        target = output_dir / f"{date}.md"
        target.write_text(_render_day_markdown(day), encoding="utf-8")
        written_paths.append(target)

    index_path = output_dir / "index.md"
    index_path.write_text(_render_index(bundle), encoding="utf-8")
    written_paths.append(index_path)
    return written_paths


def _render_day_markdown(day: dict[str, Any]) -> str:
    daily_summary = day.get("daily_summary", {})
    sleep = day.get("sleep", {})
    workouts = day.get("workouts", [])
    body_metrics = day.get("body_metrics", [])
    heart_rate = day.get("heart_rate", [])
    extras = day.get("extras", {})
    sources = day.get("source_payload_ref", [])

    frontmatter = {
        "date": day["date"],
        "source": "amazfit-sync",
        "steps_total": daily_summary.get("steps_total"),
        "distance_meters": daily_summary.get("distance_meters"),
        "sleep_total_minutes": _sum_sleep_minutes(sleep),
        "workouts_count": len(workouts),
    }
    yaml_lines = ["---"]
    for key, value in frontmatter.items():
        yaml_lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    yaml_lines.append("---")

    lines = [
        *yaml_lines,
        "",
        f"# Amazfit {day['date']}",
        "",
        "## Summary",
        f"- Steps: {_display(daily_summary.get('steps_total'))}",
        f"- Goal steps: {_display(daily_summary.get('goal_steps'))}",
        f"- Distance meters: {_display(daily_summary.get('distance_meters'))}",
        f"- Calories kcal: {_display(daily_summary.get('calories_kcal'))}",
        "",
        "## Sleep",
        f"- Total minutes: {_display(_sum_sleep_minutes(sleep))}",
        f"- Deep minutes: {_display(sleep.get('deep_sleep_minutes'))}",
        f"- Light minutes: {_display(sleep.get('light_sleep_minutes'))}",
        f"- Resting heart rate: {_display(sleep.get('resting_heart_rate'))}",
    ]

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

    if extras:
        lines.extend(
            [
                "",
                "## Extras",
                "```json",
                json.dumps(extras, indent=2, ensure_ascii=False),
                "```",
            ]
        )

    if sources:
        lines.extend(["", "## Source Payloads"])
        for source in sources:
            lines.append(f"- {source}")

    lines.append("")
    return "\n".join(lines)


def _render_index(bundle: dict[str, Any]) -> str:
    lines = [
        "# Amazfit Export Index",
        "",
        f"- Generated at: {_display(bundle.get('generated_at'))}",
        f"- Date range: {_display(bundle.get('date_range', {}).get('from'))} -> "
        f"{_display(bundle.get('date_range', {}).get('to'))}",
        f"- Resources: {', '.join(bundle.get('resources', [])) or 'n/a'}",
        "",
        "## Days",
    ]
    for day in bundle.get("days", []):
        lines.append(
            f"- [[{day['date']}]]: steps={_display(day.get('daily_summary', {}).get('steps_total'))}"
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

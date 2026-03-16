from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class RawPayloadRecord:
    resource: str
    host: str
    endpoint: str
    params: dict[str, Any]
    fetched_at: str
    http_status: int
    payload: Any
    raw_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EndpointProbeResult:
    resource: str
    host: str
    endpoint: str
    ok: bool
    http_status: int | None
    error: str | None = None
    raw_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DayRecord:
    date: str
    daily_summary: dict[str, Any] = field(default_factory=dict)
    sleep: dict[str, Any] = field(default_factory=dict)
    activity: dict[str, Any] = field(default_factory=dict)
    recovery: dict[str, Any] = field(default_factory=dict)
    trends: dict[str, Any] = field(default_factory=dict)
    heart_rate: list[dict[str, Any]] = field(default_factory=list)
    workouts: list[dict[str, Any]] = field(default_factory=list)
    body_metrics: list[dict[str, Any]] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)
    source_payload_ref: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class NormalizedBundle:
    generated_at: str
    date_range: dict[str, str]
    resources: list[str]
    days: list[DayRecord]
    validation_report_path: str | None = None
    unknown_resources: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["days"] = [day.to_dict() for day in self.days]
        return payload

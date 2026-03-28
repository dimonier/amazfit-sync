from __future__ import annotations

import json
import uuid
from base64 import b64decode
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable

import requests

from amazfit_sync.auth_state import AuthStateStore
from amazfit_sync.config import AppConfig, DEFAULT_DEVICE_ID, mask_secret
from amazfit_sync.models import EndpointProbeResult, RawPayloadRecord


@dataclass(slots=True)
class EndpointCandidate:
    resource: str
    endpoint: str
    params: dict[str, Any] = field(default_factory=dict)


DEFAULT_ENDPOINTS = (
    EndpointCandidate(
        resource="band_summary",
        endpoint="/v1/data/band_data.json",
        params={"query_type": "summary", "device_type": "android_phone"},
    ),
    EndpointCandidate(
        resource="band_detail",
        endpoint="/v1/data/band_data.json",
        params={"query_type": "detail", "device_type": "android_phone"},
    ),
    EndpointCandidate(
        resource="sleep_data",
        endpoint="/v1/data/sleep_data.json",
        params={"device_type": "android_phone"},
    ),
    EndpointCandidate(
        resource="heart_rate",
        endpoint="/v1/data/heart_rate.json",
        params={"device_type": "android_phone"},
    ),
    EndpointCandidate(
        resource="activity_data",
        endpoint="/v1/data/activity_data.json",
        params={"device_type": "android_phone"},
    ),
    EndpointCandidate(
        resource="workout_data",
        endpoint="/v1/data/workout_data.json",
        params={"device_type": "android_phone"},
    ),
    EndpointCandidate(
        resource="run_history",
        endpoint="/v1/sport/run/history.json",
        params={"source": "run.mifit.huami.com"},
    ),
    EndpointCandidate(
        resource="body_data",
        endpoint="/v1/data/body_data.json",
        params={"device_type": "android_phone"},
    ),
)
RUN_DETAIL_ENDPOINT = "/v1/sport/run/detail.json"
WEIGHT_RECORDS_ENDPOINT_TEMPLATE = "/users/{user_id}/members/-1/weightRecords"
WEIGHT_RECORDS_RESOURCE = "weight_records"


class AmazfitApiError(RuntimeError):
    """Raised when the Amazfit API returns an unexpected response."""


class AmazfitApiClient:
    """Best-effort client around reverse-engineered Amazfit endpoints."""

    ZEPP_WEB_HEADERS = {
        "app_name": "com.huami.webapp",
        "appname": "com.huami.webapp",
        "origin": "https://user.zepp.com",
        "referer": "https://user.zepp.com/",
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.5",
    }

    ZEPP_API_HEADERS = {
        "appname": "com.huami.midong",
        "appPlatform": "android_phone",
        "appplatform": "android_phone",
        "Accept": "application/json",
        "User-Agent": "Zepp/9.12.5 (Pixel 4; Android 12; Density/2.75)",
    }

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.state_store = AuthStateStore(config.auth_state_path)
        self.session = requests.Session()
        self.refresh_status = "not_attempted"
        self.refresh_error: str | None = None
        self.last_credential_source: str | None = None
        self.reauth_triggered = False
        self._refresh_succeeded = False
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": (
                    f"{config.app_name}/{config.app_version} "
                    f"({config.device_model}; Python requests)"
                ),
            }
        )
        self._ensure_stable_device_id()

    def close(self) -> None:
        self.session.close()

    def resolve_app_credentials(self, *, force_exchange: bool = False) -> dict[str, str]:
        """Return app-level credentials for Huami data endpoints."""
        if not force_exchange and self.config.has_app_credentials:
            credential_source = _cached_credential_source(self.config)
            self.last_credential_source = credential_source
            return {
                "app_token": self.config.app_token or "",
                "user_id": self.config.user_id or "",
                "credential_source": credential_source,
            }

        if not self.config.access_token:
            raise AmazfitApiError(
                "Missing app credentials and AMAZFIT_ACCESS_TOKEN is not available."
            )
        return self._resolve_zepp_app_credentials()

    def _resolve_zepp_app_credentials(self) -> dict[str, str]:
        if not self.config.access_token:
            raise AmazfitApiError(
                "Missing app credentials and AMAZFIT_ACCESS_TOKEN is not available."
            )

        payload = {
            "code": self.config.access_token,
            "device_id": self.config.device_id,
            "device_model": "android_phone",
            "app_version": "9.12.5",
            "dn": (
                "api-mifit.zepp.com,api-user.zepp.com,api-mifit.zepp.com,"
                "api-watch.zepp.com,app-analytics.zepp.com,auth.zepp.com,"
                "api-analytics.zepp.com"
            ),
            "third_name": "huami",
            "source": "com.huami.watch.hmwatchmanager:9.12.5:151689",
            "app_name": "com.huami.midong",
            "country_code": self.config.country_code,
            "grant_type": "access_token",
            "allow_registration": "false",
            "lang": "en",
            "countryState": "US-NY",
        }
        try:
            response = self.session.post(
                self.config.zepp_login_url,
                data=payload,
                headers=self.ZEPP_WEB_HEADERS,
                timeout=self.config.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise AmazfitApiError(f"Zepp access token exchange request failed: {exc}") from exc

        payload = _decode_json_response(response)
        token_info = payload.get("token_info", {}) if isinstance(payload, dict) else {}
        app_token = token_info.get("app_token")
        user_id = token_info.get("user_id")
        if not app_token or not user_id:
            raise AmazfitApiError(
                "Zepp login exchange did not return app_token/user_id. "
                f"Keys present: {sorted(payload.keys()) if isinstance(payload, dict) else type(payload)}"
            )

        self.config.app_token = str(app_token)
        self.config.app_token_source = "state"
        self.config.user_id = str(user_id)
        self.config.user_id_source = "state"
        self.config.api_hosts = _merge_api_hosts(self.config.api_hosts, payload)
        self._persist_auth_state(
            app_token=self.config.app_token,
            user_id=self.config.user_id,
            access_token=self.config.access_token,
            refresh_token=self.config.refresh_token,
        )
        credential_source = "refresh_then_exchange" if self._refresh_succeeded else "zepp_exchange"
        self.last_credential_source = credential_source
        return {
            "app_token": str(app_token),
            "user_id": str(user_id),
            "credential_source": credential_source,
        }

    def try_refresh_access_token(self) -> dict[str, Any] | None:
        """Refresh access token when a refresh URL is explicitly configured."""
        if not self.config.refresh_url or not self.config.refresh_token:
            return None

        try:
            response = self.session.post(
                self.config.refresh_url,
                data={"grant_type": "refresh_token", "refresh_token": self.config.refresh_token},
                timeout=self.config.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            self.refresh_status = "failed"
            self.refresh_error = f"Access token refresh request failed: {exc}"
            raise AmazfitApiError(f"Access token refresh request failed: {exc}") from exc
        payload = _decode_json_response(response)
        new_access_token = (
            payload.get("access_token")
            or _deep_get(payload, "data", "access_token")
            or _deep_get(payload, "token_info", "access_token")
        )
        if new_access_token:
            self.config.access_token = str(new_access_token)
            self.config.access_token_source = "state"
        new_refresh_token = (
            payload.get("refresh_token")
            or _deep_get(payload, "data", "refresh_token")
            or _deep_get(payload, "token_info", "refresh_token")
        )
        if new_refresh_token:
            self.config.refresh_token = str(new_refresh_token)
            self.config.refresh_token_source = "state"
        self._refresh_succeeded = bool(new_access_token)
        self.refresh_status = "ok"
        self.refresh_error = None
        self._persist_auth_state(
            access_token=self.config.access_token,
            refresh_token=self.config.refresh_token,
        )
        return {
            "access_token_masked": mask_secret(self.config.access_token),
            "refresh_token_masked": mask_secret(self.config.refresh_token),
        }

    def probe_and_fetch(
        self,
        *,
        from_date: date,
        to_date: date,
        candidates: tuple[EndpointCandidate, ...] | None = None,
        credentials: dict[str, str] | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> tuple[list[EndpointProbeResult], list[RawPayloadRecord]]:
        probe_results: list[EndpointProbeResult] = []
        raw_records: list[RawPayloadRecord] = []
        app_candidates = candidates or build_endpoint_candidates(self.config.extra_app_endpoints)

        credentials = credentials or self.resolve_app_credentials()
        total_app_requests = len(self.config.api_hosts) * (len(app_candidates) + 1)
        app_request_index = 0
        for host in self.config.api_hosts:
            if progress is not None:
                progress(f"Probing app-token endpoints on host {host}")
            for candidate in app_candidates:
                app_request_index += 1
                if progress is not None:
                    progress(
                        f"[{app_request_index}/{total_app_requests}] "
                        f"Fetching {candidate.resource} from {host}{candidate.endpoint}"
                    )
                try:
                    record = self._request_with_credentials(
                        credentials,
                        lambda current: self.fetch_data_endpoint(
                            host=host,
                            candidate=candidate,
                            app_token=current["app_token"],
                            user_id=current["user_id"],
                            from_date=from_date,
                            to_date=to_date,
                        ),
                    )
                except AmazfitApiError as exc:
                    probe_results.append(
                        EndpointProbeResult(
                            resource=candidate.resource,
                            host=host,
                            endpoint=candidate.endpoint,
                            ok=False,
                            http_status=getattr(exc, "http_status", None),
                            error=str(exc),
                        )
                    )
                    continue

                raw_records.append(record)
                probe_results.append(
                    EndpointProbeResult(
                        resource=candidate.resource,
                        host=host,
                        endpoint=candidate.endpoint,
                        ok=True,
                        http_status=record.http_status,
                    )
                )

            app_request_index += 1
            weight_endpoint = WEIGHT_RECORDS_ENDPOINT_TEMPLATE.format(
                user_id=credentials["user_id"]
            )
            if progress is not None:
                progress(
                    f"[{app_request_index}/{total_app_requests}] "
                    f"Fetching {WEIGHT_RECORDS_RESOURCE} from {host}{weight_endpoint}"
                )
            try:
                record = self._request_with_credentials(
                    credentials,
                    lambda current: self.fetch_weight_records_endpoint(
                        host=host,
                        app_token=current["app_token"],
                        user_id=current["user_id"],
                        from_date=from_date,
                    ),
                )
            except AmazfitApiError as exc:
                probe_results.append(
                    EndpointProbeResult(
                        resource=WEIGHT_RECORDS_RESOURCE,
                        host=host,
                        endpoint=weight_endpoint,
                        ok=False,
                        http_status=getattr(exc, "http_status", None),
                        error=str(exc),
                    )
                )
                continue

            raw_records.append(record)
            probe_results.append(
                EndpointProbeResult(
                    resource=WEIGHT_RECORDS_RESOURCE,
                    host=host,
                    endpoint=weight_endpoint,
                    ok=True,
                    http_status=record.http_status,
                )
            )

        total_bearer_requests = len(self.config.bearer_probe_endpoints)
        for bearer_index, endpoint in enumerate(self.config.bearer_probe_endpoints, start=1):
            if progress is not None:
                progress(
                    f"[bearer {bearer_index}/{total_bearer_requests}] "
                    f"Fetching /{endpoint.lstrip('/')}"
                )
            try:
                record = self.fetch_bearer_endpoint(endpoint)
            except AmazfitApiError as exc:
                probe_results.append(
                    EndpointProbeResult(
                        resource=_resource_name_from_endpoint(endpoint),
                        host=self.config.bearer_api_base_url or "<missing bearer host>",
                        endpoint=f"/{endpoint.lstrip('/')}",
                        ok=False,
                        http_status=getattr(exc, "http_status", None),
                        error=str(exc),
                    )
                )
                continue

            raw_records.append(record)
            probe_results.append(
                EndpointProbeResult(
                    resource=record.resource,
                    host=record.host,
                    endpoint=record.endpoint,
                    ok=True,
                    http_status=record.http_status,
                )
            )
        return probe_results, raw_records

    def fetch_data_endpoint(
        self,
        *,
        host: str,
        candidate: EndpointCandidate,
        app_token: str,
        user_id: str,
        from_date: date,
        to_date: date,
    ) -> RawPayloadRecord:
        url = f"{host.rstrip('/')}{candidate.endpoint}"
        params = {
            **candidate.params,
        }
        if candidate.resource == "run_history":
            params.setdefault("source", "run.mifit.huami.com")
        else:
            params.update(
                {
                    "userid": user_id,
                    "from_date": from_date.isoformat(),
                    "to_date": to_date.isoformat(),
                }
            )
        try:
            response = self.session.get(
                url,
                params=params,
                headers={**self.ZEPP_API_HEADERS, "apptoken": app_token},
                timeout=self.config.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise AmazfitApiError(
                f"Data request failed for {candidate.resource} on {host}: {exc}"
            ) from exc
        payload = _decode_json_response(response)
        fetched_at = datetime.now(timezone.utc).isoformat()
        return RawPayloadRecord(
            resource=candidate.resource,
            host=host,
            endpoint=candidate.endpoint,
            params=params,
            fetched_at=fetched_at,
            http_status=response.status_code,
            payload=payload,
        )

    def fetch_weight_records_endpoint(
        self,
        *,
        host: str,
        app_token: str,
        user_id: str,
        from_date: date,
    ) -> RawPayloadRecord:
        """Fetch body weight records from the private Zepp/Huami endpoint."""
        endpoint = WEIGHT_RECORDS_ENDPOINT_TEMPLATE.format(user_id=user_id)
        url = f"{host.rstrip('/')}{endpoint}"
        params = {
            "userid": user_id,
            "from_date": from_date.isoformat(),
            "fromTime": _date_to_epoch(from_date),
        }
        try:
            response = self.session.get(
                url,
                params={"fromTime": params["fromTime"]},
                headers={**self.ZEPP_API_HEADERS, "apptoken": app_token},
                timeout=self.config.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise AmazfitApiError(
                f"Weight records request failed on {host}: {exc}"
            ) from exc
        payload = _decode_json_response(response)
        return RawPayloadRecord(
            resource=WEIGHT_RECORDS_RESOURCE,
            host=host,
            endpoint=endpoint,
            params=params,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            http_status=response.status_code,
            payload=payload,
        )

    def fetch_run_detail_records(
        self,
        history_record: RawPayloadRecord,
        *,
        app_token: str,
        limit: int | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> list[RawPayloadRecord]:
        """Fetch workout details for a successful run_history payload."""
        if history_record.resource != "run_history":
            return []

        detail_candidates: list[tuple[str, str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in _extract_run_history_entries(history_record.payload):
            trackid = item.get("trackid")
            source = item.get("source") or history_record.params.get("source") or "run.mifit.huami.com"
            if trackid is None or source is None:
                continue

            signature = (str(trackid), str(source))
            if signature in seen:
                continue
            seen.add(signature)
            detail_candidates.append((signature[0], signature[1], item.get("end_time")))

        if limit is not None:
            detail_candidates = detail_candidates[:limit]

        detail_records: list[RawPayloadRecord] = []
        total_details = len(detail_candidates)
        for detail_index, (trackid, source, end_time) in enumerate(detail_candidates, start=1):
            if progress is not None:
                progress(
                    f"[run detail {detail_index}/{total_details}] "
                    f"Fetching trackid={trackid} from {history_record.host}"
                )
            try:
                detail_records.append(
                    self.fetch_run_detail_endpoint(
                        host=history_record.host,
                        app_token=app_token,
                        trackid=trackid,
                        source=source,
                        summary_end_time=end_time,
                    )
                )
            except AmazfitApiError:
                continue
        return detail_records

    def fetch_run_detail_endpoint(
        self,
        *,
        host: str,
        app_token: str,
        trackid: str,
        source: str,
        summary_end_time: Any = None,
    ) -> RawPayloadRecord:
        """Fetch detailed payload for a workout returned by run_history."""
        url = f"{host.rstrip('/')}{RUN_DETAIL_ENDPOINT}"
        params = {
            "trackid": trackid,
            "source": source,
        }
        try:
            response = self.session.get(
                url,
                params=params,
                headers={**self.ZEPP_API_HEADERS, "apptoken": app_token},
                timeout=self.config.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise AmazfitApiError(
                f"Run detail request failed for trackid={trackid} on {host}: {exc}"
            ) from exc

        payload = _decode_json_response(response)
        record_params = dict(params)
        if summary_end_time is not None:
            record_params["summary_end_time"] = summary_end_time
            summary_date = _timestamp_to_date(summary_end_time)
            if summary_date is not None:
                record_params["summary_date"] = summary_date

        return RawPayloadRecord(
            resource="run_detail",
            host=host,
            endpoint=RUN_DETAIL_ENDPOINT,
            params=record_params,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            http_status=response.status_code,
            payload=payload,
        )

    def fetch_bearer_endpoint(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> RawPayloadRecord:
        """Fetch a direct bearer-auth endpoint when the user knows the exact base URL."""
        if not self.config.access_token or not self.config.bearer_api_base_url:
            raise AmazfitApiError(
                "Bearer endpoint mode requires AMAZFIT_ACCESS_TOKEN and "
                "AMAZFIT_BEARER_API_BASE_URL."
            )
        url = f"{self.config.bearer_api_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        try:
            response = self.session.get(
                url,
                params=params or {},
                headers={"Authorization": f"Bearer {self.config.access_token}"},
                timeout=self.config.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise AmazfitApiError(f"Bearer request failed for {endpoint}: {exc}") from exc
        payload = _decode_json_response(response)
        return RawPayloadRecord(
            resource=endpoint.strip("/").replace("/", "_") or "bearer_resource",
            host=self.config.bearer_api_base_url,
            endpoint=f"/{endpoint.lstrip('/')}",
            params=params or {},
            fetched_at=datetime.now(timezone.utc).isoformat(),
            http_status=response.status_code,
            payload=payload,
        )

    def auth_diagnostics(self) -> dict[str, Any]:
        """Return auth metadata for validation reports."""
        return {
            "auth_state_path": self.config.auth_state_path.as_posix(),
            "credential_source": self.last_credential_source,
            "device_id_source": self.config.device_id_source,
            "refresh_status": self.refresh_status,
            "refresh_error": self.refresh_error,
            "reauth_triggered": self.reauth_triggered,
        }

    def _ensure_stable_device_id(self) -> None:
        if self.config.device_id_source == "default" or self.config.device_id == DEFAULT_DEVICE_ID:
            self.config.device_id = str(uuid.uuid4())
            self.config.device_id_source = "state"
            self.state_store.update(device_id=self.config.device_id)
            return

        if self.config.device_id_source == "env":
            self.state_store.update(device_id=self.config.device_id)

    def _persist_auth_state(self, **values: str | None) -> None:
        self.state_store.update(device_id=self.config.device_id, **values)

    def _request_with_credentials(
        self,
        credentials: dict[str, str],
        request: Callable[[dict[str, str]], RawPayloadRecord],
    ) -> RawPayloadRecord:
        try:
            return request(credentials)
        except AmazfitApiError as exc:
            if not self._should_retry_with_exchange(exc, credentials):
                raise

        refreshed_credentials = self.resolve_app_credentials(force_exchange=True)
        credentials.update(refreshed_credentials)
        self.reauth_triggered = True
        return request(credentials)

    def _should_retry_with_exchange(
        self,
        exc: AmazfitApiError,
        credentials: dict[str, str],
    ) -> bool:
        if getattr(exc, "http_status", None) != 401:
            return False
        if not self.config.access_token:
            return False
        return credentials.get("credential_source") not in {
            "zepp_exchange",
            "refresh_then_exchange",
        }


def decode_summary_blob(encoded_summary: str) -> dict[str, Any]:
    """Decode a base64 summary payload from band_data.json."""
    padded = encoded_summary + "=" * (-len(encoded_summary) % 4)
    decoded = b64decode(padded)
    return json.loads(decoded.decode("utf-8"))


def build_endpoint_candidates(extra_endpoints: tuple[str, ...] = ()) -> tuple[EndpointCandidate, ...]:
    candidates = list(DEFAULT_ENDPOINTS)
    known_endpoints = {candidate.endpoint for candidate in candidates}
    for endpoint in extra_endpoints:
        normalized = f"/{endpoint.lstrip('/')}"
        if normalized in known_endpoints:
            continue
        candidates.append(
            EndpointCandidate(
                resource=_resource_name_from_endpoint(normalized),
                endpoint=normalized,
                params={"device_type": "android_phone"},
            )
        )
    return tuple(candidates)


def _decode_json_response(response: requests.Response) -> dict[str, Any] | list[Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise AmazfitApiError(
            f"Non-JSON response from {response.request.method} {response.url}: "
            f"{response.text[:500]}"
        ) from exc

    if response.status_code >= 400:
        error = AmazfitApiError(
            f"HTTP {response.status_code} from {response.request.method} {response.url}: "
            f"{json.dumps(payload, ensure_ascii=False)[:500]}"
        )
        setattr(error, "http_status", response.status_code)
        raise error
    return payload


def _deep_get(payload: dict[str, Any] | list[Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _cached_credential_source(config: AppConfig) -> str:
    app_sources = {config.app_token_source, config.user_id_source}
    if app_sources == {"state"}:
        return "state"
    if app_sources == {"env"}:
        return "env"
    return "cached"


def _resource_name_from_endpoint(endpoint: str) -> str:
    return endpoint.strip("/").replace("/", "_").replace(".", "_") or "endpoint"


def _merge_api_hosts(
    existing_hosts: tuple[str, ...],
    payload: dict[str, Any] | list[Any],
) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return existing_hosts

    merged: list[str] = []
    seen: set[str] = set()

    def add_host(host: str) -> None:
        normalized = host.rstrip("/")
        if not normalized.startswith("http"):
            normalized = f"https://{normalized}"
        if normalized in seen:
            return
        seen.add(normalized)
        merged.append(normalized)

    for domain in payload.get("domains", []):
        if not isinstance(domain, dict):
            continue
        host = domain.get("host")
        if isinstance(host, str) and "api-mifit" in host:
            add_host(host)
        for cname in domain.get("cnames", []):
            if isinstance(cname, str) and "api-mifit" in cname:
                add_host(cname)

    for host in existing_hosts:
        add_host(host)
    return tuple(merged)


def _extract_run_history_entries(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []

    data = payload.get("data")
    if not isinstance(data, dict):
        return []

    summary = data.get("summary")
    if not isinstance(summary, list):
        return []

    return [item for item in summary if isinstance(item, dict)]


def _timestamp_to_date(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _date_to_epoch(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=timezone.utc).timestamp())

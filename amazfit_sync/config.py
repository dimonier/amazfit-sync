from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

from amazfit_sync.auth_state import AuthStateError, load_auth_state


DEFAULT_API_HOSTS = (
    "https://api-mifit.zepp.com",
    "https://api-mifit-cn3.zepp.com",
    "https://api-mifit-us2.zepp.com",
    "https://api-mifit.huami.com",
    "https://api-mifit-de.huami.com",
    "https://api-mifit-de2.huami.com",
)
DEFAULT_DEVICE_ID = "02:00:00:00:00:00"


class ConfigError(RuntimeError):
    """Raised when required runtime configuration is invalid."""


@dataclass(slots=True)
class AppConfig:
    access_token: str | None
    access_token_source: str
    refresh_token: str | None
    refresh_token_source: str
    app_token: str | None
    app_token_source: str
    user_id: str | None
    user_id_source: str
    country_code: str
    app_name: str
    device_id: str
    device_id_source: str
    device_model: str
    app_version: str
    data_dir: Path
    obsidian_export_dir: Path
    auth_state_path: Path
    account_base_url: str
    api_hosts: tuple[str, ...]
    request_timeout_seconds: int
    default_from_date: date
    default_to_date: date
    refresh_url: str | None
    bearer_api_base_url: str | None
    extra_app_endpoints: tuple[str, ...]
    bearer_probe_endpoints: tuple[str, ...]
    zepp_login_url: str

    @property
    def has_app_credentials(self) -> bool:
        return bool(self.app_token and self.user_id)

    @property
    def has_exchange_credentials(self) -> bool:
        return bool(self.access_token)


def load_config(
    env_path: Path | None = None,
    *,
    require_api_credentials: bool = True,
) -> AppConfig:
    """Load and validate configuration from environment variables."""
    load_dotenv(dotenv_path=env_path, override=False)

    today = date.today()
    default_from_date = _parse_date("AMAZFIT_FROM_DATE") or today - timedelta(days=7)
    default_to_date = _parse_date("AMAZFIT_TO_DATE") or today

    if default_from_date > default_to_date:
        raise ConfigError("AMAZFIT_FROM_DATE cannot be after AMAZFIT_TO_DATE.")

    data_dir = Path(_clean_env("AMAZFIT_DATA_DIR") or "data")
    auth_state_path = Path(_clean_env("AMAZFIT_AUTH_STATE_PATH") or data_dir / "auth_state.json")
    auth_state = _load_auth_state_or_raise(auth_state_path)

    access_token, access_token_source = _resolve_value(
        auth_state,
        "access_token",
        "AMAZFIT_ACCESS_TOKEN",
        "ACCESS_TOKEN",
    )
    refresh_token, refresh_token_source = _resolve_value(
        auth_state,
        "refresh_token",
        "AMAZFIT_REFRESH_TOKEN",
        "REFRESH_TOKEN",
    )
    app_token, app_token_source = _resolve_value(
        auth_state,
        "app_token",
        "AMAZFIT_APP_TOKEN",
        "APP_TOKEN",
    )
    user_id, user_id_source = _resolve_value(
        auth_state,
        "user_id",
        "AMAZFIT_USER_ID",
        "USER_ID",
    )
    device_id, device_id_source = _resolve_value(
        auth_state,
        "device_id",
        "AMAZFIT_DEVICE_ID",
        default=DEFAULT_DEVICE_ID,
    )

    config = AppConfig(
        access_token=access_token,
        access_token_source=access_token_source,
        refresh_token=refresh_token,
        refresh_token_source=refresh_token_source,
        app_token=app_token,
        app_token_source=app_token_source,
        user_id=user_id,
        user_id_source=user_id_source,
        country_code=(_clean_env("AMAZFIT_COUNTRY_CODE", "COUNTRY_CODE") or "US").upper(),
        app_name=_clean_env("AMAZFIT_APP_NAME") or "com.huami.watch.hmwatchmanager",
        device_id=device_id or DEFAULT_DEVICE_ID,
        device_id_source=device_id_source,
        device_model=_clean_env("AMAZFIT_DEVICE_MODEL") or "android_phone",
        app_version=_clean_env("AMAZFIT_APP_VERSION") or "9.1.0",
        data_dir=data_dir,
        obsidian_export_dir=Path(_clean_env("OBSIDIAN_EXPORT_DIR") or "exports/obsidian"),
        auth_state_path=auth_state_path,
        account_base_url=_clean_env("AMAZFIT_ACCOUNT_BASE_URL") or "https://account.huami.com",
        api_hosts=_parse_hosts(_clean_env("AMAZFIT_API_HOSTS")),
        request_timeout_seconds=int(_clean_env("AMAZFIT_TIMEOUT_SECONDS") or "30"),
        default_from_date=default_from_date,
        default_to_date=default_to_date,
        refresh_url=_clean_env("AMAZFIT_TOKEN_REFRESH_URL"),
        bearer_api_base_url=_clean_env("AMAZFIT_BEARER_API_BASE_URL"),
        extra_app_endpoints=_parse_csv(_clean_env("AMAZFIT_EXTRA_APP_ENDPOINTS")),
        bearer_probe_endpoints=_parse_csv(_clean_env("AMAZFIT_BEARER_PROBE_ENDPOINTS")),
        zepp_login_url=_clean_env("AMAZFIT_ZEPP_LOGIN_URL")
        or "https://api-mifit-us2.zepp.com/v2/client/login",
    )

    if require_api_credentials and not config.access_token and not config.app_token:
        raise ConfigError(
            "Provide AMAZFIT_ACCESS_TOKEN, AMAZFIT_APP_TOKEN, or a local auth state file."
        )

    return config


def mask_secret(secret: str | None) -> str:
    """Return a short masked representation of a secret."""
    if not secret:
        return "<missing>"
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}...{secret[-4:]}"


def _clean_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is None:
            continue
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _load_auth_state_or_raise(path: Path) -> dict[str, object]:
    try:
        return load_auth_state(path)
    except AuthStateError as exc:
        raise ConfigError(str(exc)) from exc


def _resolve_value(
    auth_state: dict[str, object],
    state_key: str,
    *env_names: str,
    default: str | None = None,
) -> tuple[str | None, str]:
    env_value = _clean_env(*env_names)
    if env_value is not None:
        return env_value, "env"

    state_value = auth_state.get(state_key)
    if isinstance(state_value, str):
        stripped = state_value.strip()
        if stripped:
            return stripped, "state"

    if default is not None:
        return default, "default"
    return None, "missing"


def _parse_date(name: str) -> date | None:
    value = _clean_env(name)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must use YYYY-MM-DD format.") from exc


def _parse_hosts(raw_hosts: str | None) -> tuple[str, ...]:
    if not raw_hosts:
        return DEFAULT_API_HOSTS
    hosts = tuple(host.strip().rstrip("/") for host in raw_hosts.split(",") if host.strip())
    if not hosts:
        raise ConfigError("AMAZFIT_API_HOSTS cannot be empty if provided.")
    return hosts


def _parse_csv(raw_value: str | None) -> tuple[str, ...]:
    if not raw_value:
        return ()
    return tuple(item.strip() for item in raw_value.split(",") if item.strip())

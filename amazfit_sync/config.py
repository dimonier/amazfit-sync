from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv


DEFAULT_API_HOSTS = (
    "https://api-mifit.zepp.com",
    "https://api-mifit-cn3.zepp.com",
    "https://api-mifit-us2.zepp.com",
    "https://api-mifit.huami.com",
    "https://api-mifit-de.huami.com",
    "https://api-mifit-de2.huami.com",
)


class ConfigError(RuntimeError):
    """Raised when required runtime configuration is invalid."""


@dataclass(slots=True)
class AppConfig:
    access_token: str | None
    refresh_token: str | None
    app_token: str | None
    user_id: str | None
    country_code: str
    app_name: str
    device_id: str
    device_model: str
    app_version: str
    data_dir: Path
    obsidian_export_dir: Path
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

    config = AppConfig(
        access_token=_clean_env("AMAZFIT_ACCESS_TOKEN", "ACCESS_TOKEN"),
        refresh_token=_clean_env("AMAZFIT_REFRESH_TOKEN", "REFRESH_TOKEN"),
        app_token=_clean_env("AMAZFIT_APP_TOKEN", "APP_TOKEN"),
        user_id=_clean_env("AMAZFIT_USER_ID", "USER_ID"),
        country_code=(_clean_env("AMAZFIT_COUNTRY_CODE", "COUNTRY_CODE") or "US").upper(),
        app_name=_clean_env("AMAZFIT_APP_NAME") or "com.huami.watch.hmwatchmanager",
        device_id=_clean_env("AMAZFIT_DEVICE_ID") or "02:00:00:00:00:00",
        device_model=_clean_env("AMAZFIT_DEVICE_MODEL") or "android_phone",
        app_version=_clean_env("AMAZFIT_APP_VERSION") or "9.1.0",
        data_dir=Path(_clean_env("AMAZFIT_DATA_DIR") or "data"),
        obsidian_export_dir=Path(_clean_env("OBSIDIAN_EXPORT_DIR") or "exports/obsidian"),
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
            "Provide AMAZFIT_ACCESS_TOKEN or AMAZFIT_APP_TOKEN in .env."
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

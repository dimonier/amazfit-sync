from __future__ import annotations

import argparse
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from amazfit_sync.amazfit_api import AmazfitApiClient
from amazfit_sync.config import AppConfig, load_config
from amazfit_sync.obsidian_export import export_bundle_to_obsidian
from amazfit_sync.pipeline import _apply_runtime_date_overrides, _resolve_default_date_range
from amazfit_sync.storage import JsonStorage


class FixedDate(date):
    @classmethod
    def today(cls) -> "FixedDate":
        return cls(2026, 3, 19)


class CliDefaultRangesTest(unittest.TestCase):
    def make_config(self, root_dir: Path) -> AppConfig:
        return AppConfig(
            access_token=None,
            access_token_source="missing",
            refresh_token=None,
            refresh_token_source="missing",
            app_token=None,
            app_token_source="missing",
            user_id=None,
            user_id_source="missing",
            country_code="US",
            app_name="app",
            device_id="device-id",
            device_id_source="env",
            device_model="android_phone",
            app_version="9.1.0",
            data_dir=root_dir / "data",
            obsidian_export_dir=root_dir / "exports",
            auth_state_path=root_dir / "data" / "auth_state.json",
            account_base_url="https://account.huami.com",
            api_hosts=("https://api-mifit.zepp.com",),
            request_timeout_seconds=30,
            default_from_date=date(2026, 3, 1),
            default_to_date=date(2026, 3, 7),
            refresh_url=None,
            bearer_api_base_url=None,
            extra_app_endpoints=(),
            bearer_probe_endpoints=(),
            zepp_login_url="https://api-mifit-us2.zepp.com/v2/client/login",
        )

    def write_normalized_month(self, storage: JsonStorage, *, dates: list[str]) -> None:
        payload = {
            "generated_at": "2026-03-19T00:00:00+00:00",
            "date_range": {"from": dates[0], "to": dates[-1]},
            "resources": ["band_summary"],
            "days": [{"date": value, "daily_summary": {}} for value in dates],
            "validation_report_path": "data/reports/latest_validation.json",
            "unknown_resources": [],
        }
        target = storage.normalized_dir / dates[-1][:4] / f"{dates[-1][:7]}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload), encoding="utf-8")

    def test_storage_latest_normalized_date_reads_latest_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = JsonStorage(Path(tmp) / "data")
            storage.ensure_dirs()
            self.write_normalized_month(
                storage,
                dates=["2026-03-15", "2026-03-16", "2026-03-18"],
            )

            self.assertEqual(storage.latest_normalized_date(), date(2026, 3, 18))

    def test_sync_defaults_use_latest_normalized_date_until_today(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            storage = JsonStorage(root_dir / "data")
            storage.ensure_dirs()
            self.write_normalized_month(
                storage,
                dates=["2026-03-15", "2026-03-16", "2026-03-18"],
            )
            config = self.make_config(root_dir)

            with patch("amazfit_sync.pipeline.date", FixedDate):
                from_date, to_date = _resolve_default_date_range(config, "sync", storage)

            self.assertEqual(from_date, date(2026, 3, 18))
            self.assertEqual(to_date, date(2026, 3, 19))

    def test_export_defaults_cover_yesterday_and_previous_two_weeks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            storage = JsonStorage(root_dir / "data")
            storage.ensure_dirs()
            config = self.make_config(root_dir)

            with patch("amazfit_sync.pipeline.date", FixedDate):
                from_date, to_date = _resolve_default_date_range(config, "export-obsidian", storage)

            self.assertEqual(from_date, date(2026, 3, 4))
            self.assertEqual(to_date, date(2026, 3, 18))

    def test_explicit_cli_dates_override_command_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            storage = JsonStorage(root_dir / "data")
            storage.ensure_dirs()
            self.write_normalized_month(storage, dates=["2026-03-18"])
            config = self.make_config(root_dir)
            args = argparse.Namespace(
                command="sync",
                from_date="2026-03-10",
                to_date=None,
                data_dir=None,
                obsidian_dir=None,
            )

            with patch("amazfit_sync.pipeline.date", FixedDate):
                resolved = _apply_runtime_date_overrides(config, args, storage)

            self.assertEqual(resolved.default_from_date, date(2026, 3, 10))
            self.assertEqual(resolved.default_to_date, date(2026, 3, 19))

    def test_load_config_keeps_absolute_obsidian_export_path_from_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "AMAZFIT_ACCESS_TOKEN=test-token",
                        "OBSIDIAN_EXPORT_DIR=D:/Obsidian-Dima/activity-reports",
                    ]
                ),
                encoding="utf-8",
            )
            original_access_token = os.environ.get("AMAZFIT_ACCESS_TOKEN")
            original_export_dir = os.environ.get("OBSIDIAN_EXPORT_DIR")

            try:
                os.environ.pop("AMAZFIT_ACCESS_TOKEN", None)
                os.environ.pop("OBSIDIAN_EXPORT_DIR", None)
                config = load_config(env_path)
            finally:
                if original_access_token is None:
                    os.environ.pop("AMAZFIT_ACCESS_TOKEN", None)
                else:
                    os.environ["AMAZFIT_ACCESS_TOKEN"] = original_access_token

                if original_export_dir is None:
                    os.environ.pop("OBSIDIAN_EXPORT_DIR", None)
                else:
                    os.environ["OBSIDIAN_EXPORT_DIR"] = original_export_dir

            self.assertEqual(config.obsidian_export_dir, Path("D:/Obsidian-Dima/activity-reports"))

    def test_load_config_reads_credentials_from_local_auth_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_dir = Path(tmp)
            data_dir = root_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "auth_state.json").write_text(
                json.dumps(
                    {
                        "access_token": "state-access",
                        "app_token": "state-app",
                        "user_id": "state-user",
                        "device_id": "state-device",
                    }
                ),
                encoding="utf-8",
            )
            env_path = root_dir / ".env"
            env_path.write_text(f"AMAZFIT_DATA_DIR={data_dir.as_posix()}\n", encoding="utf-8")
            original_values = {
                name: os.environ.get(name)
                for name in (
                    "AMAZFIT_DATA_DIR",
                    "AMAZFIT_ACCESS_TOKEN",
                    "AMAZFIT_APP_TOKEN",
                    "AMAZFIT_USER_ID",
                    "AMAZFIT_DEVICE_ID",
                )
            }

            try:
                for name in original_values:
                    os.environ.pop(name, None)
                config = load_config(env_path)
            finally:
                for name, value in original_values.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value

            self.assertEqual(config.access_token, "state-access")
            self.assertEqual(config.access_token_source, "state")
            self.assertEqual(config.app_token, "state-app")
            self.assertEqual(config.app_token_source, "state")
            self.assertEqual(config.user_id, "state-user")
            self.assertEqual(config.device_id, "state-device")
            self.assertEqual(config.device_id_source, "state")


class AuthFlowTest(unittest.TestCase):
    def make_config(self, root_dir: Path) -> AppConfig:
        return AppConfig(
            access_token="access-token",
            access_token_source="env",
            refresh_token=None,
            refresh_token_source="missing",
            app_token=None,
            app_token_source="missing",
            user_id=None,
            user_id_source="missing",
            country_code="US",
            app_name="app",
            device_id="device-id",
            device_id_source="env",
            device_model="android_phone",
            app_version="9.1.0",
            data_dir=root_dir / "data",
            obsidian_export_dir=root_dir / "exports",
            auth_state_path=root_dir / "data" / "auth_state.json",
            account_base_url="https://account.huami.com",
            api_hosts=("https://api-mifit.zepp.com",),
            request_timeout_seconds=30,
            default_from_date=date(2026, 3, 1),
            default_to_date=date(2026, 3, 7),
            refresh_url=None,
            bearer_api_base_url=None,
            extra_app_endpoints=(),
            bearer_probe_endpoints=(),
            zepp_login_url="https://api-mifit-us2.zepp.com/v2/client/login",
        )

    def test_resolve_app_credentials_prefers_cached_app_token_over_exchange(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp))
            config.app_token = "cached-app-token"
            config.app_token_source = "env"
            config.user_id = "user-1"
            config.user_id_source = "env"

            client = AmazfitApiClient(config)
            with patch.object(
                client,
                "_resolve_zepp_app_credentials",
                side_effect=AssertionError("Exchange should not be used"),
            ):
                credentials = client.resolve_app_credentials()
            client.close()

            self.assertEqual(credentials["app_token"], "cached-app-token")
            self.assertEqual(credentials["user_id"], "user-1")
            self.assertEqual(credentials["credential_source"], "env")

    def test_resolve_app_credentials_uses_exchange_when_cached_credentials_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp))
            client = AmazfitApiClient(config)
            with patch.object(
                client,
                "_resolve_zepp_app_credentials",
                return_value={
                    "app_token": "fresh-app-token",
                    "user_id": "user-2",
                    "credential_source": "zepp_exchange",
                },
            ) as mocked_exchange:
                credentials = client.resolve_app_credentials()
            client.close()

            self.assertEqual(credentials["credential_source"], "zepp_exchange")
            mocked_exchange.assert_called_once()

    def test_client_generates_and_persists_stable_device_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self.make_config(Path(tmp))
            config.device_id = "02:00:00:00:00:00"
            config.device_id_source = "default"

            client = AmazfitApiClient(config)
            generated_device_id = client.config.device_id
            client.close()

            state_payload = json.loads(config.auth_state_path.read_text(encoding="utf-8"))
            self.assertNotEqual(generated_device_id, "02:00:00:00:00:00")
            self.assertEqual(state_payload["device_id"], generated_device_id)


class ObsidianExportRangeTest(unittest.TestCase):
    def test_export_bundle_to_obsidian_writes_only_days_in_range(self) -> None:
        bundle = {
            "days": [
                {"date": "2026-03-17", "daily_summary": {"steps_total": 1}},
                {"date": "2026-03-18", "daily_summary": {"steps_total": 2}},
                {"date": "2026-03-19", "daily_summary": {"steps_total": 3}},
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            legacy_target = output_dir / "2026-03-18.md"
            legacy_target.write_text("legacy", encoding="utf-8")

            written_paths = export_bundle_to_obsidian(
                bundle,
                output_dir,
                from_date=date(2026, 3, 18),
                to_date=date(2026, 3, 18),
                preserve_existing=False,
            )

            self.assertEqual([path.name for path in written_paths], ["2026-03-18-physical.md"])
            self.assertTrue((output_dir / "2026-03-18-physical.md").exists())
            self.assertFalse(legacy_target.exists())
            self.assertFalse((output_dir / "2026-03-17-physical.md").exists())
            self.assertFalse((output_dir / "2026-03-19-physical.md").exists())

    def test_default_export_overwrites_yesterday_but_skips_existing_backfill_days(self) -> None:
        bundle = {
            "days": [
                {"date": "2026-03-17", "daily_summary": {"steps_total": 1}},
                {"date": "2026-03-18", "daily_summary": {"steps_total": 2}},
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            existing_backfill = output_dir / "2026-03-17-physical.md"
            existing_backfill.write_text("keep-me", encoding="utf-8")
            yesterday_target = output_dir / "2026-03-18-physical.md"
            yesterday_target.write_text("old-yesterday", encoding="utf-8")

            written_paths = export_bundle_to_obsidian(
                bundle,
                output_dir,
                from_date=date(2026, 3, 4),
                to_date=date(2026, 3, 18),
                preserve_existing=True,
                always_overwrite_date=date(2026, 3, 18),
            )

            self.assertEqual([path.name for path in written_paths], ["2026-03-18-physical.md"])
            self.assertEqual(existing_backfill.read_text(encoding="utf-8"), "keep-me")
            self.assertNotEqual(yesterday_target.read_text(encoding="utf-8"), "old-yesterday")


if __name__ == "__main__":
    unittest.main()

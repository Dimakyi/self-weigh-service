import os
import subprocess
import sys

import pytest


def run_config(*, app_env, admin_key=None, kiosk_key=None, extra_env=None):
    env = os.environ.copy()
    env["APP_ENV"] = app_env
    if extra_env:
        env.update(extra_env)

    if admin_key is None:
        env.pop("ADMIN_API_KEY", None)
    else:
        env["ADMIN_API_KEY"] = admin_key

    if kiosk_key is None:
        env.pop("KIOSK_API_KEY", None)
    else:
        env["KIOSK_API_KEY"] = kiosk_key

    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from app import config; "
                "print(config.APP_ENV); "
                "print(config.ADMIN_API_KEY); "
                "print(config.KIOSK_API_KEY)"
            ),
        ],
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("admin_key", "kiosk_key"),
    [
        ("dev-admin-key", "A" * 40),
        ("A" * 40, "dev-kiosk-key"),
        ("dev-admin-key", "dev-kiosk-key"),
    ],
)
def test_production_rejects_default_api_keys(admin_key, kiosk_key):
    result = run_config(
        app_env="production",
        admin_key=admin_key,
        kiosk_key=kiosk_key,
    )

    assert result.returncode != 0
    assert "Production requires a non-default" in result.stderr


@pytest.mark.parametrize(
    ("admin_key", "kiosk_key"),
    [
        ("", "B" * 40),
        ("   ", "B" * 40),
        ("A" * 31, "B" * 40),
        ("A" * 40, ""),
        ("A" * 40, "   "),
        ("A" * 40, "B" * 31),
    ],
)
def test_production_rejects_blank_or_short_api_keys(admin_key, kiosk_key):
    result = run_config(
        app_env="production",
        admin_key=admin_key,
        kiosk_key=kiosk_key,
    )

    assert result.returncode != 0
    assert "containing at least 32 characters" in result.stderr


def test_production_accepts_strong_non_default_api_keys():
    admin_key = "admin-" + "A" * 40
    kiosk_key = "kiosk-" + "B" * 40

    result = run_config(
        app_env="production",
        admin_key=admin_key,
        kiosk_key=kiosk_key,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "production",
        admin_key,
        kiosk_key,
    ]


@pytest.mark.parametrize("app_env", ["", "prod", "local", "production-like"])
def test_config_rejects_unsupported_environment_names(app_env):
    result = run_config(app_env=app_env)

    assert result.returncode != 0
    assert "Unsupported APP_ENV" in result.stderr


def test_development_allows_default_api_keys():
    result = run_config(app_env="development")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "development",
        "dev-admin-key",
        "dev-kiosk-key",
    ]


@pytest.mark.parametrize(
    ("setting", "value", "error_message"),
    [
        (
            "OUTBOX_MAX_ATTEMPTS",
            "0",
            "OUTBOX_MAX_ATTEMPTS must be at least 1",
        ),
        (
            "OUTBOX_RETRY_BASE_SECONDS",
            "0",
            "OUTBOX_RETRY_BASE_SECONDS must be above 0",
        ),
        (
            "OUTBOX_RETRY_MAX_SECONDS",
            "1",
            "OUTBOX_RETRY_MAX_SECONDS must be at least the base delay",
        ),
    ],
)
def test_config_rejects_invalid_outbox_retry_settings(
    setting, value, error_message
):
    result = run_config(
        app_env="development",
        extra_env={setting: value},
    )

    assert result.returncode != 0
    assert error_message in result.stderr

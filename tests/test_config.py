import os
import subprocess
import sys

import pytest


def run_config(*, app_env, admin_key=None, kiosk_key=None):
    env = os.environ.copy()
    env["APP_ENV"] = app_env

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
        ("dev-admin-key", "secure-kiosk-key"),
        ("secure-admin-key", "dev-kiosk-key"),
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
    assert (
        "Production requires non-default ADMIN_API_KEY and KIOSK_API_KEY"
        in result.stderr
    )


def test_production_accepts_non_default_api_keys():
    result = run_config(
        app_env="production",
        admin_key="secure-admin-key",
        kiosk_key="secure-kiosk-key",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "production",
        "secure-admin-key",
        "secure-kiosk-key",
    ]


def test_development_allows_default_api_keys():
    result = run_config(app_env="development")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "development",
        "dev-admin-key",
        "dev-kiosk-key",
    ]

"""Configuration. Defaults are illustrative, not real airline rates."""
import os


APP_ENV = os.getenv("APP_ENV", "development").strip().lower()

ALLOWED_ENVIRONMENTS = {"development", "test", "staging", "production"}

if APP_ENV not in ALLOWED_ENVIRONMENTS:
    raise RuntimeError(
        f"Unsupported APP_ENV: {APP_ENV!r}. "
        f"Choose one of: {', '.join(sorted(ALLOWED_ENVIRONMENTS))}."
    )

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./selfweigh.db")

# Operator-level keys. Change these outside local development.
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "dev-admin-key")
KIOSK_API_KEY = os.getenv("KIOSK_API_KEY", "dev-kiosk-key")

if APP_ENV == "production":
    production_keys = {
        "ADMIN_API_KEY": ADMIN_API_KEY,
        "KIOSK_API_KEY": KIOSK_API_KEY,
    }

    for key_name, key_value in production_keys.items():
        if (
            not key_value.strip()
            or len(key_value) < 32
            or key_value in {"dev-admin-key", "dev-kiosk-key"}
        ):
            raise RuntimeError(
                f"Production requires a non-default {key_name} "
                "containing at least 32 characters."
            )

# Defaults offered when an airline is created without its own policy.
DEFAULT_ALLOWANCE_KG = float(os.getenv("DEFAULT_ALLOWANCE_KG", "23"))
DEFAULT_MAX_BAG_KG = float(os.getenv("DEFAULT_MAX_BAG_KG", "32"))
DEFAULT_EXCESS_RATE_CENTS_PER_KG = int(os.getenv("DEFAULT_EXCESS_RATE_CENTS_PER_KG", "15000"))

# Statements and cash reconciliation use this timezone for month and day boundaries.
TIMEZONE = os.getenv("TIMEZONE", "Africa/Johannesburg")

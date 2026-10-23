"""Configuration. Defaults are illustrative, not real airline rates."""
import os

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./selfweigh.db")

# Operator-level keys. Change these outside local development.
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "dev-admin-key")
KIOSK_API_KEY = os.getenv("KIOSK_API_KEY", "dev-kiosk-key")

if APP_ENV == "production":
    if (
        ADMIN_API_KEY == "dev-admin-key"
        or KIOSK_API_KEY == "dev-kiosk-key"
    ):
        raise RuntimeError(
            "Production requires non-default ADMIN_API_KEY and KIOSK_API_KEY."
        )

# Defaults offered when an airline is created without its own policy.
DEFAULT_ALLOWANCE_KG = float(os.getenv("DEFAULT_ALLOWANCE_KG", "23"))
DEFAULT_MAX_BAG_KG = float(os.getenv("DEFAULT_MAX_BAG_KG", "32"))
DEFAULT_EXCESS_RATE_CENTS_PER_KG = int(os.getenv("DEFAULT_EXCESS_RATE_CENTS_PER_KG", "15000"))

# Statements and cash reconciliation use this timezone for month and day boundaries.
TIMEZONE = os.getenv("TIMEZONE", "Africa/Johannesburg")

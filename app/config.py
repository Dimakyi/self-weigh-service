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

# Outbox worker settings (python -m app.worker).
WORKER_POLL_SECONDS = float(os.getenv("WORKER_POLL_SECONDS", "2"))
WORKER_BATCH_SIZE = int(os.getenv("WORKER_BATCH_SIZE", "100"))
WORKER_LEASE_SECONDS = int(os.getenv("WORKER_LEASE_SECONDS", "60"))

if WORKER_POLL_SECONDS <= 0 or WORKER_BATCH_SIZE < 1 or WORKER_LEASE_SECONDS < 1:
    raise RuntimeError(
        "WORKER_POLL_SECONDS must be above 0, and WORKER_BATCH_SIZE and "
        "WORKER_LEASE_SECONDS must be at least 1."
    )

# Outbox retry and dead-letter settings.
OUTBOX_MAX_ATTEMPTS = int(os.getenv("OUTBOX_MAX_ATTEMPTS", "5"))
OUTBOX_RETRY_BASE_SECONDS = float(
    os.getenv("OUTBOX_RETRY_BASE_SECONDS", "2")
)
OUTBOX_RETRY_MAX_SECONDS = float(
    os.getenv("OUTBOX_RETRY_MAX_SECONDS", "300")
)

if (
    OUTBOX_MAX_ATTEMPTS < 1
    or OUTBOX_RETRY_BASE_SECONDS <= 0
    or OUTBOX_RETRY_MAX_SECONDS < OUTBOX_RETRY_BASE_SECONDS
):
    raise RuntimeError(
        "OUTBOX_MAX_ATTEMPTS must be at least 1, "
        "OUTBOX_RETRY_BASE_SECONDS must be above 0, and "
        "OUTBOX_RETRY_MAX_SECONDS must be at least the base delay."
    )

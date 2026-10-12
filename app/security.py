"""API-key auth. Three roles: admin (manages airlines), kiosk (weigh/pay), airline (reads own data)."""
import hashlib
import secrets

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.db import get_db
from app.models import Airline, Staff


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_airline_key() -> str:
    return "swk_" + secrets.token_urlsafe(24)


def new_staff_key() -> str:
    return "sws_" + secrets.token_urlsafe(24)


def _check(provided: str | None, expected: str) -> None:
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(401, "Invalid or missing key")


def require_admin(x_admin_key: str | None = Header(None)) -> None:
    _check(x_admin_key, config.ADMIN_API_KEY)


def require_kiosk(x_kiosk_key: str | None = Header(None)) -> None:
    _check(x_kiosk_key, config.KIOSK_API_KEY)


def current_airline(x_api_key: str | None = Header(None), db: Session = Depends(get_db)) -> Airline:
    if not x_api_key:
        raise HTTPException(401, "Invalid or missing key")
    airline = db.scalar(select(Airline).where(Airline.api_key_hash == hash_key(x_api_key)))
    if airline is None or not airline.active:
        raise HTTPException(401, "Invalid or missing key")
    return airline


def current_staff(x_staff_key: str | None = Header(None), db: Session = Depends(get_db)) -> Staff:
    if not x_staff_key:
        raise HTTPException(401, "Invalid or missing key")
    staff = db.scalar(select(Staff).where(Staff.api_key_hash == hash_key(x_staff_key)))
    if staff is None or not staff.active:
        raise HTTPException(401, "Invalid or missing key")
    return staff

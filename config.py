"""Configuration loaded from environment variables only (never hardcode secrets)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

from dotenv import load_dotenv

from phone_utils import PhoneParseError, normalise_country_code

VALID_MODES = ("LOCAL", "TWILIO")
_TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")


class ConfigError(RuntimeError):
    """Raised when the environment configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    telegram_token: str = field(repr=False)
    provider_mode: str = "LOCAL"
    default_country: str = "IN"
    allowed_user_ids: frozenset = frozenset()
    rate_limit_max_requests: int = 5
    rate_limit_window_seconds: int = 60
    http_timeout_seconds: float = 10.0
    http_max_retries: int = 2
    twilio_account_sid: str = field(default="", repr=False)
    twilio_auth_token: str = field(default="", repr=False)
    twilio_api_key_sid: str = field(default="", repr=False)
    twilio_api_key_secret: str = field(default="", repr=False)
    twilio_enable_line_type: bool = False


def _get_int(env: Mapping[str, str], name: str, default: int, minimum: int, maximum: int) -> int:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number.") from None
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _get_float(env: Mapping[str, str], name: str, default: float, minimum: float, maximum: float) -> float:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number.") from None
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _get_bool(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = (env.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be true or false.")


def _get_user_ids(env: Mapping[str, str]) -> frozenset:
    raw = (env.get("ALLOWED_USER_IDS") or "").strip()
    if not raw:
        return frozenset()
    try:
        return frozenset(int(part) for part in raw.split(",") if part.strip())
    except ValueError:
        raise ConfigError("ALLOWED_USER_IDS must be comma-separated numeric Telegram user IDs.") from None


def load_settings(env: Optional[Mapping[str, str]] = None, *, require_token: bool = True) -> Settings:
    """Build Settings from `env` (defaults to .env file + process environment)."""
    if env is None:
        load_dotenv(Path(__file__).resolve().parent / ".env")
        env = os.environ

    token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if require_token:
        if not token:
            raise ConfigError("TELEGRAM_BOT_TOKEN is not set. Add it to your .env file.")
        if not _TOKEN_RE.fullmatch(token):
            raise ConfigError(
                "TELEGRAM_BOT_TOKEN does not look valid. Copy the full token from @BotFather "
                "(format 123456789:AA...)."
            )

    mode = (env.get("LOOKUP_PROVIDER") or "LOCAL").strip().upper()
    if mode not in VALID_MODES:
        raise ConfigError(f"LOOKUP_PROVIDER must be one of: {', '.join(VALID_MODES)}.")

    try:
        country = normalise_country_code((env.get("DEFAULT_COUNTRY") or "IN"))
    except PhoneParseError as exc:
        raise ConfigError(f"DEFAULT_COUNTRY: {exc.user_message}") from None

    return Settings(
        telegram_token=token,
        provider_mode=mode,
        default_country=country,
        allowed_user_ids=_get_user_ids(env),
        rate_limit_max_requests=_get_int(env, "RATE_LIMIT_MAX_REQUESTS", 5, 1, 1000),
        rate_limit_window_seconds=_get_int(env, "RATE_LIMIT_WINDOW_SECONDS", 60, 1, 86400),
        http_timeout_seconds=_get_float(env, "HTTP_TIMEOUT_SECONDS", 10.0, 1.0, 60.0),
        http_max_retries=_get_int(env, "HTTP_MAX_RETRIES", 2, 0, 5),
        twilio_account_sid=(env.get("TWILIO_ACCOUNT_SID") or "").strip(),
        twilio_auth_token=(env.get("TWILIO_AUTH_TOKEN") or "").strip(),
        twilio_api_key_sid=(env.get("TWILIO_API_KEY_SID") or "").strip(),
        twilio_api_key_secret=(env.get("TWILIO_API_KEY_SECRET") or "").strip(),
        twilio_enable_line_type=_get_bool(env, "TWILIO_ENABLE_LINE_TYPE", False),
    )

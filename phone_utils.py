"""Phone-number parsing, normalisation and LOCAL numbering-plan validation.

Everything here is inferred locally from the offline `phonenumbers` metadata.
Nothing in this module contacts the network, and nothing here can tell whether
a SIM is active or who owns a number.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Optional

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat, PhoneNumberType
from phonenumbers import ValidationResult, geocoder

MAX_INPUT_LENGTH = 40
MAX_DIGITS = 17  # E.164 allows 15 digits; allow a little for "00" style prefixes
_BULK_SEPARATORS = re.compile(r"[\n\r\t;,|/]")
_ALLOWED_INPUT = re.compile(r"^\+?[\d\s().\-]+$")

_TYPE_LABELS = {
    PhoneNumberType.FIXED_LINE: "Fixed line",
    PhoneNumberType.MOBILE: "Mobile",
    PhoneNumberType.FIXED_LINE_OR_MOBILE: "Fixed line or mobile",
    PhoneNumberType.TOLL_FREE: "Toll-free",
    PhoneNumberType.PREMIUM_RATE: "Premium rate",
    PhoneNumberType.SHARED_COST: "Shared cost",
    PhoneNumberType.VOIP: "VoIP",
    PhoneNumberType.PERSONAL_NUMBER: "Personal number",
    PhoneNumberType.PAGER: "Pager",
    PhoneNumberType.UAN: "Universal access number",
    PhoneNumberType.VOICEMAIL: "Voicemail access",
    PhoneNumberType.UNKNOWN: "Unknown",
}

_REASON_TEXT = {
    ValidationResult.IS_POSSIBLE: "The length is plausible for this numbering plan.",
    ValidationResult.IS_POSSIBLE_LOCAL_ONLY: (
        "Only plausible as a local number without an area code; include the full number."
    ),
    ValidationResult.INVALID_COUNTRY_CODE: "The country calling code is not recognised.",
    ValidationResult.TOO_SHORT: "The number is too short for this numbering plan.",
    ValidationResult.TOO_LONG: "The number is too long for this numbering plan.",
    ValidationResult.INVALID_LENGTH: "The length does not match any known pattern.",
}


class PhoneParseError(ValueError):
    """Input could not be turned into a phone number. Message is safe to show to users."""

    def __init__(self, code: str, user_message: str) -> None:
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message


@dataclass(frozen=True)
class PhoneInfo:
    """Locally inferred facts about a number. NOT proof of ownership or activity."""

    e164: str
    international: str
    national: str
    country_calling_code: int
    input_region: str
    region: Optional[str]            # ISO code, only for numbers that validate
    country_name: Optional[str]
    area_description: Optional[str]  # coarse numbering-plan area, not a live location
    number_type: str
    is_possible: bool
    possibility_reason: str
    is_valid: bool


def normalise_country_code(code: str) -> str:
    """Return an upper-case ISO 3166-1 alpha-2 code supported by `phonenumbers`."""
    value = (code or "").strip().upper()
    if value == "UK":
        raise PhoneParseError("bad_country", "Use GB for the United Kingdom (ISO code).")
    if len(value) != 2 or not value.isalpha() or value not in phonenumbers.SUPPORTED_REGIONS:
        raise PhoneParseError(
            "bad_country",
            "Unsupported or invalid country code. Use a 2-letter ISO code such as IN, US or GB.",
        )
    return value


def mask_number(e164: str) -> str:
    """Return a log-safe version of a number (never log full numbers)."""
    if len(e164) <= 6:
        return "***"
    return e164[:3] + "*" * (len(e164) - 5) + e164[-2:]


def escape_html(value: object) -> str:
    """Escape untrusted text for Telegram HTML parse mode."""
    return html.escape(str(value), quote=False)


def parse_phone_number(raw: str, default_region: str = "IN") -> PhoneInfo:
    """Parse ONE phone number and return locally inferred metadata."""
    text = (raw or "").strip()
    if not text:
        raise PhoneParseError("empty", "Please send a phone number.")
    if len(text) > MAX_INPUT_LENGTH:
        raise PhoneParseError(
            "too_long", "That input is too long. Send exactly one phone number; bulk lookup is not supported."
        )
    if _BULK_SEPARATORS.search(text):
        raise PhoneParseError(
            "bulk", "Bulk input is not supported. Send exactly one phone number per message."
        )
    if not _ALLOWED_INPUT.fullmatch(text):
        raise PhoneParseError(
            "bad_chars",
            "Use digits with an optional leading +, spaces, hyphens, dots or parentheses. "
            "Send only one number.",
        )
    digits = sum(ch.isdigit() for ch in text)
    if digits == 0:
        raise PhoneParseError("no_digits", "I could not find any digits in that message.")
    if digits > MAX_DIGITS:
        raise PhoneParseError(
            "too_many_digits",
            "That has too many digits for one phone number. Bulk lookup is not supported.",
        )

    region = normalise_country_code(default_region)
    try:
        number = phonenumbers.parse(text, region)
    except NumberParseException as exc:
        if exc.error_type == NumberParseException.INVALID_COUNTRY_CODE:
            msg = "Missing or invalid country code. Start with + and the country code, or set /country."
        elif exc.error_type in (NumberParseException.TOO_SHORT_NSN, NumberParseException.TOO_SHORT_AFTER_IDD):
            msg = "That number is too short."
        elif exc.error_type == NumberParseException.TOO_LONG:
            msg = "That number is too long."
        else:
            msg = "That does not look like a phone number."
        raise PhoneParseError("parse_error", msg) from exc

    return _build_info(number, region)


def _build_info(number: phonenumbers.PhoneNumber, input_region: str) -> PhoneInfo:
    reason = phonenumbers.is_possible_number_with_reason(number)
    is_possible = reason == ValidationResult.IS_POSSIBLE
    is_valid = phonenumbers.is_valid_number(number)

    region: Optional[str] = None
    country_name: Optional[str] = None
    area: Optional[str] = None
    number_type = "Unknown"
    if is_valid:
        region = phonenumbers.region_code_for_number(number)
        country_name = geocoder.country_name_for_number(number, "en") or None
        description = geocoder.description_for_number(number, "en") or None
        area = description if description and description != country_name else None
        number_type = _TYPE_LABELS.get(phonenumbers.number_type(number), "Unknown")

    return PhoneInfo(
        e164=phonenumbers.format_number(number, PhoneNumberFormat.E164),
        international=phonenumbers.format_number(number, PhoneNumberFormat.INTERNATIONAL),
        national=phonenumbers.format_number(number, PhoneNumberFormat.NATIONAL),
        country_calling_code=number.country_code,
        input_region=input_region,
        region=region,
        country_name=country_name,
        area_description=area,
        number_type=number_type,
        is_possible=is_possible,
        possibility_reason=_REASON_TEXT.get(reason, "Not a possible number."),
        is_valid=is_valid,
    )

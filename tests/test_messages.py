import dataclasses
from datetime import datetime, timezone

import phonenumbers
from phonenumbers import PhoneNumberFormat, PhoneNumberType

from messages import build_result_message
from phone_utils import parse_phone_number
from providers.base import ProviderResult

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def valid_info():
    num = phonenumbers.example_number_for_type("IN", PhoneNumberType.MOBILE)
    return parse_phone_number(phonenumbers.format_number(num, PhoneNumberFormat.E164), "IN")


def test_local_message_never_claims_activity_or_identity():
    text = build_result_message(
        valid_info(), ProviderResult("LOCAL", False), provider_display="Local", now=NOW
    )
    assert "Not checked" in text
    assert "2026-01-02 03:04:05 UTC" in text
    assert "not proof of ownership" in text
    assert "not sent to any external service" in text
    assert "Carrier:" not in text


def test_provider_none_values_show_not_available():
    result = ProviderResult("TWILIO", True, valid=True, line_type_requested=True)
    text = build_result_message(valid_info(), result, provider_display="Twilio Lookup v2", now=NOW)
    assert "Line type: Not available" in text
    assert "Carrier: Not available" in text
    assert "was sent" in text


def test_line_type_not_requested_is_explicit():
    result = ProviderResult("TWILIO", True, valid=True, line_type_requested=False)
    text = build_result_message(valid_info(), result, provider_display="Twilio Lookup v2", now=NOW)
    assert "Not requested" in text


def test_untrusted_text_is_html_escaped():
    info = dataclasses.replace(valid_info(), area_description="<script>alert(1)</script>")
    result = ProviderResult("TWILIO", True, valid=True, line_type_requested=True, carrier_name="<b>X</b>")
    text = build_result_message(info, result, provider_display="Twilio Lookup v2", now=NOW)
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert "<b>X</b>" not in text and "&lt;b&gt;X&lt;/b&gt;" in text


def test_provider_error_message_still_shows_local_results():
    text = build_result_message(
        valid_info(),
        ProviderResult("LOCAL", False),
        provider_display="Twilio Lookup v2",
        provider_error="The lookup provider did not respond in time.",
        now=NOW,
    )
    assert "External lookup failed" in text
    assert "E.164" in text

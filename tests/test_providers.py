import asyncio

import httpx
import pytest

from config import load_settings
from providers import LocalProvider, TwilioLookupProvider, create_provider
from providers.base import (
    ProviderAuthError,
    ProviderConfigError,
    ProviderError,
    ProviderNetworkError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

SID = "AC" + "0" * 32
NUMBER = "+919876543210"
TOKEN = "123456789:" + "A" * 35

# Fixtures below exist only in tests (they mimic the documented response shape).
GOOD = {
    "phone_number": NUMBER,
    "valid": True,
    "validation_errors": None,
    "line_type_intelligence": {
        "type": "mobile",
        "carrier_name": "Example Carrier",
        "error_code": None,
        "mobile_country_code": "404",
        "mobile_network_code": "10",
    },
}


def run_lookup(handler, *, e164=NUMBER, **kwargs):
    """Run one lookup against a mocked transport. No real network access."""
    options = dict(enable_line_type=True, max_retries=2, backoff_seconds=0)
    options.update(kwargs)

    async def go():
        provider = TwilioLookupProvider(SID, SID, "secret", transport=httpx.MockTransport(handler), **options)
        try:
            return await provider.lookup(e164)
        finally:
            await provider.aclose()

    return asyncio.run(go())


def json_handler(payload, status=200):
    return lambda request: httpx.Response(status, json=payload)


def test_success_with_line_type_uses_documented_endpoint_and_fields():
    seen = {}

    def handler(request):
        seen["raw_path"] = request.url.raw_path
        seen["fields"] = request.url.params.get("Fields")
        seen["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json=GOOD)

    result = run_lookup(handler)
    assert seen["raw_path"].startswith(b"/v2/PhoneNumbers/%2B919876543210")
    assert seen["fields"] == "line_type_intelligence"
    assert seen["auth"].startswith("Basic ")
    assert result.external and result.valid is True
    assert result.line_type == "mobile"
    assert result.carrier_name == "Example Carrier"
    assert result.line_type_requested


def test_line_type_is_opt_in_and_not_requested_by_default():
    seen = {}

    def handler(request):
        seen["fields"] = request.url.params.get("Fields")
        return httpx.Response(200, json=GOOD)

    result = run_lookup(handler, enable_line_type=False)
    assert seen["fields"] is None
    assert result.line_type is None and result.carrier_name is None
    assert not result.line_type_requested


def test_null_fields_stay_none_and_are_never_fabricated():
    payload = {"valid": True, "line_type_intelligence": None}
    result = run_lookup(json_handler(payload))
    assert result.line_type is None
    assert result.carrier_name is None


def test_line_type_error_code_is_reported():
    payload = {
        "valid": True,
        "line_type_intelligence": {"type": None, "carrier_name": None, "error_code": 60600},
    }
    result = run_lookup(json_handler(payload))
    assert result.line_type is None
    assert result.line_type_error_code == 60600


def test_invalid_number_from_provider_is_reported_as_invalid():
    payload = {"valid": False, "validation_errors": ["TOO_SHORT"], "line_type_intelligence": None}
    result = run_lookup(json_handler(payload))
    assert result.valid is False
    assert result.validation_errors == ("TOO_SHORT",)


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_failure(status):
    with pytest.raises(ProviderAuthError):
        run_lookup(json_handler({}, status))


def test_not_found():
    with pytest.raises(ProviderNotFoundError):
        run_lookup(json_handler({}, 404))


def test_rate_limit_is_not_retried_and_reads_retry_after():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "30"}, json={})

    with pytest.raises(ProviderRateLimitError) as exc:
        run_lookup(handler)
    assert exc.value.retry_after == 30
    assert len(calls) == 1


def test_server_errors_are_retried_a_bounded_number_of_times():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503)

    with pytest.raises(ProviderUnavailableError):
        run_lookup(handler, max_retries=2)
    assert len(calls) == 3


def test_transient_failure_then_success():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500) if len(calls) == 1 else httpx.Response(200, json=GOOD)

    assert run_lookup(handler).valid is True
    assert len(calls) == 2


def test_timeout_is_retried_then_reported():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(ProviderTimeoutError):
        run_lookup(handler, max_retries=2)
    assert len(calls) == 3


def test_network_error():
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(ProviderNetworkError):
        run_lookup(handler, max_retries=0)


def test_retry_count_is_capped():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500)

    with pytest.raises(ProviderUnavailableError):
        run_lookup(handler, max_retries=1000)
    assert len(calls) == 6  # 1 attempt + 5 (cap)


@pytest.mark.parametrize(
    "bad_payload",
    [
        ["not", "a", "dict"],
        {"phone_number": NUMBER},                                   # missing "valid"
        {"valid": "yes"},                                           # wrong type
        {"valid": True, "validation_errors": {"a": 1}},             # wrong type
        {"valid": True, "validation_errors": [1, 2]},               # wrong item type
        {"valid": True, "line_type_intelligence": "mobile"},        # wrong type
        {"valid": True, "line_type_intelligence": {"type": ["x"]}}, # wrong inner type
        {"valid": True, "line_type_intelligence": {"error_code": "60600"}},
    ],
)
def test_malformed_payloads_are_rejected(bad_payload):
    with pytest.raises(ProviderResponseError):
        run_lookup(json_handler(bad_payload))


def test_non_json_body_is_rejected():
    with pytest.raises(ProviderResponseError):
        run_lookup(lambda request: httpx.Response(200, content=b"<html>oops</html>"))


def test_unexpected_status_code():
    with pytest.raises(ProviderResponseError):
        run_lookup(json_handler({}, 418))


@pytest.mark.parametrize("bad", ["12345", "919876543210", "+0123456789", "", "+91 98765 43210"])
def test_provider_rejects_non_e164_input_without_network(bad):
    def handler(request):
        raise AssertionError("network must not be used")

    with pytest.raises(ProviderError):
        run_lookup(handler, e164=bad)


@pytest.mark.parametrize(
    "sid,user,secret",
    [("", "u", "s"), ("XX123", "u", "s"), (SID, "", "s"), (SID, "u", "")],
)
def test_missing_or_invalid_credentials(sid, user, secret):
    with pytest.raises(ProviderConfigError):
        TwilioLookupProvider(sid, user, secret)


def test_factory_local_needs_no_credentials():
    settings = load_settings({"LOOKUP_PROVIDER": "LOCAL"}, require_token=False)
    provider = create_provider(settings)
    assert isinstance(provider, LocalProvider)
    assert provider.sends_data_externally is False


def test_factory_twilio_without_credentials_fails_cleanly():
    settings = load_settings({"LOOKUP_PROVIDER": "TWILIO"}, require_token=False)
    with pytest.raises(ProviderConfigError):
        create_provider(settings)


def test_factory_twilio_with_account_token():
    env = {"LOOKUP_PROVIDER": "TWILIO", "TWILIO_ACCOUNT_SID": SID, "TWILIO_AUTH_TOKEN": "tok"}
    provider = create_provider(load_settings(env, require_token=False))
    assert isinstance(provider, TwilioLookupProvider)
    assert provider.sends_data_externally is True
    asyncio.run(provider.aclose())


def test_factory_twilio_with_api_key():
    env = {
        "LOOKUP_PROVIDER": "TWILIO",
        "TWILIO_ACCOUNT_SID": SID,
        "TWILIO_API_KEY_SID": "SK" + "1" * 32,
        "TWILIO_API_KEY_SECRET": "secret",
    }
    provider = create_provider(load_settings(env, require_token=False))
    assert isinstance(provider, TwilioLookupProvider)
    asyncio.run(provider.aclose())


def test_local_provider_returns_no_external_data():
    result = asyncio.run(LocalProvider().lookup(NUMBER))
    assert result.external is False
    assert result.valid is None and result.carrier_name is None and result.line_type is None


def test_local_provider_rejects_bad_format():
    with pytest.raises(ProviderError):
        asyncio.run(LocalProvider().lookup("not-a-number"))


def test_secrets_are_not_in_settings_repr():
    env = {
        "TELEGRAM_BOT_TOKEN": TOKEN,
        "TWILIO_ACCOUNT_SID": SID,
        "TWILIO_AUTH_TOKEN": "super-secret-token",
    }
    text = repr(load_settings(env))
    assert "super-secret-token" not in text and TOKEN not in text

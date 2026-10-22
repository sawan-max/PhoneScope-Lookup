import pytest

from config import ConfigError, load_settings

TOKEN = "123456789:" + "A" * 35


def test_defaults():
    s = load_settings({"TELEGRAM_BOT_TOKEN": TOKEN})
    assert s.provider_mode == "LOCAL"
    assert s.default_country == "IN"
    assert s.rate_limit_max_requests == 5
    assert s.twilio_enable_line_type is False
    assert s.allowed_user_ids == frozenset()


def test_missing_token():
    with pytest.raises(ConfigError):
        load_settings({})


@pytest.mark.parametrize("token", ["your-bot-token-here", "abc", "123:short"])
def test_invalid_token_format(token):
    with pytest.raises(ConfigError):
        load_settings({"TELEGRAM_BOT_TOKEN": token})


def test_token_not_required_for_local_testing():
    assert load_settings({}, require_token=False).telegram_token == ""


def test_invalid_values():
    base = {"TELEGRAM_BOT_TOKEN": TOKEN}
    for extra in [
        {"LOOKUP_PROVIDER": "FOO"},
        {"DEFAULT_COUNTRY": "ZZ"},
        {"RATE_LIMIT_MAX_REQUESTS": "abc"},
        {"RATE_LIMIT_MAX_REQUESTS": "0"},
        {"HTTP_MAX_RETRIES": "99"},
        {"HTTP_TIMEOUT_SECONDS": "x"},
        {"TWILIO_ENABLE_LINE_TYPE": "maybe"},
        {"ALLOWED_USER_IDS": "12,abc"},
    ]:
        with pytest.raises(ConfigError):
            load_settings({**base, **extra})


def test_parsed_values():
    s = load_settings(
        {
            "TELEGRAM_BOT_TOKEN": TOKEN,
            "LOOKUP_PROVIDER": "twilio",
            "DEFAULT_COUNTRY": "us",
            "ALLOWED_USER_IDS": "1, 2",
            "TWILIO_ENABLE_LINE_TYPE": "true",
        }
    )
    assert s.provider_mode == "TWILIO"
    assert s.default_country == "US"
    assert s.allowed_user_ids == frozenset({1, 2})
    assert s.twilio_enable_line_type is True

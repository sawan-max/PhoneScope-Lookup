import dataclasses

import phonenumbers
import pytest
from phonenumbers import PhoneNumberFormat, PhoneNumberType

from phone_utils import (
    PhoneParseError,
    escape_html,
    mask_number,
    normalise_country_code,
    parse_phone_number,
)


def example(region, ntype=PhoneNumberType.MOBILE):
    """A number guaranteed valid by libphonenumber's own metadata."""
    return phonenumbers.example_number_for_type(region, ntype)


def e164_of(number):
    return phonenumbers.format_number(number, PhoneNumberFormat.E164)


@pytest.fixture
def indian():
    num = example("IN")
    return num, e164_of(num), str(num.national_number)


def test_indian_number_all_common_formats_normalise_identically(indian):
    num, e164, nsn = indian
    cc = num.country_code
    variants = [
        e164,
        f"+{cc} {nsn[:5]} {nsn[5:]}",
        f"+{cc}-{nsn[:5]}-{nsn[5:]}",
        f"+{cc} ({nsn[:3]}) {nsn[3:]}",
        phonenumbers.format_number(num, PhoneNumberFormat.NATIONAL),
        nsn,
    ]
    for text in variants:
        info = parse_phone_number(text, "IN")
        assert info.e164 == e164, text
        assert info.is_valid and info.is_possible
        assert info.region == "IN"
        assert info.country_calling_code == 91


def test_indian_result_has_expected_fields(indian):
    _, e164, _ = indian
    info = parse_phone_number(e164, "IN")
    assert info.international.startswith("+91 ")
    assert info.national
    assert info.country_name == "India"
    assert info.number_type in {"Mobile", "Fixed line or mobile"}


@pytest.mark.parametrize("region,cc", [("US", 1), ("GB", 44), ("DE", 49), ("AU", 61)])
def test_international_numbers(region, cc):
    num = example(region)
    info = parse_phone_number(e164_of(num), "IN")  # explicit + overrides default region
    assert info.is_valid
    assert info.region == region
    assert info.country_calling_code == cc


def test_missing_country_code_uses_default_region(indian):
    num, _, nsn = indian
    assert parse_phone_number(nsn, "IN").country_calling_code == 91
    assert parse_phone_number(nsn, "US").country_calling_code == 1


def test_clearly_invalid_number_is_not_possible_or_valid():
    info = parse_phone_number("12345", "IN")
    assert not info.is_possible
    assert not info.is_valid
    assert info.region is None
    assert info.number_type == "Unknown"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "hello",
        "98765abcde",
        "+",
        "+91 98765 43210, +91 98765 43211",
        "+1 650 253 0000\n+1 650 253 0001",
        "+1 650 253 0000; +1 650 253 0001",
        "1" * 30,
        "9" * 20,
        "+999 123456",
    ],
)
def test_invalid_and_bulk_input_is_rejected(bad):
    with pytest.raises(PhoneParseError) as exc:
        parse_phone_number(bad, "IN")
    assert exc.value.user_message


def test_bulk_input_reports_bulk_message():
    with pytest.raises(PhoneParseError) as exc:
        parse_phone_number("+911234567890,+911234567891", "IN")
    assert exc.value.code == "bulk"


def test_unsupported_default_region_is_rejected(indian):
    _, e164, _ = indian
    with pytest.raises(PhoneParseError):
        parse_phone_number(e164, "XX")


def test_normalise_country_code():
    assert normalise_country_code(" in ") == "IN"
    assert normalise_country_code("us") == "US"
    for bad in ["", "XX", "IND", "1", "UK", "I N"]:
        with pytest.raises(PhoneParseError):
            normalise_country_code(bad)


def test_mask_number_hides_middle_digits():
    masked = mask_number("+919876543210")
    assert masked.startswith("+91") and masked.endswith("10")
    assert "98765" not in masked
    assert mask_number("+123") == "***"


def test_escape_html():
    assert escape_html("<b>&") == "&lt;b&gt;&amp;"


def test_parse_info_is_immutable(indian):
    _, e164, _ = indian
    info = parse_phone_number(e164, "IN")
    with pytest.raises(dataclasses.FrozenInstanceError):
        info.e164 = "+1"

"""Lookup-provider interface, result type and error hierarchy."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Tuple

E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


class ProviderError(Exception):
    """Base class. `user_message` is safe to show to end users (never contains secrets)."""

    default_message = "The lookup provider returned an error."

    def __init__(self, message: Optional[str] = None) -> None:
        self.user_message = message or self.default_message
        super().__init__(self.user_message)


class ProviderConfigError(ProviderError):
    default_message = "The lookup provider is not configured correctly."


class ProviderAuthError(ProviderError):
    default_message = "The lookup provider rejected the configured credentials."


class ProviderRateLimitError(ProviderError):
    default_message = "The lookup provider is rate limiting requests. Try again later."

    def __init__(self, message: Optional[str] = None, retry_after: Optional[int] = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderTimeoutError(ProviderError):
    default_message = "The lookup provider did not respond in time."


class ProviderNetworkError(ProviderError):
    default_message = "Could not reach the lookup provider (network error)."


class ProviderUnavailableError(ProviderError):
    default_message = "The lookup provider is temporarily unavailable."


class ProviderNotFoundError(ProviderError):
    default_message = "The lookup provider does not recognise or support this number."


class ProviderResponseError(ProviderError):
    default_message = "The lookup provider returned an unexpected or malformed response."


@dataclass(frozen=True)
class ProviderResult:
    """Only values genuinely returned by a provider. None means 'not available'."""

    provider: str
    external: bool
    valid: Optional[bool] = None
    validation_errors: Tuple[str, ...] = ()
    line_type: Optional[str] = None
    carrier_name: Optional[str] = None
    mobile_country_code: Optional[str] = None
    mobile_network_code: Optional[str] = None
    line_type_requested: bool = False
    line_type_error_code: Optional[int] = None


class LookupProvider(ABC):
    name: str = "BASE"
    display_name: str = "Base provider"
    sends_data_externally: bool = False

    @abstractmethod
    async def lookup(self, e164: str) -> ProviderResult:
        """Look up a number that is already normalised to E.164."""

    async def aclose(self) -> None:
        """Release any resources (HTTP clients etc.)."""
        return None


def ensure_e164(value: str) -> str:
    if not isinstance(value, str) or not E164_RE.fullmatch(value):
        raise ProviderError("The number is not in valid E.164 format.")
    return value

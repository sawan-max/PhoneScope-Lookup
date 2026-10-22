"""Provider package and factory."""
from __future__ import annotations

from config import Settings

from .base import LookupProvider, ProviderConfigError, ProviderError, ProviderResult
from .local_provider import LocalProvider
from .twilio_provider import TwilioLookupProvider

__all__ = [
    "LookupProvider",
    "ProviderResult",
    "ProviderError",
    "LocalProvider",
    "TwilioLookupProvider",
    "create_provider",
]


def create_provider(settings: Settings) -> LookupProvider:
    """Build the provider selected by LOOKUP_PROVIDER."""
    if settings.provider_mode == "LOCAL":
        return LocalProvider()
    if settings.provider_mode == "TWILIO":
        if settings.twilio_api_key_sid and settings.twilio_api_key_secret:
            user, secret = settings.twilio_api_key_sid, settings.twilio_api_key_secret
        elif settings.twilio_auth_token:
            user, secret = settings.twilio_account_sid, settings.twilio_auth_token
        else:
            raise ProviderConfigError(
                "TWILIO mode needs TWILIO_ACCOUNT_SID plus either TWILIO_AUTH_TOKEN or "
                "TWILIO_API_KEY_SID and TWILIO_API_KEY_SECRET."
            )
        return TwilioLookupProvider(
            account_sid=settings.twilio_account_sid,
            auth_user=user,
            auth_secret=secret,
            enable_line_type=settings.twilio_enable_line_type,
            timeout=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
        )
    raise ProviderConfigError(f"Unknown provider mode: {settings.provider_mode}")

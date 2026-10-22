"""Optional Twilio Lookup v2 provider.

Endpoint: GET https://lookups.twilio.com/v2/PhoneNumbers/{E.164}?Fields=line_type_intelligence
Line-type/carrier data is requested only when explicitly enabled, because it may be chargeable.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from .base import (
    LookupProvider,
    ProviderAuthError,
    ProviderConfigError,
    ProviderError,
    ProviderNetworkError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderResult,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ensure_e164,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://lookups.twilio.com/v2/PhoneNumbers/"
LINE_TYPE_FIELD = "line_type_intelligence"
MAX_RETRIES_CAP = 5


def _optional_text(container: Dict[str, Any], key: str) -> Optional[str]:
    value = container.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ProviderResponseError()
    text = str(value).strip()
    return text or None


class TwilioLookupProvider(LookupProvider):
    name = "TWILIO"
    display_name = "Twilio Lookup v2"
    sends_data_externally = True

    def __init__(
        self,
        account_sid: str,
        auth_user: str,
        auth_secret: str,
        *,
        enable_line_type: bool = False,
        timeout: float = 10.0,
        max_retries: int = 2,
        backoff_seconds: float = 0.5,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        if not account_sid or not account_sid.startswith("AC"):
            raise ProviderConfigError("TWILIO_ACCOUNT_SID is missing or invalid (it should start with AC).")
        if not auth_user or not auth_secret:
            raise ProviderConfigError(
                "Twilio credentials are missing. Set TWILIO_AUTH_TOKEN, or "
                "TWILIO_API_KEY_SID and TWILIO_API_KEY_SECRET."
            )
        self._enable_line_type = enable_line_type
        self._max_retries = min(max(int(max_retries), 0), MAX_RETRIES_CAP)
        self._backoff = max(float(backoff_seconds), 0.0)
        self._client = httpx.AsyncClient(
            auth=(auth_user, auth_secret),
            timeout=httpx.Timeout(timeout),
            headers={"Accept": "application/json"},
            follow_redirects=False,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def lookup(self, e164: str) -> ProviderResult:
        ensure_e164(e164)
        url = BASE_URL + quote(e164, safe="")
        params = {"Fields": LINE_TYPE_FIELD} if self._enable_line_type else None
        response = await self._get_with_retries(url, params)
        return self._parse(response)

    async def _get_with_retries(self, url: str, params: Optional[Dict[str, str]]) -> httpx.Response:
        last_error: ProviderError = ProviderError()
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.get(url, params=params)
            except httpx.TimeoutException:
                last_error = ProviderTimeoutError()
            except httpx.TransportError:
                last_error = ProviderNetworkError()
            else:
                if response.status_code < 500:
                    return response
                last_error = ProviderUnavailableError()
            logger.warning("Twilio request failed (attempt %d): %s", attempt + 1, type(last_error).__name__)
            if attempt < self._max_retries and self._backoff:
                await asyncio.sleep(self._backoff * (2 ** attempt))
        raise last_error

    def _parse(self, response: httpx.Response) -> ProviderResult:
        status = response.status_code
        if status in (401, 403):
            raise ProviderAuthError()
        if status == 404:
            raise ProviderNotFoundError()
        if status == 429:
            retry_after = response.headers.get("Retry-After", "")
            raise ProviderRateLimitError(retry_after=int(retry_after) if retry_after.isdigit() else None)
        if status != 200:
            raise ProviderResponseError(f"The lookup provider returned HTTP {status}.")

        try:
            payload = response.json()
        except ValueError:
            raise ProviderResponseError() from None
        if not isinstance(payload, dict) or "valid" not in payload:
            raise ProviderResponseError()

        valid = payload["valid"]
        if valid is not None and not isinstance(valid, bool):
            raise ProviderResponseError()

        errors = payload.get("validation_errors")
        if errors is None:
            errors = []
        if not isinstance(errors, list) or not all(isinstance(e, str) for e in errors):
            raise ProviderResponseError()

        line_type = carrier = mcc = mnc = None
        error_code: Optional[int] = None
        if self._enable_line_type:
            lti = payload.get(LINE_TYPE_FIELD)
            if lti is not None:
                if not isinstance(lti, dict):
                    raise ProviderResponseError()
                line_type = _optional_text(lti, "type")
                carrier = _optional_text(lti, "carrier_name")
                mcc = _optional_text(lti, "mobile_country_code")
                mnc = _optional_text(lti, "mobile_network_code")
                code = lti.get("error_code")
                if code is not None:
                    if isinstance(code, bool) or not isinstance(code, int):
                        raise ProviderResponseError()
                    error_code = code

        return ProviderResult(
            provider=self.name,
            external=True,
            valid=valid,
            validation_errors=tuple(errors),
            line_type=line_type,
            carrier_name=carrier,
            mobile_country_code=mcc,
            mobile_network_code=mnc,
            line_type_requested=self._enable_line_type,
            line_type_error_code=error_code,
        )

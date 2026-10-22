"""LOCAL provider: no network, no credentials, no cost."""
from __future__ import annotations

from .base import LookupProvider, ProviderResult, ensure_e164


class LocalProvider(LookupProvider):
    """Returns no external data. Local facts come from phone_utils (offline metadata)."""

    name = "LOCAL"
    display_name = "Local numbering data (phonenumbers)"
    sends_data_externally = False

    async def lookup(self, e164: str) -> ProviderResult:
        ensure_e164(e164)
        return ProviderResult(provider=self.name, external=False)

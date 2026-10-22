"""User-facing Telegram messages (HTML parse mode). No Telegram imports, so it is unit-testable."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from phone_utils import PhoneInfo, escape_html as esc
from providers.base import ProviderResult

NA = "Not available"


def _na(value: Optional[str]) -> str:
    return esc(value) if value else NA


def start_text(default_country: str, provider_display: str, external: bool) -> str:
    where = (
        f"Optional provider lookups use <b>{esc(provider_display)}</b> (external service)."
        if external
        else "This bot is in <b>LOCAL</b> mode: nothing is sent to any external service."
    )
    return (
        "<b>👋 Welcome to PhoneScope</b>\n\n"
        "I check <b>one phone number at a time</b> and report numbering-plan validation and "
        "formatting.\n\n"
        "<b>What I can do</b>\n"
        "• Normalise to E.164 and show international/national formats\n"
        "• Report whether the number is <i>possible</i> and <i>valid</i> for its numbering plan\n"
        "• Show the calling code, numbering region and line category inferred from public numbering data\n"
        f"• {where}\n\n"
        "<b>What I cannot do</b>\n"
        "• Identify the owner, name, address or live location\n"
        "• Confirm a SIM is active or reachable\n"
        "• Access Aadhaar, bank, WhatsApp, SMS, call records or social media\n"
        "• Do bulk lookups\n\n"
        f"<b>Example</b>\n<code>+91 98765 43210</code> or just <code>98765 43210</code> "
        f"(default country: {esc(default_country)}; change with <code>/country US</code>)\n\n"
        "Use /help for commands and /privacy for privacy details."
    )


def help_text() -> str:
    return (
        "<b>Commands</b>\n"
        "/start - Introduction and limitations\n"
        "/help - This list\n"
        "/lookup - Prompt for a number to check\n"
        "/country XX - Set your default country, e.g. <code>/country IN</code>\n"
        "/privacy - How data is handled\n"
        "/reset - Forget your settings and consent\n\n"
        "You can also just send a phone number as a normal message."
    )


def privacy_text(provider_display: str, external: bool, line_type_enabled: bool) -> str:
    base = (
        "<b>🔒 Privacy</b>\n"
        "• Numbers and results are not stored in a database and full numbers are not logged.\n"
        "• Your country setting and consent live in memory only and vanish when the bot restarts "
        "(or when you send /reset).\n"
    )
    if external:
        extra = (
            f"• <b>External provider:</b> numbers that pass local checks are sent to "
            f"<b>{esc(provider_display)}</b>, which has its own privacy policy and retention rules.\n"
        )
        if line_type_enabled:
            extra += "• Carrier / line-type lookup is enabled and may be chargeable to the bot operator.\n"
        else:
            extra += "• Carrier / line-type lookup is disabled (opt-in).\n"
    else:
        extra = "• LOCAL mode: numbers are never sent to a third party.\n"
    return base + extra


def consent_text(provider_display: str, external: bool) -> str:
    notice = (
        f"\n\n⚠️ <b>External provider notice:</b> numbers you send are transmitted to "
        f"<b>{esc(provider_display)}</b>. Do not send a number if you are not comfortable with that."
        if external
        else "\n\nIn LOCAL mode your number is processed on this bot only."
    )
    return (
        "<b>Before you continue</b>\n"
        "Please confirm that you have a lawful reason to check this number and that you will use "
        "the result responsibly (no harassment, stalking or unlawful profiling). Validation does "
        "not identify a person." + notice
    )


def build_result_message(
    info: PhoneInfo,
    result: ProviderResult,
    *,
    provider_display: str,
    provider_error: Optional[str] = None,
    external_skipped: bool = False,
    now: Optional[datetime] = None,
) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S UTC")
    yes_no = lambda flag: "✅ Yes" if flag else "❌ No"  # noqa: E731

    region_parts = [p for p in (info.region, info.country_name) if p]
    region_text = " - ".join(region_parts) if region_parts else NA

    lines = [
        "<b>📞 PhoneScope result</b>",
        "",
        "<b>Number (formatted locally)</b>",
        f"• E.164: <code>{esc(info.e164)}</code>",
        f"• International: {esc(info.international)}",
        f"• National: {_na(info.national)}",
        f"• Calling code: +{info.country_calling_code}",
        f"• Numbering region: {esc(region_text) if region_parts else NA}",
        "",
        "<b>Local numbering-plan checks (inferred offline)</b>",
        f"• Possible number: {yes_no(info.is_possible)}",
        f"  <i>{esc(info.possibility_reason)}</i>",
        f"• Valid numbering-plan number: {yes_no(info.is_valid)}",
        "  <i>Matches the public numbering-plan rules. This is not proof of an active SIM.</i>",
        f"• Line category (inferred): {_na(info.number_type if info.is_valid else None)}",
        f"• Numbering-plan area (approximate): {_na(info.area_description)}",
        "  <i>Not a live or current location.</i>",
        "• Confirmed active/reachable: ❔ Not checked",
        "  <i>This bot cannot determine whether a number is in service.</i>",
        "",
    ]

    if result.external:
        lines.append(f"<b>Provider data - {esc(provider_display)} (external)</b>")
        if result.valid is None:
            valid_text = NA
        else:
            valid_text = "Valid" if result.valid else "Invalid"
        lines.append(f"• Provider validation: {valid_text}")
        if result.validation_errors:
            lines.append(f"• Validation errors: {esc(', '.join(result.validation_errors))}")
        if not result.line_type_requested:
            lines.append("• Line type / carrier: Not requested (opt-in is disabled)")
        else:
            lines.append(f"• Line type: {_na(result.line_type)}")
            lines.append(f"• Carrier: {_na(result.carrier_name)}")
            if result.line_type_error_code is not None:
                lines.append(
                    f"  <i>Provider could not supply this data (error code {result.line_type_error_code}).</i>"
                )
        lines.append("")
    elif provider_error:
        lines.append(f"⚠️ <b>External lookup failed:</b> {esc(provider_error)}")
        lines.append("<i>The local results above are still shown.</i>")
        lines.append("")
    elif external_skipped:
        lines.append("ℹ️ Not sent to the external provider because it is not a possible number.")
        lines.append("")

    sent_externally = result.external or provider_error is not None
    lines.extend(
        [
            "<b>Notes</b>",
            "• Validation is not proof of ownership or active service.",
            "• Carrier data can be unavailable or outdated (e.g. after number porting).",
            "• Local facts are inferred from offline numbering data; provider data is shown only "
            "when the provider returned it.",
            (
                f"🔒 This number was sent (or an attempt was made to send it) to {esc(provider_display)}."
                if sent_externally
                else "🔒 This number was not sent to any external service."
            ),
            f"🕒 {stamp}",
        ]
    )
    return "\n".join(lines)

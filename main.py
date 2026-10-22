"""PhoneScope - Telegram bot entry point and handlers."""
from __future__ import annotations

import functools
import logging
import sys
from typing import Awaitable, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import InvalidToken, NetworkError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import messages
from config import ConfigError, Settings, load_settings
from phone_utils import PhoneParseError, escape_html, mask_number, normalise_country_code, parse_phone_number
from providers import ProviderError, ProviderResult, create_provider
from providers.base import LookupProvider
from rate_limiter import RateLimiter

logger = logging.getLogger("phonescope")

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def authorized(func: Handler) -> Handler:
    """Reject users outside ALLOWED_USER_IDS (if configured)."""

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user is None:
            return
        settings: Settings = context.bot_data["settings"]
        if settings.allowed_user_ids and user.id not in settings.allowed_user_ids:
            if update.effective_message:
                await update.effective_message.reply_text("Sorry, this bot is private.")
            return
        await func(update, context)

    return wrapper


async def _reply(update: Update, text: str, **kwargs) -> None:
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, **kwargs)


def _provider(context: ContextTypes.DEFAULT_TYPE) -> LookupProvider:
    return context.bot_data["provider"]


async def _send_consent_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    provider = _provider(context)
    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ I confirm", callback_data="consent:yes"),
            InlineKeyboardButton("✖ Cancel", callback_data="consent:no"),
        ]]
    )
    await _reply(
        update,
        messages.consent_text(provider.display_name, provider.sends_data_externally),
        reply_markup=keyboard,
    )


@authorized
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    provider = _provider(context)
    country = context.user_data.get("country", settings.default_country)
    await _reply(update, messages.start_text(country, provider.display_name, provider.sends_data_externally))
    if not context.user_data.get("consented"):
        await _send_consent_prompt(update, context)


@authorized
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, messages.help_text())


@authorized
async def cmd_privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    provider = _provider(context)
    await _reply(
        update,
        messages.privacy_text(provider.display_name, provider.sends_data_externally, settings.twilio_enable_line_type),
    )


@authorized
async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await _reply(update, "Your settings and consent have been cleared.")


@authorized
async def cmd_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get("consented"):
        await _send_consent_prompt(update, context)
        return
    await _reply(
        update,
        "Send <b>one</b> phone number, for example <code>+91 98765 43210</code>. "
        "Bulk input is not supported.",
    )


@authorized
async def cmd_country(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    if len(context.args or []) != 1:
        current = context.user_data.get("country", settings.default_country)
        await _reply(update, f"Current default country: <b>{escape_html(current)}</b>\nUsage: <code>/country IN</code>")
        return
    try:
        code = normalise_country_code(context.args[0])
    except PhoneParseError as exc:
        await _reply(update, escape_html(exc.user_message))
        return
    context.user_data["country"] = code
    await _reply(update, f"Default country set to <b>{code}</b>.")


@authorized
async def on_consent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "consent:yes":
        context.user_data["consented"] = True
        await query.edit_message_text(
            "✅ Thanks. Send me one phone number to check, for example +91 98765 43210."
        )
    else:
        context.user_data["consented"] = False
        await query.edit_message_text("No problem. I will not perform lookups until you confirm (use /lookup).")


@authorized
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    limiter: RateLimiter = context.bot_data["limiter"]
    provider = _provider(context)
    user = update.effective_user

    if not context.user_data.get("consented"):
        await _send_consent_prompt(update, context)
        return

    decision = limiter.check(user.id)
    if not decision.allowed:
        await _reply(update, f"⏳ Too many requests. Please wait about {decision.retry_after_seconds} seconds.")
        return

    country = context.user_data.get("country", settings.default_country)
    try:
        info = parse_phone_number(update.effective_message.text or "", country)
    except PhoneParseError as exc:
        await _reply(update, "❌ " + escape_html(exc.user_message))
        return

    result = ProviderResult(provider="LOCAL", external=False)
    provider_error = None
    skipped = False
    if not info.is_possible:
        skipped = provider.sends_data_externally
    else:
        try:
            result = await provider.lookup(info.e164)
        except ProviderError as exc:
            provider_error = exc.user_message
            logger.warning("Provider error %s for %s", type(exc).__name__, mask_number(info.e164))

    logger.info("Lookup %s valid=%s mode=%s", mask_number(info.e164), info.is_valid, provider.name)
    await _reply(
        update,
        messages.build_result_message(
            info,
            result,
            provider_display=provider.display_name,
            provider_error=provider_error,
            external_skipped=skipped,
        ),
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Log only the exception type: messages and URLs can contain sensitive data.
    logger.error("Unhandled error: %s", type(context.error).__name__)


async def _post_shutdown(application: Application) -> None:
    await application.bot_data["provider"].aclose()


def build_application(settings: Settings, provider: LookupProvider) -> Application:
    application = (
        Application.builder()
        .token(settings.telegram_token)
        .concurrent_updates(16)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.bot_data["settings"] = settings
    application.bot_data["provider"] = provider
    application.bot_data["limiter"] = RateLimiter(
        settings.rate_limit_max_requests, settings.rate_limit_window_seconds
    )

    private = filters.ChatType.PRIVATE
    application.add_handler(CommandHandler("start", cmd_start, filters=private))
    application.add_handler(CommandHandler("help", cmd_help, filters=private))
    application.add_handler(CommandHandler("lookup", cmd_lookup, filters=private))
    application.add_handler(CommandHandler("country", cmd_country, filters=private))
    application.add_handler(CommandHandler("privacy", cmd_privacy, filters=private))
    application.add_handler(CommandHandler("reset", cmd_reset, filters=private))
    application.add_handler(CallbackQueryHandler(on_consent, pattern=r"^consent:(yes|no)$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & private, on_text))
    application.add_error_handler(on_error)
    return application


def configure_logging() -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    # httpx logs full request URLs at INFO; Telegram URLs contain the bot token.
    for noisy in ("httpx", "httpcore", "telegram", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    configure_logging()
    try:
        settings = load_settings()
        provider = create_provider(settings)
    except (ConfigError, ProviderError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(2)

    application = build_application(settings, provider)
    logger.info("PhoneScope starting in %s mode", settings.provider_mode)
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except InvalidToken:
        print("Telegram rejected the bot token. Re-copy it from @BotFather into .env.", file=sys.stderr)
        sys.exit(3)
    except NetworkError:
        print("Could not reach Telegram. Check your internet connection or proxy.", file=sys.stderr)
        sys.exit(4)


if __name__ == "__main__":
    main()

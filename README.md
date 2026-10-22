# PhoneScope

A Telegram bot that checks **one phone number at a time** and reports numbering-plan validation and
formatting. It never claims to know who owns a number, where they are, or whether the SIM is active.

## Modes

| Mode | Cost | What you get | Data leaves the bot? |
|------|------|--------------|----------------------|
| `LOCAL` (default) | Free | E.164, international/national format, calling code, region, possible/valid status, inferred line category | No |
| `TWILIO` (optional) | Twilio pricing applies | Everything in LOCAL plus Twilio's own validation result and, if you opt in, line type and carrier name **as returned by Twilio** | Yes - to Twilio |

**Locally inferred** = computed offline from public numbering-plan data (`phonenumbers`).
**Provider-supplied** = returned by Twilio Lookup v2 and shown only if actually returned
(otherwise "Not available"). Carrier data can be missing or outdated (number porting), and validation is
not proof of ownership or active service.

## Project layout

    main.py                     Telegram handlers + entry point
    config.py                   Environment settings
    phone_utils.py              Parsing / validation (offline)
    messages.py                 Message text and result formatting
    rate_limiter.py             Per-user sliding-window limiter
    providers/base.py           Provider interface, result type, errors
    providers/local_provider.py LOCAL provider
    providers/twilio_provider.py Optional Twilio Lookup v2 provider
    tests/                      pytest suite (all external calls mocked)

## Windows setup (PowerShell + VS Code)

Prerequisite: Python 3.11, 3.12 or 3.13 from https://www.python.org/downloads/ (tick "Add python.exe to PATH").
Check with `py --version`.

### 1. Create the project folder
```powershell
mkdir C:\Projects\PhoneScope
cd C:\Projects\PhoneScope
code .
```
Copy all project files into this folder (keep the `providers` and `tests` sub-folders).

### 2. Create and activate a virtual environment
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```
If PowerShell blocks the script, run once, then activate again:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```
You should see `(.venv)` at the start of the prompt. In VS Code press `Ctrl+Shift+P`,
choose **Python: Select Interpreter**, and pick the `.venv` one.

### 3. Install requirements
```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Create the Telegram bot
1. In Telegram search for **@BotFather** (the official bot has a verified badge).
2. Send `/newbot`, choose a display name, then a username ending in `bot`.
3. BotFather replies with a token like `123456789:AA...`. Treat it like a password.
4. Create your config file and paste the token:
```powershell
Copy-Item .env.example .env
code .env
```
Set `TELEGRAM_BOT_TOKEN=<your token>` (no quotes, no spaces). Never share or commit `.env`.

### 5. Configure LOCAL mode (no paid services)
In `.env` keep:
```
LOOKUP_PROVIDER=LOCAL
DEFAULT_COUNTRY=IN
```
Optional: restrict who can use the bot with `ALLOWED_USER_IDS=123456789` (your numeric Telegram ID).

### 6. (Optional) Configure Twilio mode
1. Create an account at https://www.twilio.com and open the Console; copy the **Account SID** (starts with `AC`).
2. Console > Account > API keys & tokens > **Create API key** (Standard). Copy the **SID** (starts with `SK`)
   and the **Secret** immediately - it is shown only once.
3. Edit `.env`:
```
LOOKUP_PROVIDER=TWILIO
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_API_KEY_SID=SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_API_KEY_SECRET=your-secret
TWILIO_ENABLE_LINE_TYPE=false
```
(You can use `TWILIO_AUTH_TOKEN` instead of an API key.) Set `TWILIO_ENABLE_LINE_TYPE=true` only if you accept that
line-type/carrier lookups may be chargeable - check Twilio's current pricing first.
Numbers are then sent to Twilio; the bot tells users this.

### 7. Start the bot
```powershell
python main.py
```
Open your bot in Telegram, send `/start`, tap **I confirm**, then send `+91 98765 43210`. Stop with `Ctrl+C`.

### 8. Run the unit tests
```powershell
pytest -v
pytest tests/test_phone_utils.py -v
pytest tests/test_providers.py -v
```
Tests need no Telegram token, no Twilio account and no internet: all HTTP is mocked
(`httpx.MockTransport`). Expected result: every test reports `PASSED` and the last line reads
`N passed`. If anything fails, read the assertion message and see the troubleshooting list below.

## Commands

`/start`, `/help`, `/lookup`, `/country IN`, `/privacy`, `/reset`. Or send a number as a normal message.

## Privacy and safety design

- Numbers and results are never stored; full numbers are never logged (masked like `+91********10`).
- Consent and country are held in memory per Telegram user and cleared on restart or `/reset`.
- Only private chats are served. One number per message; commas, new lines and long input are rejected.
- Per-user rate limit (`RATE_LIMIT_MAX_REQUESTS` per `RATE_LIMIT_WINDOW_SECONDS`).
- Twilio calls use timeouts and at most `HTTP_MAX_RETRIES` retries (cap 5); 4xx and 429 are not retried.
- Third-party privacy: Twilio receives the number you submit and applies its own policy.
- Not implemented on purpose: names, addresses, live location, Aadhaar/bank data, messaging or call
  records, social-media lookups, Truecaller or scraping of any kind.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Configuration error: TELEGRAM_BOT_TOKEN is not set` | `.env` missing or in the wrong folder. It must sit next to `main.py`; the variable must be spelled exactly. |
| `TELEGRAM_BOT_TOKEN does not look valid` | Re-copy the full token from @BotFather; no quotes or spaces. |
| `Telegram rejected the bot token` | Token revoked or mistyped. In BotFather use `/token` to get a fresh one. |
| `ModuleNotFoundError: telegram / phonenumbers / httpx` | Virtual environment not active or requirements not installed: run `.\.venv\Scripts\Activate.ps1` then `pip install -r requirements.txt`. |
| `ModuleNotFoundError: config` (or `providers`) | Run commands from the project root (the folder containing `main.py`). |
| `running scripts is disabled on this system` | `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` |
| Bot starts but does not answer | Another copy is running with the same token (only one polling instance allowed), or you chatted in a group; the bot serves private chats only. |
| `Configuration error: TWILIO mode needs ...` | Fill `TWILIO_ACCOUNT_SID` and either the API key pair or `TWILIO_AUTH_TOKEN`. |
| "rejected the configured credentials" | Wrong SID/secret pair, deleted key, or account SID not matching the key. Recreate the API key. |
| "does not recognise or support this number" | Twilio could not process the number (unsupported range or format). |
| "rate limiting requests" (Twilio) | Wait and retry; reduce traffic. |
| "Too many requests" (bot) | Per-user limit reached; adjust `RATE_LIMIT_*` in `.env`. |
| "did not respond in time" | Network issue or slow provider; raise `HTTP_TIMEOUT_SECONDS` slightly. |
| Errors on Python 3.14 | Use Python 3.11-3.13 until your python-telegram-bot version supports 3.14. |

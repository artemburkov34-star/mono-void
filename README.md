# MONO CORE 4.0

> Smart Semi-Browser & OS Overlord. UI: The Void.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then fill in the keys

# Start API + UI (PWA)
python run_api.py

# Start Telegram bot
python main.py bot

# Start both
python main.py both
```

## Architecture

```
MONO_SYSTEM/
├─ core/
│  ├─ guard/         Phi-3 Mini moderation client + cache
│  ├─ settings/      Pydantic + SQLite hot-reload settings
│  ├─ resource_paths.py   PyInstaller-safe asset resolution
│  ├─ config.py, crypto.py, db.py, ai_router.py, engine.py
├─ skills/           os_master, vision, proactive, messengers, consent
├─ api/
│  ├─ middleware/    MonoGuardMiddleware (Phi-3 content moderation)
│  ├─ routes/        settings, auth (OAuth2 Google)
│  ├─ security/      JWT helpers + Depends
│  └─ server.py
├─ bot/middleware/   GuardMiddleware (aiogram 3.x)
├─ ui/               The Void (HTML/CSS/JS, PWA-ready)
├─ main.py           unified entrypoint
├─ run_api.py        FastAPI server
└─ mono_vault.db
```

## Security

* All secrets live in encrypted blobs inside `mono_vault.db` (AES-GCM).
* No hardcoded keys - `.env` only.
* Sensitive actions require explicit consent.
* `MonoGuard` (Phi-3 Mini) blocks toxic/spammy traffic on both the
  FastAPI gateway and the Telegram bot.

## MonoGuard (content moderation)

The middleware ships with a **local** Phi-3 Mini endpoint, no cloud
dependency. Configure in `.env`:

```ini
PHI3_BASE_URL=http://127.0.0.1:8080     # LM Studio / llama.cpp / vLLM
PHI3_MODEL=phi3:mini
PHI3_CACHE_REDIS_URL=                   # optional Redis cache
```

Endpoints `/api/chat`, `/api/skill/...`, `/api/run`, ... are screened.
On block the API returns HTTP 451 with `{"error": "guard_blocked",
"reason": "..."}` and the bot deletes the offending message.

## OAuth2 (Google) + JWT

Set `MONO_GOOGLE_CLIENT_ID` and `MONO_GOOGLE_CLIENT_SECRET` in `.env`,
then visit `http://127.0.0.1:8000/api/auth/login`.

Flow:

1. `/api/auth/login` -> 302 to Google consent screen.
2. Google redirects to `/api/auth/callback` with `?code=...`.
3. Callback exchanges the code, fetches the profile, upserts the user
   into SQLite and redirects back to the PWA shell with
   `#access_token=...&refresh_token=...`.
4. Protected routes use `Depends(current_user)` /
   `Depends(require_role("admin"))`.

## Dynamic settings

`core.settings.SettingsManager` keeps limits / module toggles in a
dedicated `settings` SQLite table. Update them via:

```bash
curl -X POST http://127.0.0.1:8000/api/settings/ \
     -H 'Content-Type: application/json' \
     -d '{"allow_search": false, "max_tokens": 4096}'
```

No restart required. `update_config(**patch)` validates types with
Pydantic `TypeAdapter`.

## License

Founder's Access - lifetime key for $15 (Telegram Wallet).

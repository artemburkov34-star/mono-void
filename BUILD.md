# Mono Core 4.0 — Build .exe

## TL;DR

```powershell
cd "E:\Artyom Burkov\Работа\Programm\MONO_SYSTEM"
.\build_exe.bat
dist\mono.exe --help
```

You get a single `dist\mono.exe` that runs all three modes.

---

## Step-by-step

### 1. Create `.env`

Copy `.env.example` to `.env` and fill in the keys:

```ini
DEEPSEEK_API_KEY=sk-...
OPENAI_API_KEY=sk-...
BOT_TOKEN=123456:ABC...
VAULT_PASSPHRASE=any-strong-string
```

Place `.env` next to `mono.exe` (or in `%APPDATA%\MonoCore\`).

> ⚠️ Never commit `.env` to git. It's already in `.gitignore`.

### 2. Build

PowerShell / cmd:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean tools\mono.spec
```

Or just run:

```powershell
.\build_exe.bat
```

### 3. Run

```powershell
dist\mono.exe                # default: Telegram bot
dist\mono.exe api            # FastAPI server (UI + skills)
dist\mono.exe both           # bot + api in one process
dist\mono.exe migrate        # create / upgrade mono_vault.db, then exit
dist\mono.exe --help
```

### 4. Where data lives

| File | Location |
|---|---|
| `mono_vault.db` | `%APPDATA%\MonoCore\mono_vault.db` |
| `logs\mono.log` | `%APPDATA%\MonoCore\logs\mono.log` |
| `.env` | next to `mono.exe`, OR `%APPDATA%\MonoCore\.env` |
| `ui\` (read-only) | bundled inside the .exe (`sys._MEIPASS`) |

Override the data dir with env var `MONO_DATA_DIR=D:\mono`.

### 5. Common flags

- `--onefile` is implicit (`mono.spec` uses `EXE(...)`).
- `--noconsole`: open `tools\mono.spec`, change `console=True` to `False`,
  then rebuild.
- Smaller binary: install `upx`, then set `upx=True` in the spec.

### 6. PyInstaller flags used

```text
--noconfirm --clean tools\mono.spec
```

Inside `mono.spec`:
- `datas=[("ui","ui"), (".env.example",".")]` — bundle UI assets.
- `hiddenimports=[...]` — pre-declare modules PyInstaller sometimes misses.
- `excludes=["tkinter","matplotlib","numpy",...]` — shrink the binary.
- `console=True` — show stdout (turn `False` for a windowed binary).

### 7. Troubleshooting

**"API Key missing: DEEPSEEK_API_KEY"**
— Put the key in `.env` or set `%DEEPSEEK_API_KEY%` in the environment.

**"BOT_TOKEN missing"**
— Same. Or run `dist\mono.exe api` instead of the bot.

**"OSError: [Errno 10048] bind 127.0.0.1:8000"**
— Another process holds the port. Run `netstat -ano | findstr :8000`,
then `taskkill /PID <pid> /F`.

**Logs**
— `%APPDATA%\MonoCore\logs\mono.log`.

**Schema migration**
— `dist\mono.exe migrate` will create the DB and apply pending migrations.
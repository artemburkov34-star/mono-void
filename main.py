from __future__ import annotations
# -*- coding: utf-8 -*-
"""
Mono Core 4.0 — Personal Neuro-OS on Telegram.
 
Self-contained aiogram 3.x application:
  - aiosqlite for async persistence (users / messages / vault)
  - cryptography.Fernet for encrypting vault entries at rest
  - pluggable AI backend (OpenAI-compatible chat/completions endpoint)
  - AI Autopilot ("Задача:" / "Сделай:") with a simulated reasoning cycle
  - lightweight semantic recall ("Вспомни..." / "Что я писал о...")
  - referral program with Mono-Energy balance
  - PDF/TXT summarization, voice placeholder
  - single WebApp URL used for both the MenuButton and the reply keyboard
 
Required environment variables:
    BOT_TOKEN     — 8725939105:AAEzPUNxUSFUAA6dCa6cvphHTjsILjhkT0M
    WEBAPP_URL    — https://artemburkov34-star.github.io/mono-void/
    ADMIN_ID      — 6233350937
    DB_PATH       — path to the SQLite file (default: mono_core.db)
    VAULT_KEY     — quzcsRYHIOaDynoZWpHpXBX0R8ak-fJtCx0kdc2Xm8Y=
    AI_API_KEY    — API key for the AI backend (optional; bot runs in a
                    degraded "offline" mode without it)
    AI_API_URL    — OpenAI-compatible chat completions endpoint
    AI_MODEL      — model name to request
"""
 
import asyncio
import io
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence
 
import aiosqlite
from cryptography.fernet import Fernet, InvalidToken
 
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    Document,
    KeyboardButton,
    Message,
    MenuButtonWebApp,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
 
try:
    from PyPDF2 import PdfReader
except ImportError:  # optional dependency — degrade gracefully
    PdfReader = None  # type: ignore[assignment]
 
try:
    import aiohttp
except ImportError:
    aiohttp = None  # type: ignore[assignment]
 
 
# ============================================================
# 1. Configuration
# ============================================================
BOT_TOKEN: str = "8725939105:AAEzPUNxUSFUAA6dCa6cvphHTjsILjhkT0M"
WEBAPP_URL: str = "https://artemburkov34-star.github.io/mono-void/"
ADMIN_ID: int = 6233350937
DB_PATH: str = "mono_core.db"
VAULT_KEY: str = "quzcsRYHIOaDynoZWpHpXBX0R8ak-fJtCx0kdc2Xm8Y="

 
AI_API_KEY: str = ("AI_API_KEY", "")
AI_API_URL: str = ("AI_API_URL", "https://api.openai.com/v1/chat/completions")
AI_MODEL: str = ("AI_MODEL", "gpt-4o-mini")
 
REFERRAL_BONUS: int = 50
 
SYSTEM_PROMPT: str = (
    "Ты — Mono Core, персональная нейро-операционная система Оператора. "
    "Отвечай по-русски, вежливо, по делу и без лишней воды. "
    "Опирайся на контекст предыдущих сообщений, чтобы отвечать последовательно."
)
 
TASK_PREFIXES: tuple[str, ...] = ("задача:", "сделай:")
RECALL_PREFIXES: tuple[str, ...] = ("вспомни", "что я писал о")
 
AUTOPILOT_STEPS: tuple[str, ...] = (
    "🔍 Поиск по нейронным связям...",
    "🧠 Синтез контекста Mono Core...",
    "🏗 Построение архитектуры решения...",
)
 
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("mono_core")
 
 
# ============================================================
# 2. Vault encryption (Fernet)
# ============================================================
if VAULT_KEY:
    _fernet = Fernet(VAULT_KEY.encode())
else:
    _generated_key = Fernet.generate_key()
    _fernet = Fernet(_generated_key)
    logger.warning(
        "VAULT_KEY not set — generated a temporary key: %s\n"
        "Set VAULT_KEY to this value (or your own) to keep vault entries "
        "readable across restarts.",
        _generated_key.decode(),
    )
 
 
def vault_encrypt(text: str) -> bytes:
    return _fernet.encrypt(text.encode("utf-8"))
 
 
def vault_decrypt(token: bytes) -> str:
    try:
        return _fernet.decrypt(token).decode("utf-8")
    except InvalidToken:
        return "[⚠️ не удалось расшифровать запись]"
 
 
# ============================================================
# 3. Database layer (aiosqlite)
# ============================================================
class Database:
    """Thin async wrapper around a single aiosqlite connection."""
 
    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
 
    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._create_schema()
 
    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
 
    async def _create_schema(self) -> None:
        assert self._conn is not None
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id                INTEGER PRIMARY KEY,
                username          TEXT,
                name              TEXT,
                sub_status        TEXT NOT NULL DEFAULT 'free',
                balance           INTEGER NOT NULL DEFAULT 0,
                registration_date TEXT NOT NULL,
                referrer_id       INTEGER
            );
 
            CREATE TABLE IF NOT EXISTS messages (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER NOT NULL,
                role      TEXT NOT NULL,
                content   TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, id);
 
            CREATE TABLE IF NOT EXISTS vault (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                encrypted_text  BLOB NOT NULL,
                created_at      TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_vault_user ON vault(user_id, id);
            """
        )
        await self._conn.commit()
 
    # ---------------- users ----------------
    async def get_user(self, user_id: int) -> Optional[aiosqlite.Row]:
        assert self._conn is not None
        cur = await self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cur.fetchone()
        await cur.close()
        return row
 
    async def create_user_if_missing(
        self,
        user_id: int,
        username: Optional[str],
        name: Optional[str],
        referrer_id: Optional[int] = None,
    ) -> bool:
        """Insert a new user row. Returns True if the user was newly created."""
        assert self._conn is not None
        async with self._lock:
            if await self.get_user(user_id) is not None:
                return False
            now = datetime.now(timezone.utc).isoformat()
            valid_referrer = referrer_id if (referrer_id and referrer_id != user_id) else None
            await self._conn.execute(
                "INSERT INTO users (id, username, name, sub_status, balance, "
                "registration_date, referrer_id) VALUES (?, ?, ?, 'free', 0, ?, ?)",
                (user_id, username, name, now, valid_referrer),
            )
            await self._conn.commit()
            return True
 
    async def credit_balance(self, user_id: int, amount: int) -> None:
        assert self._conn is not None
        async with self._lock:
            await self._conn.execute(
                "UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user_id)
            )
            await self._conn.commit()
 
    async def stats(self) -> dict[str, int]:
        assert self._conn is not None
        cur = await self._conn.execute("SELECT COUNT(*) AS c FROM users")
        total = (await cur.fetchone())["c"]
        await cur.close()
 
        since_new = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        cur = await self._conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE registration_date >= ?", (since_new,)
        )
        new_today = (await cur.fetchone())["c"]
        await cur.close()
 
        since_active = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        cur = await self._conn.execute(
            "SELECT COUNT(DISTINCT user_id) AS c FROM messages WHERE timestamp >= ?",
            (since_active,),
        )
        active_week = (await cur.fetchone())["c"]
        await cur.close()
 
        return {"total": total, "new_today": new_today, "active_week": active_week}
 
    # ---------------- messages ----------------
    async def add_message(self, user_id: int, role: str, content: str) -> None:
        assert self._conn is not None
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO messages (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (user_id, role, content, datetime.now(timezone.utc).isoformat()),
            )
            await self._conn.commit()
 
    async def get_context(self, user_id: int, limit: int = 15) -> list[dict[str, str]]:
        """Return up to `limit` most recent messages, oldest-first, ready for the LLM."""
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT role, content FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        rows = await cur.fetchall()
        await cur.close()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
 
    async def search_messages(self, user_id: int, query: str, limit: int = 5) -> list[aiosqlite.Row]:
        """Naive substring search over past user messages — a stand-in for real
        semantic (embedding-based) search until that backend is wired in."""
        assert self._conn is not None
        like = f"%{query}%"
        cur = await self._conn.execute(
            "SELECT content, timestamp FROM messages "
            "WHERE user_id = ? AND role = 'user' AND content LIKE ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, like, limit),
        )
        rows = await cur.fetchall()
        await cur.close()
        return rows
 
    # ---------------- vault ----------------
    async def vault_add(self, user_id: int, encrypted_text: bytes) -> None:
        assert self._conn is not None
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO vault (user_id, encrypted_text, created_at) VALUES (?, ?, ?)",
                (user_id, encrypted_text, datetime.now(timezone.utc).isoformat()),
            )
            await self._conn.commit()
 
    async def vault_list(self, user_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT encrypted_text, created_at FROM vault WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        rows = await cur.fetchall()
        await cur.close()
        return rows
 
 
db = Database(DB_PATH)
 
 
# ============================================================
# 4. AI backend (OpenAI-compatible chat/completions)
# ============================================================
class AIClient:
    def __init__(self, api_key: str, api_url: str, model: str) -> None:
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
 
    async def chat(self, messages: Sequence[dict[str, str]]) -> str:
        if not self.api_key or aiohttp is None:
            last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
            return (
                "🧠 Mono Core (офлайн-режим): AI-провайдер не настроен.\n"
                f"Получен запрос: «{last_user[:200]}».\n"
                "Задайте AI_API_KEY (и при необходимости AI_API_URL / AI_MODEL), "
                "чтобы подключить нейросеть."
            )
        payload = {"model": self.model, "messages": list(messages), "temperature": 0.7}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
                async with session.post(self.api_url, json=payload, headers=headers) as resp:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:  # noqa: BLE001 — surface any backend failure to the user
            logger.exception("AI request failed")
            return f"⚠️ Ошибка обращения к нейросети: {exc}"
 
 
ai_client = AIClient(AI_API_KEY, AI_API_URL, AI_MODEL)
 
 
# ============================================================
# 5. FSM states
# ============================================================
class VaultForm(StatesGroup):
    waiting_note = State()
 
 
# ============================================================
# 6. Keyboards / WebApp
# ============================================================
def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⚡ ОТКРЫТЬ ЯДРО", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True,
    )
 
 
async def setup_menu_button(bot: Bot) -> None:
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="Mono Core", web_app=WebAppInfo(url=WEBAPP_URL))
    )
 
 
# ============================================================
# 7. Typing effect with flood-control handling
# ============================================================
async def typing_reveal(message: Message, full_text: str, chunk_size: int = 40, delay: float = 0.5) -> Message:
    """Send a message and progressively edit it to simulate live generation,
    backing off on TelegramRetryAfter (flood control)."""
    if not full_text:
        full_text = "…"
 
    sent = await message.answer("⏳")
    buffer = ""
    for i in range(0, len(full_text), chunk_size):
        buffer += full_text[i : i + chunk_size]
        is_last = i + chunk_size >= len(full_text)
        display = buffer if is_last else buffer + " ▌"
        try:
            await sent.edit_text(display)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                await sent.edit_text(display)
            except TelegramBadRequest:
                pass
        except TelegramBadRequest:
            pass
        if not is_last:
            await asyncio.sleep(delay)
    return sent
 
 
async def run_autopilot(message: Message, task_text: str, user_id: int) -> None:
    """AI Autopilot: visual 'deep analysis' cycle, then a real LLM answer."""
    status = await message.answer(AUTOPILOT_STEPS[0])
    for step in AUTOPILOT_STEPS[1:]:
        await asyncio.sleep(1.1)
        try:
            await status.edit_text(step)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                await status.edit_text(step)
            except TelegramBadRequest:
                pass
        except TelegramBadRequest:
            pass
 
    context = await db.get_context(user_id)
    messages = (
        [{"role": "system", "content": SYSTEM_PROMPT}]
        + context
        + [{"role": "user", "content": f"Задача от Оператора: {task_text}"}]
    )
    answer = await ai_client.chat(messages)
    try:
        await status.edit_text(f"✅ Решение готово:\n\n{answer}")
    except TelegramRetryAfter as exc:
        await asyncio.sleep(exc.retry_after)
        await status.edit_text(f"✅ Решение готово:\n\n{answer}")
    await db.add_message(user_id, "assistant", answer)
 
 
# ============================================================
# 8. Filters (prefix matching helpers)
# ============================================================
def _starts_with(prefixes: tuple[str, ...]):
    def _check(text: Optional[str]) -> bool:
        if not text:
            return False
        return text.strip().lower().startswith(prefixes)
    return _check
 
 
# ============================================================
# 9. Router / handlers
# ============================================================
router = Router()
 
 
# ---- onboarding & referrals -------------------------------------------------
@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    user = message.from_user
    referrer_id: Optional[int] = None
    if command.args and command.args.isdigit():
        referrer_id = int(command.args)
 
    created = await db.create_user_if_missing(
        user_id=user.id,
        username=user.username,
        name=user.full_name,
        referrer_id=referrer_id,
    )
    if created and referrer_id:
        await db.credit_balance(referrer_id, REFERRAL_BONUS)
        try:
            await message.bot.send_message(
                referrer_id,
                f"🎁 По вашей ссылке зарегистрировался новый Оператор. "
                f"Начислено {REFERRAL_BONUS} Mono-Energy.",
            )
        except TelegramBadRequest:
            pass
 
    await message.answer(
        "⚡ <b>MONO CORE 4.0</b>\n"
        "Персональная нейро-ОС в Telegram.\n\n"
        "Пишите — я отвечаю с учётом истории нашей переписки.\n"
        "«<b>Задача: ...</b>» или «<b>Сделай: ...</b>» — запускаю AI Автопилот.\n"
        "«<b>Вспомни ...</b>» — ищу в вашей истории.\n"
        "/vault — сохранить зашифрованную запись, /vault_list — показать их.\n"
        "/ref — ваша реферальная ссылка.",
        reply_markup=main_menu_kb(),
    )
 
 
@router.message(Command("ref"))
async def cmd_ref(message: Message, bot: Bot) -> None:
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={message.from_user.id}"
    user = await db.get_user(message.from_user.id)
    balance = user["balance"] if user else 0
    await message.answer(
        f"👥 Ваша реферальная ссылка:\n{link}\n\n"
        f"За каждого приглашённого — {REFERRAL_BONUS} Mono-Energy.\n"
        f"Текущий баланс: {balance} Mono-Energy."
    )
 
 
@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if message.from_user.id != ADMIN_ID:
        return
    s = await db.stats()
    await message.answer(
        "📊 <b>Статистика Mono Core</b>\n"
        f"Всего пользователей: {s['total']}\n"
        f"Новых за 24ч: {s['new_today']}\n"
        f"Активных за 7д: {s['active_week']}"
    )
 
 
# ---- vault (encrypted notes) -------------------------------------------------
@router.message(Command("vault"))
async def cmd_vault(message: Message, state: FSMContext) -> None:
    await state.set_state(VaultForm.waiting_note)
    await message.answer(
        "🔐 Отправьте текст для зашифрованного хранилища (Vault).\n"
        "Команда /vault_list покажет последние записи."
    )
 
 
@router.message(VaultForm.waiting_note, F.text)
async def save_vault_note(message: Message, state: FSMContext) -> None:
    token = vault_encrypt(message.text)
    await db.vault_add(message.from_user.id, token)
    await state.clear()
    await message.answer("🔐 Запись зашифрована и сохранена в Vault.")
 
 
@router.message(Command("vault_list"))
async def cmd_vault_list(message: Message) -> None:
    rows = await db.vault_list(message.from_user.id)
    if not rows:
        await message.answer("🔐 Vault пуст.")
        return
    lines = ["🔐 <b>Vault:</b>"]
    for r in rows:
        decrypted = vault_decrypt(r["encrypted_text"])
        date = r["created_at"][:10]
        lines.append(f"— <i>{date}:</i> {decrypted[:200]}")
    await message.answer("\n".join(lines))
 
 
# ---- files & voice ------------------------------------------------------------
@router.message(F.voice)
async def handle_voice(message: Message) -> None:
    await message.answer("🎙 Голос принят. Транскрибация Whisper будет доступна в v4.1")
 
 
@router.message(F.document)
async def handle_document(message: Message, bot: Bot) -> None:
    doc: Document = message.document
    name = (doc.file_name or "").lower()
    if not (name.endswith(".pdf") or name.endswith(".txt")):
        await message.answer("📎 Поддерживаются файлы .pdf и .txt.")
        return
 
    status = await message.answer("📄 Читаю файл...")
    file = await bot.get_file(doc.file_id)
    buf = io.BytesIO()
    await bot.download_file(file.file_path, destination=buf)
    buf.seek(0)
 
    if name.endswith(".pdf"):
        if PdfReader is None:
            await status.edit_text("⚠️ Модуль PyPDF2 не установлен на сервере.")
            return
        try:
            reader = PdfReader(buf)
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            logger.exception("PDF parse failed")
            await status.edit_text("⚠️ Не удалось прочитать PDF.")
            return
    else:
        text = buf.read().decode("utf-8", errors="ignore")
 
    text = text.strip()
    if not text:
        await status.edit_text("⚠️ В файле не найдено текста.")
        return
 
    excerpt = text[:6000]
    messages = [
        {
            "role": "system",
            "content": "Ты делаешь краткое резюме документа для Оператора Mono Core, "
                       "по-русски, структурированно, по пунктам.",
        },
        {"role": "user", "content": f"Сделай краткое резюме этого документа:\n\n{excerpt}"},
    ]
    summary = await ai_client.chat(messages)
    await status.edit_text(f"📄 <b>Резюме документа</b> «{doc.file_name}»:\n\n{summary}")
 
    user_id = message.from_user.id
    await db.add_message(user_id, "user", f"[файл: {doc.file_name}]")
    await db.add_message(user_id, "assistant", summary)
 
 
# ---- AI Autopilot ("Задача:" / "Сделай:") --------------------------------------
@router.message(F.text.func(_starts_with(TASK_PREFIXES)))
async def handle_task(message: Message) -> None:
    text = message.text.strip()
    task_text = text.split(":", 1)[1].strip() if ":" in text else text
    user_id = message.from_user.id
    await db.add_message(user_id, "user", text)
    await run_autopilot(message, task_text, user_id)
 
 
# ---- recall / lightweight semantic search --------------------------------------
@router.message(F.text.func(_starts_with(RECALL_PREFIXES)))
async def handle_recall(message: Message) -> None:
    text = message.text.strip()
    query = text
    for prefix in RECALL_PREFIXES:
        if text.lower().startswith(prefix):
            query = text[len(prefix):].strip(" :.,")
            break
 
    user_id = message.from_user.id
    await db.add_message(user_id, "user", text)
 
    if not query:
        reply = "Уточните, что именно вспомнить — например: «Вспомни про проект X»."
    else:
        hits = await db.search_messages(user_id, query)
        if not hits:
            reply = "🔍 В вашей истории ничего не найдено по этому запросу."
        else:
            lines = ["🔍 <b>Найдено в истории:</b>"]
            for h in hits:
                date = h["timestamp"][:10]
                snippet = h["content"][:200]
                lines.append(f"— <i>{date}:</i> «{snippet}»")
            reply = "\n".join(lines)
 
    await message.answer(reply)
    await db.add_message(user_id, "assistant", reply)
 
 
# ---- default AI chat -------------------------------------------------------------
@router.message(F.text)
async def handle_chat(message: Message) -> None:
    text = message.text.strip()
    user_id = message.from_user.id
    await db.add_message(user_id, "user", text)
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
 
    context = await db.get_context(user_id)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + context
    answer = await ai_client.chat(messages)
    await typing_reveal(message, answer)
    await db.add_message(user_id, "assistant", answer)
 
 
# ============================================================
# 10. Application lifecycle
# ============================================================
async def on_startup(bot: Bot) -> None:
    await db.connect()
    await setup_menu_button(bot)
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Запустить Mono Core"),
            BotCommand(command="ref", description="Реферальная ссылка"),
            BotCommand(command="vault", description="Сохранить запись в Vault"),
            BotCommand(command="vault_list", description="Показать записи Vault"),
            BotCommand(command="admin", description="Статистика (только для админа)"),
        ]
    )
    logger.info("Mono Core 4.0 started")
 
 
async def on_shutdown(bot: Bot) -> None:
    await db.close()
    logger.info("Mono Core 4.0 stopped")
 
 
async def main() -> None:
    
 
    bot = Bot(token=BOT_TOKEN, default_properties=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
 
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
 
 
if __name__ == "__main__":
    asyncio.run(main())
 


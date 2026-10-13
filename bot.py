"""
STARKA AI - Bot Telegram berbasis 9Router (API kompatibel OpenAI).

"""

import asyncio
import functools
import html
import logging
import os
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from telegram import BotCommand, Update
from telegram.constants import ChatAction, ChatType, ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ==================================================
# 1. KONFIGURASI
# ==================================================

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
# Kurangi log berisik dari library HTTP.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("starka")


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ROUTER_API_KEY = os.getenv("ROUTER_API_KEY")
ROUTER_BASE_URL = os.getenv("ROUTER_BASE_URL", "http://localhost:20128/v1")

MODELS = {
    "general": os.getenv("MODEL_GENERAL", "gemini/gemini-3.5-flash-lite"),
    "analysis": os.getenv("MODEL_ANALYSIS", "gemini/gemini-3.5-flash-lite"),
    "coding": os.getenv("MODEL_CODING", "kr/qwen3-coder-next"),
}

# Suhu per kategori: rendah untuk kode/analisis agar lebih konsisten.
TEMPERATURES = {"general": 0.7, "analysis": 0.3, "coding": 0.2}

MAX_HISTORY_MESSAGES = env_int("MAX_HISTORY_MESSAGES", 10)
MAX_HISTORY_CHARS = env_int("MAX_HISTORY_CHARS", 12000)
MAX_INPUT_CHARS = env_int("MAX_INPUT_CHARS", 6000)
MAX_MESSAGE_LENGTH = 3500  # batas aman < 4096 karena ada tag HTML
MAX_TOKENS = env_int("MAX_TOKENS", 2048)
REQUEST_TIMEOUT = env_int("REQUEST_TIMEOUT", 60)
MAX_RETRIES = env_int("MAX_RETRIES", 1)
RATE_LIMIT_PER_MINUTE = env_int("RATE_LIMIT_PER_MINUTE", 10)

# Opsional: batasi akses, contoh ALLOWED_USER_IDS=12345,67890 (kosong = terbuka).
ALLOWED_USER_IDS = {
    int(x)
    for x in os.getenv("ALLOWED_USER_IDS", "").replace(" ", "").split(",")
    if x.isdigit()
}

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN belum diisi di file .env")

if not ROUTER_API_KEY:
    raise ValueError("ROUTER_API_KEY belum diisi di file .env")

client = AsyncOpenAI(
    api_key=ROUTER_API_KEY,
    base_url=ROUTER_BASE_URL,
    timeout=float(REQUEST_TIMEOUT),
    max_retries=0,  # retry ditangani manual di ask_model
)

TRANSIENT_ERRORS = (
    APITimeoutError,
    APIConnectionError,
    RateLimitError,
    InternalServerError,
)

TRUNCATED_NOTE = (
    "\n\n(Jawaban terpotong karena terlalu panjang. "
    "Ketik \"lanjutkan\" untuk meneruskan.)"
)


# ==================================================
# 2. STATE PERCAKAPAN
# ==================================================

@dataclass
class ChatState:
    history: list = field(default_factory=list)
    mode: Optional[str] = None          # None = otomatis
    last_category: str = "general"
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


states: dict[int, ChatState] = defaultdict(ChatState)
user_hits: dict[int, deque] = defaultdict(deque)


def trim_history(history: list) -> list:
    """Batasi riwayat berdasarkan jumlah pesan dan total karakter."""
    history = history[-MAX_HISTORY_MESSAGES:]
    while len(history) > 2 and sum(len(m["content"]) for m in history) > MAX_HISTORY_CHARS:
        history = history[1:]
    # Riwayat sebaiknya diawali pesan pengguna.
    while history and history[0]["role"] != "user":
        history = history[1:]
    return history


def is_rate_limited(user_id: int) -> bool:
    now = time.monotonic()
    hits = user_hits[user_id]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= RATE_LIMIT_PER_MINUTE:
        return True
    hits.append(now)
    return False


# ==================================================
# 3. PEMILIHAN KATEGORI OTOMATIS
# ==================================================

def _compile(words: list[str]) -> re.Pattern:
    return re.compile(
        r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b"
    )


CODING_PATTERN = _compile([
    "python", "javascript", "typescript", "html", "css", "sql", "mysql",
    "php", "java", "laravel", "flask", "django", "react", "node.js",
    "coding", "kode", "code", "pemrograman", "programmer", "debug",
    "debugging", "error", "bug", "script", "function", "fungsi",
    "query", "database", "api", "endpoint", "github", "git", "docker",
    "buat website", "buat aplikasi", "perbaiki kode",
])

ANALYSIS_PATTERN = _compile([
    "analisis", "analisa", "statistik", "regresi", "korelasi",
    "penelitian", "metodologi", "skripsi", "jurnal", "dataset",
    "machine learning", "algoritma", "xgboost", "akurasi",
    "evaluasi model", "confusion matrix", "hitung", "persamaan",
    "rumus", "interpretasi", "feature selection", "information gain",
    "shap", "smote", "hipotesis",
])


def detect_category(text: str, state: ChatState) -> str:
    """Pilih kategori berdasarkan isi pesan; pesan pendek mengikuti topik sebelumnya."""
    lowered = text.lower()
    coding_hits = len(CODING_PATTERN.findall(lowered))
    analysis_hits = len(ANALYSIS_PATTERN.findall(lowered))

    if coding_hits or analysis_hits:
        return "coding" if coding_hits >= analysis_hits else "analysis"

    # Pertanyaan lanjutan ("lanjutkan", "kenapa?", "contohnya?") tetap di topik yang sama.
    if state.history and len(text) < 80:
        return state.last_category
    return "general"


# ==================================================
# 4. PROMPT SISTEM
# ==================================================

BASE_PROMPT = (
    "Kamu adalah STARKA AI, asisten virtual di Telegram yang akurat, jelas, "
    "ramah, dan efisien.\n"
    "Waktu saat ini: {now}.\n\n"
    "Aturan:\n"
    "- Jawab dalam bahasa yang dipakai pengguna (default Bahasa Indonesia).\n"
    "- Pertanyaan sederhana dijawab langsung dan singkat. Pertanyaan teknis "
    "dijawab bertahap dengan contoh yang relevan.\n"
    "- Jika permintaan ambigu, ajukan satu pertanyaan klarifikasi singkat.\n"
    "- Jangan pernah menampilkan proses berpikir, rencana jawaban, atau tag "
    "seperti <thinking>; tulis hanya jawaban akhir untuk pengguna.\n"
    "- Jika tidak yakin atau tidak tahu, katakan terus terang; jangan mengarang "
    "fakta, angka, atau sumber.\n"
    "- Format untuk Telegram: paragraf pendek, daftar dengan tanda '-', "
    "**tebal** seperlunya, kode dalam blok ``` dengan nama bahasa. "
    "Jangan gunakan tabel Markdown, LaTeX, atau judul bertingkat."
)

CATEGORY_HINTS = {
    "general": "",
    "analysis": (
        "\n\nFokus: analisis. Jelaskan langkah penalaran secara runtut, "
        "sebutkan asumsi, dan beri alasan pada setiap pilihan metode."
    ),
    "coding": (
        "\n\nFokus: pemrograman. Berikan kode yang lengkap dan dapat dijalankan, "
        "jelaskan singkat bagian pentingnya, dan sebutkan cara menjalankannya "
        "bila perlu."
    ),
}


def build_system_prompt(category: str) -> str:
    wib = timezone(timedelta(hours=7))
    now = datetime.now(wib).strftime("%Y-%m-%d %H:%M WIB")
    return BASE_PROMPT.format(now=now) + CATEGORY_HINTS.get(category, "")


# ==================================================
# 5. FORMAT JAWABAN UNTUK TELEGRAM
# ==================================================

_TAG_NAMES = r"(?:thinking|think|thoughts?|reasoning|reflection)"
_OPEN_TAG = rf"<\s*{_TAG_NAMES}\s*>"
_CLOSE_TAG = rf"<\s*/\s*{_TAG_NAMES}\s*>"


def clean_answer(text: str) -> str:
    """Hapus blok penalaran (<thinking>, <think>, dll.) dari jawaban model."""
    flags = re.S | re.I
    # Blok lengkap: <thinking> ... </thinking>
    text = re.sub(rf"{_OPEN_TAG}.*?{_CLOSE_TAG}", "", text, flags=flags)
    # Tag penutup tanpa pembuka: buang semua teks sebelumnya.
    text = re.sub(rf"^.*?{_CLOSE_TAG}", "", text, flags=flags)
    # Tag pembuka tanpa penutup (mis. terpotong max_tokens): buang sisanya.
    text = re.sub(rf"{_OPEN_TAG}.*", "", text, flags=flags)
    return text.strip()


def md_to_html(text: str) -> str:
    """Ubah Markdown sederhana dari model menjadi HTML yang didukung Telegram."""
    blocks: list[str] = []
    inline: list[str] = []

    def stash_block(m: re.Match) -> str:
        lang = m.group(1).strip()
        code = html.escape(m.group(2).strip("\n"))
        if lang:
            blocks.append(
                f'<pre><code class="language-{html.escape(lang)}">{code}</code></pre>'
            )
        else:
            blocks.append(f"<pre>{code}</pre>")
        return f"\x00B{len(blocks) - 1}\x00"

    def stash_inline(m: re.Match) -> str:
        inline.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00I{len(inline) - 1}\x00"

    text = re.sub(r"```([\w+#.-]*)\n?(.*?)```", stash_block, text, flags=re.S)
    text = re.sub(r"`([^`\n]+)`", stash_inline, text)
    text = html.escape(text)

    text = re.sub(r"^\s{0,3}#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+", "• ", text, flags=re.M)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.S)
    text = re.sub(r"(?<![\*\w])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\*\w])", r"<i>\1</i>", text)
    text = re.sub(
        r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)",
        r'<a href="\2">\1</a>',
        text,
    )

    text = re.sub(r"\x00I(\d+)\x00", lambda m: inline[int(m.group(1))], text)
    text = re.sub(r"\x00B(\d+)\x00", lambda m: blocks[int(m.group(1))], text)
    return text


def split_message(text: str, limit: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Pecah teks panjang per baris; blok kode ditutup dan dibuka ulang di tiap potongan."""
    chunks: list[str] = []
    current = ""
    in_code = False
    reserve = 4  # ruang untuk "\n```" penutup
    piece_size = limit - 10

    def flush():
        nonlocal current
        if current.strip():
            chunk = current.rstrip("\n")
            if in_code:
                chunk += "\n```"
            chunks.append(chunk)
        current = "```\n" if in_code else ""

    for line in text.split("\n"):
        pieces = [line[i:i + piece_size] for i in range(0, len(line), piece_size)] or [""]
        for piece in pieces:
            if len(current) + len(piece) + 1 > limit - reserve:
                flush()
            current += piece + "\n"
            if piece.strip().startswith("```"):
                in_code = not in_code

    if current.strip() not in ("", "```"):
        chunks.append(current.rstrip("\n"))
    return chunks or [text]


async def send_long(message, text: str) -> None:
    for chunk in split_message(text):
        try:
            await message.reply_text(
                md_to_html(chunk),
                parse_mode=ParseMode.HTML,
            )
        except BadRequest:
            # Jika HTML ditolak Telegram, kirim apa adanya.
            await message.reply_text(chunk)


# ==================================================
# 6. PEMANGGILAN MODEL
# ==================================================

async def ask_model(model: str, messages: list, temperature: float) -> str:
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=MAX_TOKENS,
                temperature=temperature,
            )
        except TRANSIENT_ERRORS:
            if attempt < MAX_RETRIES:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            raise

        choice = response.choices[0]
        answer = clean_answer(choice.message.content or "")
        if not answer:
            raise ValueError("Model memberikan jawaban kosong.")
        if choice.finish_reason == "length":
            answer += TRUNCATED_NOTE
        return answer

    raise RuntimeError("Tidak ada percobaan yang dijalankan.")  # tidak tercapai


async def generate_answer(category: str, messages: list) -> str:
    primary = MODELS[category]
    fallback = MODELS["general"]
    temperature = TEMPERATURES[category]

    try:
        return await ask_model(primary, messages, temperature)
    except Exception as exc:
        if primary == fallback:
            raise
        logger.warning(
            "Model kategori '%s' gagal (%s). Mencoba model cadangan.",
            category,
            type(exc).__name__,
        )
        return await ask_model(fallback, messages, TEMPERATURES["general"])


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, APITimeoutError):
        return "Model terlalu lama merespons. Coba lagi, atau persingkat pertanyaanmu."
    if isinstance(exc, RateLimitError):
        return "Layanan AI sedang sibuk. Tunggu sebentar lalu coba lagi."
    if isinstance(exc, APIConnectionError):
        return "Tidak dapat terhubung ke layanan AI. Coba lagi beberapa saat lagi."
    return "Maaf, permintaan belum berhasil diproses. Silakan coba lagi."


# ==================================================
# 7. UTILITAS HANDLER
# ==================================================

def is_authorized(update: Update) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    user = update.effective_user
    return bool(user and user.id in ALLOWED_USER_IDS)


def restricted(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_authorized(update):
            chat = update.effective_chat
            if chat and chat.type == ChatType.PRIVATE and update.message:
                await update.message.reply_text("Maaf, akses ke bot ini dibatasi.")
            return
        return await func(update, context)

    return wrapper


async def keep_typing(chat, stop: asyncio.Event) -> None:
    """Kirim indikator 'mengetik...' sampai jawaban siap."""
    while not stop.is_set():
        try:
            await chat.send_action(ChatAction.TYPING)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=4)
        except asyncio.TimeoutError:
            pass


def extract_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    """Di chat pribadi semua teks dijawab; di grup hanya saat di-mention atau di-reply."""
    message = update.message
    text = (message.text or "").strip()

    if update.effective_chat.type == ChatType.PRIVATE:
        return text

    username = (context.bot.username or "").lower()
    mention = f"@{username}"
    if username and mention in text.lower():
        return re.sub(re.escape(mention), "", text, flags=re.I).strip()

    replied = message.reply_to_message
    if replied and replied.from_user and replied.from_user.id == context.bot.id:
        return text

    return None


# ==================================================
# 8. PERINTAH TELEGRAM
# ==================================================

HELP_TEXT = (
    "Perintah yang tersedia:\n"
    "/mode - Lihat atau ubah mode (auto, general, analysis, coding)\n"
    "/model - Lihat kategori model\n"
    "/reset - Hapus riwayat percakapan\n"
    "/help - Tampilkan bantuan ini\n\n"
    "Kamu juga bisa langsung mengetik pertanyaan. "
    "Di grup, mention bot atau balas pesan bot."
)


@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name if update.effective_user else "teman"
    await update.message.reply_text(
        f"Halo, {name}! Saya STARKA AI.\n\n"
        "Saya siap membantu menjawab pertanyaan, menganalisis masalah, "
        "dan membuat kode program.\n\n" + HELP_TEXT
    )


@restricted
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)


@restricted
async def show_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = states[update.effective_chat.id]
    await update.message.reply_text(
        "Kategori STARKA AI:\n\n"
        f"General: {MODELS['general']}\n"
        f"Analysis: {MODELS['analysis']}\n"
        f"Coding: {MODELS['coding']}\n\n"
        f"Mode saat ini: {state.mode or 'auto'}"
    )


@restricted
async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = states[update.effective_chat.id]

    if not context.args:
        await update.message.reply_text(
            f"Mode saat ini: {state.mode or 'auto'}\n\n"
            "Gunakan /mode auto, /mode general, /mode analysis, atau /mode coding."
        )
        return

    mode = context.args[0].lower()

    if mode == "auto":
        state.mode = None
        await update.message.reply_text("Pemilihan model otomatis diaktifkan.")
        return

    if mode not in MODELS:
        await update.message.reply_text(
            "Mode tidak valid. Pilih auto, general, analysis, atau coding."
        )
        return

    state.mode = mode
    await update.message.reply_text(f"Mode {mode} diaktifkan.")


@restricted
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = states[update.effective_chat.id]
    state.history.clear()
    state.last_category = "general"
    await update.message.reply_text("Riwayat percakapan telah dihapus.")


@restricted
async def unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Saat ini saya hanya dapat memproses pesan teks. "
        "Silakan ketik pertanyaanmu."
    )


# ==================================================
# 9. PROSES PESAN PENGGUNA
# ==================================================

@restricted
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    user_text = extract_prompt(update, context)
    if not user_text:
        return

    if len(user_text) > MAX_INPUT_CHARS:
        await message.reply_text(
            f"Pesan terlalu panjang (maks {MAX_INPUT_CHARS} karakter). "
            "Silakan persingkat atau pecah menjadi beberapa pesan."
        )
        return

    user_id = update.effective_user.id if update.effective_user else 0
    if is_rate_limited(user_id):
        await message.reply_text(
            "Terlalu banyak pesan dalam waktu singkat. Tunggu sebentar ya."
        )
        return

    chat = update.effective_chat
    state = states[chat.id]

    # Kunci per chat menjaga urutan pesan, sementara chat lain tetap berjalan paralel.
    async with state.lock:
        category = state.mode or detect_category(user_text, state)

        messages = [
            {"role": "system", "content": build_system_prompt(category)},
            *state.history,
            {"role": "user", "content": user_text},
        ]

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(chat, stop_typing))

        try:
            answer = await generate_answer(category, messages)
        except Exception as exc:
            logger.exception("Permintaan gagal (kategori: %s)", category)
            stop_typing.set()
            await typing_task
            await message.reply_text(friendly_error(exc))
            return  # riwayat tidak diubah saat gagal
        finally:
            stop_typing.set()

        await typing_task

        # Simpan percakapan hanya setelah berhasil.
        state.history.append({"role": "user", "content": user_text})
        state.history.append({"role": "assistant", "content": answer})
        state.history = trim_history(state.history)
        state.last_category = category

        await send_long(message, answer)


# ==================================================
# 10. MENJALANKAN BOT
# ==================================================

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Error tak tertangani", exc_info=context.error)


async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "Mulai menggunakan bot"),
        BotCommand("mode", "Lihat atau ubah mode"),
        BotCommand("model", "Lihat kategori model"),
        BotCommand("reset", "Hapus riwayat percakapan"),
        BotCommand("help", "Bantuan"),
    ])


def main():
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .concurrent_updates(True)  # pengguna lain tidak menunggu permintaan yang lambat
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("model", show_models))
    app.add_handler(CommandHandler("mode", set_mode))
    app.add_handler(CommandHandler("reset", reset))

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    app.add_handler(
        MessageHandler(
            ~filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            unsupported,
        )
    )

    app.add_error_handler(on_error)

    print("STARKA AI aktif . Tekan Ctrl+C untuk berhenti.")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
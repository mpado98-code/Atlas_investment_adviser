"""Atlas - Telegram bot di consulenza investimenti personali (versione Gemini).

Architettura:
- python-telegram-bot per gestione messaggi
- Google Gemini 2.5 Pro come motore di ragionamento (vision + Google Search grounding)
- Memoria conversazione in-memory per chat, persistita su file JSON
- Whitelist utenti (TELEGRAM_ALLOWED_USER_IDS) per evitare accessi indesiderati
- Modalita' polling (locale/VM) o webhook (Render/Fly/Vercel free tier)

Tier gratuito Gemini API (https://aistudio.google.com):
  - Gemini 2.5 Pro: ~100 richieste/giorno, 5 al minuto
  - Gemini 2.5 Flash: ~250 richieste/giorno, 10 al minuto
  - Include visione e Google Search grounding
  Per uso personale (10-30 query al giorno) basta e avanza.

Variabili d'ambiente richieste:
  TELEGRAM_BOT_TOKEN          Token bot da @BotFather
  GOOGLE_API_KEY              API key da https://aistudio.google.com/apikey
  TELEGRAM_ALLOWED_USER_IDS   CSV di Telegram user id consentiti (es. "12345,67890")

Modalita' di esecuzione:
  MODE=polling   (default)  Adatto a esecuzione locale e VM sempre accese.
  MODE=webhook              Espone un endpoint HTTP. Necessario per i piani
                            Web Service gratuiti (Render, Fly, ecc.).
                            Richiede inoltre:
    WEBHOOK_URL             URL pubblico HTTPS del servizio (es.
                            "https://atlas-bot.onrender.com")
    WEBHOOK_SECRET_PATH     stringa random nel path URL per protezione
                            (default: token del bot). Esempio: "tg-abc123".
    PORT                    porta su cui ascoltare (Render la fornisce
                            automaticamente come env var)

Opzionali:
  GEMINI_MODEL                default: gemini-2.5-pro
  ENABLE_WEB_SEARCH           "true" per abilitare Google Search grounding (default: true)
  CONV_DIR                    cartella per persistenza (default: ./conversations)
  MAX_HISTORY_TURNS           max turni mantenuti (default: 40)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types as gtypes
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from prompts import SYSTEM_PROMPT, WELCOME_MESSAGE

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("atlas")

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
ALLOWED_IDS = {
    int(x) for x in os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",") if x.strip()
}
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
ENABLE_WEB_SEARCH = os.environ.get("ENABLE_WEB_SEARCH", "true").lower() == "true"
CONV_DIR = Path(os.environ.get("CONV_DIR", "./conversations"))
MAX_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "40"))

CONV_DIR.mkdir(parents=True, exist_ok=True)
client = genai.Client(api_key=GOOGLE_API_KEY)


# ---------------------------------------------------------------------------
# Conversation store
# ---------------------------------------------------------------------------
#
# Formato messaggi (compatibile con google-genai):
# {
#   "role": "user" | "model",
#   "parts": [
#       {"text": "..."}                                  (testo)
#     | {"inline_data": {"mime_type": "image/jpeg",
#                         "data": "<base64>"}}            (immagine)
#   ]
# }


@dataclass
class Conversation:
    user_id: int
    contents: list[dict[str, Any]] = field(default_factory=list)

    @property
    def path(self) -> Path:
        return CONV_DIR / f"{self.user_id}.json"

    @classmethod
    def load(cls, user_id: int) -> "Conversation":
        path = CONV_DIR / f"{user_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return cls(user_id=user_id, contents=data.get("contents", []))
            except Exception as exc:
                log.warning("Impossibile leggere %s: %s", path, exc)
        return cls(user_id=user_id)

    def save(self) -> None:
        self.path.write_text(
            json.dumps({"contents": self.contents}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, role: str, parts: list[dict[str, Any]]) -> None:
        self.contents.append({"role": role, "parts": parts})
        # Trim mantenendo gli ultimi MAX_TURNS turni (user+model)
        if len(self.contents) > MAX_TURNS * 2:
            self.contents = self.contents[-MAX_TURNS * 2 :]
        self.save()

    def reset(self) -> None:
        self.contents = []
        self.save()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def is_allowed(update: Update) -> bool:
    if not ALLOWED_IDS:
        return False
    user = update.effective_user
    return user is not None and user.id in ALLOWED_IDS


async def deny(update: Update) -> None:
    user = update.effective_user
    uid = user.id if user else "?"
    log.warning("Accesso negato a user_id=%s", uid)
    if update.effective_message:
        await update.effective_message.reply_text(
            f"Accesso non autorizzato. Il tuo user_id Telegram e': `{uid}`\n"
            "Aggiungilo alla whitelist TELEGRAM_ALLOWED_USER_IDS per usare il bot.",
            parse_mode=ParseMode.MARKDOWN,
        )


# ---------------------------------------------------------------------------
# Chiamata Gemini
# ---------------------------------------------------------------------------


def build_config() -> gtypes.GenerateContentConfig:
    tools: list[gtypes.Tool] = []
    if ENABLE_WEB_SEARCH:
        # Google Search grounding: il modello puo' interrogare Google per dati
        # aggiornati (quotazioni, news, dati macro).
        tools.append(gtypes.Tool(google_search=gtypes.GoogleSearch()))
    return gtypes.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.4,
        # 8192 e' il massimo per Gemini 2.5 Flash/Pro. Configurabile via env
        # nel caso si voglia ridurre per contenere i costi.
        max_output_tokens=int(os.environ.get("MAX_OUTPUT_TOKENS", "8192")),
        tools=tools or None,
    )


def call_gemini(conv: Conversation) -> str:
    """Chiama Gemini con la storia conversazione e ritorna il testo finale.

    Se la risposta viene troncata per limite di token (finish_reason
    MAX_TOKENS), aggiunge un avviso visibile in fondo al testo.
    """
    response = client.models.generate_content(
        model=MODEL,
        contents=conv.contents,
        config=build_config(),
    )

    text = (response.text or "").strip()

    # Estrai il finish_reason del primo candidato per capire se la risposta
    # e' stata troncata.
    finish_reason = None
    try:
        if response.candidates:
            fr = response.candidates[0].finish_reason
            finish_reason = getattr(fr, "name", str(fr)) if fr is not None else None
    except Exception:
        finish_reason = None

    if finish_reason and finish_reason not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
        log.warning("Gemini finish_reason=%s (risposta possibilmente troncata)", finish_reason)
        if finish_reason == "MAX_TOKENS":
            text = (text or "[risposta troncata]") + (
                "\n\n_[Risposta troncata: limite token raggiunto. "
                "Scrivimi 'continua' per il resto, oppure riformula in modo piu' specifico.]_"
            )

    if not text:
        text = "[risposta vuota dal modello]"

    # Salva la risposta come turno "model" con un singolo blocco testo.
    conv.add("model", [{"text": text}])
    return text


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        await deny(update)
        return
    await update.message.reply_text(WELCOME_MESSAGE, parse_mode=ParseMode.MARKDOWN)


async def help_cmd(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        await deny(update)
        return
    await update.message.reply_text(WELCOME_MESSAGE, parse_mode=ParseMode.MARKDOWN)


async def reset_cmd(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        await deny(update)
        return
    conv = Conversation.load(update.effective_user.id)
    conv.reset()
    await update.message.reply_text(
        "Conversazione resettata. Ripartiamo da zero - mandami uno screenshot quando vuoi."
    )


async def portfolio_cmd(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        await deny(update)
        return
    conv = Conversation.load(update.effective_user.id)
    if not conv.contents:
        await update.message.reply_text(
            "Non ho ancora visto il tuo portafoglio. Mandami uno screenshot da Directa."
        )
        return
    conv.add(
        "user",
        [
            {
                "text": (
                    "Riepiloga sinteticamente il portafoglio che hai visto finora: "
                    "posizioni principali, controvalore totale stimato e allocation "
                    "per asset class. Solo i fatti, senza nuove raccomandazioni."
                )
            }
        ],
    )
    await update.effective_chat.send_action(ChatAction.TYPING)
    reply = await asyncio.to_thread(call_gemini, conv)
    await send_long(update, reply)


async def on_text(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        await deny(update)
        return
    text = update.message.text or ""
    if not text.strip():
        return
    conv = Conversation.load(update.effective_user.id)
    conv.add("user", [{"text": text}])
    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        reply = await asyncio.to_thread(call_gemini, conv)
    except Exception as exc:
        log.exception("Errore chiamata Gemini")
        await update.message.reply_text(f"Errore nell'analisi: {exc}")
        return
    await send_long(update, reply)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        await deny(update)
        return
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    data = await file.download_as_bytearray()
    b64 = base64.standard_b64encode(bytes(data)).decode("ascii")
    caption = (update.message.caption or "").strip()

    parts: list[dict[str, Any]] = [
        {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
        {
            "text": (
                caption
                or "Questo e' uno screenshot del mio portafoglio Directa. "
                "Estrai le posizioni, calcola l'allocation, e dimmi cosa noti. "
                "Se i numeri non sono leggibili, chiedimelo."
            )
        },
    ]

    conv = Conversation.load(update.effective_user.id)
    conv.add("user", parts)
    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        reply = await asyncio.to_thread(call_gemini, conv)
    except Exception as exc:
        log.exception("Errore chiamata Gemini (foto)")
        await update.message.reply_text(f"Errore nell'analisi dell'immagine: {exc}")
        return
    await send_long(update, reply)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Accetta immagini inviate come file (HEIC dal Pixel a volte arriva cosi')."""
    if not is_allowed(update):
        await deny(update)
        return
    doc = update.message.document
    if not doc or not (doc.mime_type or "").startswith("image/"):
        await update.message.reply_text(
            "Per ora gestisco solo immagini. Mandami uno screenshot del portafoglio."
        )
        return
    file = await context.bot.get_file(doc.file_id)
    data = await file.download_as_bytearray()
    b64 = base64.standard_b64encode(bytes(data)).decode("ascii")
    caption = (update.message.caption or "").strip()
    parts = [
        {"inline_data": {"mime_type": doc.mime_type or "image/jpeg", "data": b64}},
        {
            "text": caption
            or "Screenshot portafoglio Directa - estrai posizioni e analizza."
        },
    ]
    conv = Conversation.load(update.effective_user.id)
    conv.add("user", parts)
    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        reply = await asyncio.to_thread(call_gemini, conv)
    except Exception as exc:
        log.exception("Errore chiamata Gemini (documento)")
        await update.message.reply_text(f"Errore: {exc}")
        return
    await send_long(update, reply)


# ---------------------------------------------------------------------------
# Utility: invio messaggi lunghi (limite Telegram: 4096 char)
# ---------------------------------------------------------------------------


async def send_long(update: Update, text: str) -> None:
    LIMIT = 3800
    if len(text) <= LIMIT:
        try:
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(text)
        return
    chunks: list[str] = []
    buf = ""
    for para in text.split("\n\n"):
        if len(buf) + len(para) + 2 > LIMIT:
            chunks.append(buf)
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    for ch in chunks:
        try:
            await update.message.reply_text(ch, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(ch)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    if not ALLOWED_IDS:
        log.warning(
            "ATTENZIONE: TELEGRAM_ALLOWED_USER_IDS non impostato. "
            "Il bot rifiutera' tutti i messaggi finche' non aggiungi il tuo user_id."
        )

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("portfolio", portfolio_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    mode = os.environ.get("MODE", "polling").lower()
    log.info(
        "Atlas avviato. Modello=%s, web_search=%s, mode=%s",
        MODEL, ENABLE_WEB_SEARCH, mode,
    )

    if mode == "webhook":
        webhook_url = os.environ.get("WEBHOOK_URL", "").rstrip("/")
        if not webhook_url:
            raise RuntimeError(
                "MODE=webhook ma WEBHOOK_URL non impostata. "
                "Su Render imposta WEBHOOK_URL al tuo URL pubblico "
                "(es. https://atlas-bot.onrender.com)."
            )
        # Path segreto nell'URL: chiunque conosca questo path puo' iniettare
        # update fasulli. Default: usa una parte del token per renderlo non
        # indovinabile, ma e' meglio impostarlo a mano.
        secret_path = os.environ.get(
            "WEBHOOK_SECRET_PATH",
            TELEGRAM_TOKEN.split(":")[-1][:16],
        )
        port = int(os.environ.get("PORT", "10000"))
        full_url = f"{webhook_url}/{secret_path}"
        log.info("Webhook in ascolto su 0.0.0.0:%s, URL pubblico %s", port, full_url)
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=secret_path,
            webhook_url=full_url,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
    else:
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

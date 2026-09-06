import os
import logging
import httpx
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from uptime_kuma_api import UptimeKumaApi

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment Variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
TELEGRAM_ADMIN_IDS = [int(id_str) for id_str in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",") if id_str.strip()]

OMNISEARCH_URL = os.getenv("OMNISEARCH_URL", "http://localhost:8008")
AUDIOBOOKSHELF_URL = os.getenv("AUDIOBOOKSHELF_URL", "http://localhost:13378")
UPTIME_KUMA_URL = os.getenv("UPTIME_KUMA_URL", "http://localhost:3001")
KUMA_USER = os.getenv("KUMA_USER", "admin")
KUMA_PASS = os.getenv("KUMA_PASS", "admin")
CAMERA_INGEST_URL = os.getenv("CAMERA_INGEST_URL", "http://localhost:8080")

def is_admin(update: Update) -> bool:
    if not update.effective_user:
        return False
    if not TELEGRAM_ADMIN_IDS:
        return False
    return update.effective_user.id in TELEGRAM_ADMIN_IDS

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Unauthorized access.")
        return
    await update.message.reply_text("Welcome to Homelab Ops Bot!")

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Unauthorized access.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /search <query>")
        return

    query = " ".join(context.args)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{OMNISEARCH_URL}/search", params={"q": query})
            response.raise_for_status()
            results = response.json().get("results", [])

            if not results:
                await update.message.reply_text("No matches found.")
                return

            reply_text = f"Top matches for '{query}':\n\n"
            for res in results[:3]:
                title = res.get('title', 'Unknown')
                ts = res.get('timestamp', '0.0')
                thumb = res.get('thumbnail', 'No thumbnail')
                reply_text += f"- {title} (T: {ts}s)\n  {thumb}\n"

            await update.message.reply_text(reply_text)
    except Exception as e:
        logger.error(f"Search failed: {e}")
        await update.message.reply_text(f"Search failed: {e}")

async def briefing_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Unauthorized access.")
        return

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{AUDIOBOOKSHELF_URL}/generate_briefing")
            response.raise_for_status()

            data = response.json()
            if "audio_url" not in data:
                raise ValueError("Missing 'audio_url' in response")

            audio_url = data["audio_url"]
            await update.message.reply_audio(audio_url, caption="Morning briefing generated")
    except Exception as e:
        logger.error(f"Briefing generation failed: {e}")
        await update.message.reply_text(f"Briefing generation failed: {e}")


def _fetch_kuma_status():
    api = UptimeKumaApi(UPTIME_KUMA_URL)
    api.login(KUMA_USER, KUMA_PASS)

    monitors = api.get_monitors()

    up_count = 0
    down_count = 0
    report = "📊 **Homelab Status**\n\n"

    for monitor in monitors:
        m_id = monitor["id"]
        name = monitor["name"]

        try:
            heartbeats = api.get_heartbeats(m_id)
            if heartbeats and len(heartbeats) > 0:
                latest = heartbeats[-1]
                is_up = latest.get("status") == 1
            else:
                is_up = False
        except Exception as e:
            logger.error(f"Failed to get heartbeats for {name}: {e}")
            is_up = False

        status_text = "🟢 UP" if is_up else "🔴 DOWN"
        if is_up:
            up_count += 1
        else:
            down_count += 1

        report += f"- {name}: {status_text}\n"

    report += f"\nTotal: {len(monitors)} | 🟢 {up_count} | 🔴 {down_count}"

    api.disconnect()
    return report


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Unauthorized access.")
        return

    try:
        report = await asyncio.to_thread(_fetch_kuma_status)
        await update.message.reply_text(report, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        await update.message.reply_text(f"Status check failed: {e}")

async def ingest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Unauthorized access.")
        return

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{CAMERA_INGEST_URL}/status")
            response.raise_for_status()

            data = response.json()
            status = data.get("status", "Unknown")
            pending = data.get("pending_files", 0)

            await update.message.reply_text(f"Camera Ingest Status: {status}\nPending Files: {pending}")
    except Exception as e:
        logger.error(f"Ingest check failed: {e}")
        await update.message.reply_text(f"Ingest check failed: {e}")

def create_app():
    if TELEGRAM_TOKEN == "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11":
        logger.warning("Using mock token, only suitable for testing.")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("briefing", briefing_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("ingest", ingest_command))

    return app

if __name__ == "__main__":
    app = create_app()
    if TELEGRAM_TOKEN != "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11":
        app.run_polling()

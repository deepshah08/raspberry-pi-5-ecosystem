import os
import json
import httpx
import logging
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
import uvicorn

app = FastAPI(title="Uptime Kuma Alert Bridge")

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
LOG_FILE = os.getenv("NAS_SLO_WATCHDOG_LOG", "nas_slo_watchdog.log")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def send_telegram_alert(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("Telegram credentials not set. Skipping Telegram alert.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            logging.info("Successfully sent Telegram alert")
        except Exception as e:
            logging.error(f"Failed to send Telegram alert: {e}")

def log_to_watchdog(payload: dict):
    try:
        timestamp = datetime.now().isoformat()
        log_entry = {
            "timestamp": timestamp,
            "incident": payload,
            "source": "uptime-kuma"
        }
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
        logging.info(f"Logged incident to {LOG_FILE}")
    except Exception as e:
        logging.error(f"Failed to log to watchdog file: {e}")

@app.post("/webhook")
async def handle_webhook(request: Request):
    try:
        payload = await request.json()
        logging.info(f"Received webhook: {payload}")

        if not payload or "msg" not in payload:
            raise HTTPException(status_code=400, detail="Invalid payload: missing 'msg' field")

        monitor_name = payload.get("monitor", {}).get("name", "Unknown Monitor")
        status = payload.get("heartbeat", {}).get("status", "Unknown")
        msg = payload.get("msg")

        # Format message
        status_emoji = "🟢" if status == 1 else "🔴"
        message = f"{status_emoji} <b>Uptime Kuma Alert</b>\n\n<b>Monitor:</b> {monitor_name}\n<b>Status:</b> {status}\n<b>Message:</b> {msg}"

        # Dispatch
        await send_telegram_alert(message)
        log_to_watchdog(payload)

        return {"status": "success", "message": "Alert processed and dispatched"}
    except HTTPException as he:
        raise he
    except Exception as e:
        logging.error(f"Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

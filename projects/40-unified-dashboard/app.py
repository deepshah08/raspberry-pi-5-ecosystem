import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Unified Search & Daily Briefing PWA Dashboard")

# Mount static files and templates
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

OMNISEARCH_URL = os.getenv("OMNISEARCH_URL", "http://localhost:8008")
AUDIOBOOKSHELF_URL = os.getenv("AUDIOBOOKSHELF_URL", "http://localhost:13378")
UPTIME_KUMA_URL = os.getenv("UPTIME_KUMA_URL", "http://localhost:3001")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={})

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/api/search")
async def proxy_search(q: str = ""):
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{OMNISEARCH_URL}/api/search", params={"q": q})
            if response.status_code == 200:
                return response.json()
    except Exception:
        pass

    # Mock fallback
    return {
        "results": [
            {
                "id": "1",
                "title": f"Result for {q}",
                "confidence": 0.95,
                "timestamp": "01:23",
                "image_url": "https://via.placeholder.com/150",
                "snippet": "This is a mocked result from OmniSearch Gateway."
            }
        ]
    }

@app.get("/api/briefing")
async def proxy_briefing():
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{AUDIOBOOKSHELF_URL}/api/podcasts/latest")
            if response.status_code == 200:
                return response.json()
    except Exception:
        pass

    # Mock fallback
    return {
        "audio_url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
        "title": "Latest Morning Briefing (Mock)"
    }

@app.get("/api/status")
async def proxy_status():
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{UPTIME_KUMA_URL}/api/status")
            if response.status_code == 200:
                return response.json()
    except Exception:
        pass

    # Mock fallback
    return {
        "status": "operational",
        "services": {
            "nas": "up",
            "pi5": "up",
            "gateway": "down"
        }
    }

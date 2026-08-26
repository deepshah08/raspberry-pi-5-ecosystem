import os
import socket
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException

SERVICE_TYPE = "_tripdrop._tcp.local."
PORT = 8088
HOSTNAME = socket.gethostname()

class PeerListener:
    def __init__(self):
        self.peers = {}

    def remove_service(self, zeroconf, type, name):
        if name in self.peers:
            del self.peers[name]

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        if info:
            addresses = [socket.inet_ntoa(addr) for addr in info.addresses]
            self.peers[name] = {
                "addresses": addresses,
                "port": info.port,
                "server": info.server,
            }

listener = PeerListener()

@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("uploads", exist_ok=True)
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok", "service": "tripdrop"}

@app.get("/peers")
async def get_peers():
    return {"peers": listener.peers}

@app.post("/upload/{filename:path}")
async def upload_file(filename: str, request: Request):
    file_path = os.path.join("uploads", os.path.basename(filename))
    try:
        with open(file_path, "wb") as f:
            async for chunk in request.stream():
                f.write(chunk)
        return {"status": "success", "filename": os.path.basename(filename)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

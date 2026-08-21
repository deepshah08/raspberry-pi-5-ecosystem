import asyncio
import os
import socket
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf

SERVICE_TYPE = "_tripdrop._tcp.local."
PORT = 8000
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

    def update_service(self, zeroconf, type, name):
        self.add_service(zeroconf, type, name)

zeroconf: Zeroconf = None
listener: PeerListener = None
service_info: ServiceInfo = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global zeroconf, listener, service_info

    os.makedirs("uploads", exist_ok=True)

    if os.environ.get("TESTING") != "1":
        zeroconf = Zeroconf()
        listener = PeerListener()
        browser = ServiceBrowser(zeroconf, SERVICE_TYPE, listener)

        ip_address = socket.gethostbyname(socket.gethostname())
        if ip_address == '127.0.0.1':
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(('10.255.255.255', 1))
                ip_address = s.getsockname()[0]
            except Exception:
                ip_address = '127.0.0.1'
            finally:
                s.close()

        addresses = [socket.inet_aton(ip_address)]
        service_info = ServiceInfo(
            SERVICE_TYPE,
            f"{HOSTNAME}._tripdrop._tcp.local.",
            addresses=addresses,
            port=PORT,
            server=f"{HOSTNAME}.local.",
        )
        zeroconf.register_service(service_info)
    else:
        listener = PeerListener()
        listener.peers = {"test_peer": {"addresses": ["127.0.0.1"], "port": 8000, "server": "test.local."}}

    yield

    if zeroconf and service_info and os.environ.get("TESTING") != "1":
        zeroconf.unregister_service(service_info)
        zeroconf.close()

app = FastAPI(lifespan=lifespan)

@app.post("/upload/{filename:path}")
async def upload_file(filename: str, request: Request):
    """Handle chunked upload of a file"""
    file_path = os.path.join("uploads", filename)
    if os.path.dirname(file_path) != "uploads":
        raise HTTPException(status_code=400, detail="Invalid filename")
    try:
        with open(file_path, "wb") as f:
            async for chunk in request.stream():
                f.write(chunk)
        return {"status": "success", "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/peers")
async def get_peers():
    """Return a list of discovered peers"""
    if listener:
        return {"peers": listener.peers}
    return {"peers": {}}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)

import asyncio
import json
import logging
import os
import uvicorn
import socket
from typing import List
from fastapi import UploadFile, File, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from dashboard import app
from core.async_agent import AsyncAgent
from core.monitor import Monitor
from core.proxy_manager import ProxyManager

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MoltyBot.Orchestrator")

# Global Variables
AGENTS: List[AsyncAgent] = []
RUNNING_AGENT_NAMES = set()
GLOBAL_PROXIES = []

def check_local_tor():
    """Detect if local Tor multi-instances (9050-9060) are active."""
    tor_proxies = []
    for port in range(9050, 9061):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.1)
            if s.connect_ex(('127.0.0.1', port)) == 0:
                tor_proxies.append(f"socks5://127.0.0.1:{port}")
    return tor_proxies

async def start_agents(json_data=None):
    """Startup with Auto-Tor and Proxy Validation."""
    accounts = load_accounts(json_data)
    if not accounts:
        logger.warning("No accounts to load. Waiting for manual upload...")
        return

    # 1. Prioritas: Gunakan Tor Lokal (Jika di Armbian)
    proxy_list = check_local_tor()
    
    # 2. Alternatif: Gunakan Proxy yang di-upload
    if not proxy_list and GLOBAL_PROXIES:
        proxy_list = await ProxyManager.get_healthy_proxies(GLOBAL_PROXIES, target_count=len(accounts))
    
    # 3. Alternatif Terakhir: Scrape otomatis (Jika di Railway)
    if not proxy_list:
        logger.info("No local Tor or uploaded proxies. Scraping public proxies...")
        proxy_list = await ProxyManager.get_healthy_proxies(target_count=len(accounts))

    logger.info(f"Using {len(proxy_list)} different IPs for {len(accounts)} agents.")
    
    for i, acc in enumerate(accounts):
        name = acc.get("name", f"Agent_{i}")
        if name in RUNNING_AGENT_NAMES: continue

        key = acc.get("apikey") or acc.get("api_key") or acc.get("key")
        wallet = acc.get("walletaddress") or acc.get("wallet_address") or acc.get("wallet")
        if not key: continue

        # Logic: Max 5 bots per IP
        proxy = None
        proxy_info = "Direct"
        if proxy_list:
            # Gunakan IP ke-(i/5) agar setiap IP pegang max 5 bot
            proxy_idx = (i // 5) % len(proxy_list)
            proxy = proxy_list[proxy_idx]
            proxy_info = proxy.split('/')[-1] # Tampilkan port saja untuk Tor

        agent = AsyncAgent(name=name, api_key=key, wallet_address=wallet, proxy=proxy, index=i)
        AGENTS.append(agent)
        RUNNING_AGENT_NAMES.add(name)
        
        Monitor.update(name, proxy=proxy_info, proxy_status="Connecting...")
        asyncio.create_task(agent.start())
        await asyncio.sleep(0.5)

@app.post("/api/upload-proxies")
async def upload_proxies(file: UploadFile = File(...)):
    global GLOBAL_PROXIES
    try:
        content = await file.read()
        text = content.decode('utf-8')
        GLOBAL_PROXIES = [line.strip() for line in text.split('\n') if line.strip()]
        return {"status": "success", "message": f"{len(GLOBAL_PROXIES)} proxies queued."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/upload-accounts")
async def upload_accounts(file: UploadFile = File(...)):
    try:
        content = await file.read()
        json_data = json.loads(content)
        asyncio.create_task(start_agents(json_data))
        return {"status": "success", "message": "Starting bots..."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def load_accounts(json_data=None):
    if json_data: return json_data
    json_path = "mort_royal_bots_export.json"
    if os.path.exists(json_path):
        with open(json_path, 'r') as f:
            data = json.load(f)
            return data.get("accounts", data) if isinstance(data, dict) else data
    return []

@app.on_event("startup")
async def on_startup():
    """Smart detection for Local vs Railway startup."""
    is_railway = os.environ.get("RAILWAY_ENVIRONMENT_ID") or os.environ.get("RAILWAY_STATIC_URL")
    
    if is_railway:
        logger.info("--- [ENVIRONMENT: RAILWAY + TOR DOCKER] ---")
        # Beri waktu tambahan agar Tor benar-benar konek (100%)
        await asyncio.sleep(10)
    else:
        logger.info("--- [ENVIRONMENT: LOCAL / ARMBIAN] ---")
        asyncio.create_task(start_agents())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")

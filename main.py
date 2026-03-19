import asyncio
import json
import logging
import os
import uvicorn
import socket
import re
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
    tor_proxies = []
    for port in range(9050, 9061):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.1)
            if s.connect_ex(('127.0.0.1', port)) == 0:
                tor_proxies.append(f"socks5://127.0.0.1:{port}")
    return tor_proxies

async def start_agents(json_data=None):
    accounts = load_accounts(json_data)
    if not accounts:
        logger.warning("No accounts to load.")
        return

    global GLOBAL_PROXIES
    proxy_list = []

    if GLOBAL_PROXIES:
        logger.info(f"Dashboard Proxies detected: {len(GLOBAL_PROXIES)} IPs.")
        proxy_list = await ProxyManager.get_healthy_proxies(GLOBAL_PROXIES, target_count=len(accounts))

    if not proxy_list:
        proxy_list = check_local_tor()
        if proxy_list: logger.info(f"Using {len(proxy_list)} local Tor instances.")

    if not proxy_list and os.path.exists("proxies.txt"):
        try:
            with open("proxies.txt", "r") as f:
                lines = [line.strip() for line in f if line.strip()]
                proxy_list = await ProxyManager.get_healthy_proxies(lines, target_count=len(accounts))
        except: pass

    if not proxy_list:
        logger.info("Scraping public proxies...")
        proxy_list = await ProxyManager.get_healthy_proxies(target_count=len(accounts))

    logger.info(f"Using {len(proxy_list)} different IPs for {len(accounts)} agents.")
    
    for i, acc in enumerate(accounts):
        name = acc.get("name", f"Agent_{i}")
        if name in RUNNING_AGENT_NAMES: continue

        key = acc.get("apikey") or acc.get("api_key") or acc.get("key")
        wallet = acc.get("walletaddress") or acc.get("wallet_address") or acc.get("wallet")
        if not key: continue

        proxy = None
        proxy_display = "Direct"
        if proxy_list:
            proxy = proxy_list[i % len(proxy_list)]
            # Display cleanup logic
            if "@" in proxy:
                proxy_display = proxy.split('@')[-1]
            else:
                proxy_display = proxy.replace("http://", "").replace("socks5://", "").replace("socks4://", "")
        
        agent = AsyncAgent(name=name, api_key=key, wallet_address=wallet, proxy=proxy, index=i)
        AGENTS.append(agent)
        RUNNING_AGENT_NAMES.add(name)
        
        Monitor.update(name, proxy=proxy_display, proxy_status="Connecting...")
        asyncio.create_task(agent.start())
        await asyncio.sleep(0.5)

from fastapi import Form

@app.post("/api/upload-proxies")
async def upload_proxies(file: UploadFile = File(...), user: str = Form(None), pass_: str = Form(None, alias="pass")):
    global GLOBAL_PROXIES
    try:
        content = await file.read()
        text = content.decode('utf-8')
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        processed = []
        global_auth = f"{user}:{pass_}" if user and pass_ else ""
        
        for l in lines:
            # Jika sudah ada protokol, simpan apa adanya
            if "://" in l:
                processed.append(l); continue
            
            # Jika ada format IP:PORT:USER:PASS, gunakan auth baris tersebut
            m = re.match(r'^([\d\.]+):(\d+):([^:]+):([^:]+)$', l)
            if m:
                processed.append(f"http://{m.group(3)}:{m.group(4)}@{m.group(1)}:{m.group(2)}")
                continue

            # Jika format IP:PORT, gunakan Global Auth (jika ada)
            m = re.match(r'^([\d\.]+):(\d+)$', l)
            if m:
                if global_auth:
                    processed.append(f"http://{global_auth}@{m.group(1)}:{m.group(2)}")
                else:
                    processed.append(f"http://{l}")
                continue
            
            processed.append(f"http://{l}")

        GLOBAL_PROXIES = processed
        return {"status": "success", "message": f"Loaded {len(processed)} proxies. Global Auth: {'Active' if global_auth else 'None'}"}
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
    is_railway = os.environ.get("RAILWAY_ENVIRONMENT_ID") or os.environ.get("RAILWAY_STATIC_URL")
    if is_railway:
        logger.info("--- [ENVIRONMENT: RAILWAY] ---")
        await asyncio.sleep(10)
    else:
        logger.info("--- [ENVIRONMENT: LOCAL] ---")
        asyncio.create_task(start_agents())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")

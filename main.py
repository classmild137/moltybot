import asyncio
import json
import logging
import os
import uvicorn
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

def load_accounts(json_data=None):
    """Load accounts from file or raw JSON data"""
    if json_data:
        data = json_data
    else:
        json_path = "mort_royal_bots_export.json"
        if not os.path.exists(json_path):
            return []
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
        except:
            return []

    if isinstance(data, dict) and "accounts" in data:
        data = data["accounts"]
    return data if isinstance(data, list) else []

async def start_agents(json_data=None):
    """Startup or Hot-load agents with Proxy Validation."""
    accounts = load_accounts(json_data)
    if not accounts:
        logger.warning("No accounts to load. Waiting for manual upload...")
        return

    global GLOBAL_PROXIES
    # 1. Pilih sumber proxy
    proxy_source = GLOBAL_PROXIES
    if not proxy_source and os.path.exists("proxies.txt"):
        try:
            with open("proxies.txt", "r") as f:
                proxy_source = [line.strip() for line in f if line.strip()]
        except: pass

    # 2. Jika tidak ada proxy sama sekali, coba scrape darurat
    if not proxy_source:
        logger.info("No proxies found. Emergency scraping initiated...")
        proxy_source = await ProxyManager.scrape_free_proxies()

    # 3. Test Proxy (Filter hanya yang hidup)
    logger.info("Validating proxies against Molty Royale API...")
    healthy_proxies = await ProxyManager.get_healthy_proxies(proxy_source, target_count=len(accounts))
    
    if not healthy_proxies:
        logger.warning("NO HEALTHY PROXIES FOUND! Bots will attempt Direct connection.")

    logger.info(f"Starting {len(accounts)} agents with {len(healthy_proxies)} working proxies.")
    
    for i, acc in enumerate(accounts):
        name = acc.get("name", f"Agent_{i}")
        if name in RUNNING_AGENT_NAMES:
            continue

        key = acc.get("apikey") or acc.get("api_key") or acc.get("key")
        wallet = acc.get("walletaddress") or acc.get("wallet_address") or acc.get("wallet")

        if not key: continue

        # Distribution logic: Max 5 bots per proxy
        proxy = None
        proxy_info = "Direct"
        if healthy_proxies:
            if i < (len(healthy_proxies) * 5):
                proxy = healthy_proxies[i % len(healthy_proxies)]
                proxy_info = proxy.split('@')[-1]
        
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
        logger.info(f"Loaded {len(GLOBAL_PROXIES)} proxies via API")
        return {"status": "success", "message": f"Successfully loaded {len(GLOBAL_PROXIES)} proxies into queue. Start Agents to begin testing."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to load proxies: {str(e)}"}

@app.post("/api/upload-accounts")
async def upload_accounts(file: UploadFile = File(...)):
    try:
        content = await file.read()
        json_data = json.loads(content)
        asyncio.create_task(start_agents(json_data))
        return {"status": "success", "message": "Accounts loaded! Testing proxies and starting bots..."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to load JSON: {str(e)}"}

@app.on_event("startup")
async def on_startup():
    """Smart detection for Local vs Railway startup."""
    is_railway = os.environ.get("RAILWAY_ENVIRONMENT_ID") or os.environ.get("RAILWAY_STATIC_URL")
    if not is_railway:
        asyncio.create_task(start_agents())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")

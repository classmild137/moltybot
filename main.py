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
    """Startup or Hot-load agents with In-Memory Proxy Support."""
    accounts = load_accounts(json_data)
    if not accounts:
        logger.warning("No accounts to load. Waiting for manual upload...")
        return

    # Use proxies from memory or file
    proxy_list = GLOBAL_PROXIES
    if not proxy_list and os.path.exists("proxies.txt"):
        try:
            with open("proxies.txt", "r") as f:
                proxy_list = [line.strip() for line in f if line.strip()]
        except:
            pass

    logger.info(f"Processing {len(accounts)} accounts with {len(proxy_list)} proxies...")
    
    for i, acc in enumerate(accounts):
        name = acc.get("name", f"Agent_{i}")
        if name in RUNNING_AGENT_NAMES:
            continue

        key = acc.get("apikey") or acc.get("api_key") or acc.get("key")
        wallet = acc.get("walletaddress") or acc.get("wallet_address") or acc.get("wallet")

        if not key: continue

        # Jika punya 10 proxy dan 55 akun: 
        # i=0-49 akan dapat proxy (round-robin), i=50-54 akan dapat None (Direct IP)
        proxy = None
        proxy_info = "Direct"
        if proxy_list and i < (len(proxy_list) * 5): # Maks 5 bot per proxy (Safety Limit)
            proxy = proxy_list[i % len(proxy_list)]
            # Masking user:pass untuk display
            p_parts = proxy.split('@')
            proxy_info = p_parts[-1] if len(p_parts) > 1 else proxy
        
        agent = AsyncAgent(name=name, api_key=key, wallet_address=wallet, proxy=proxy)
        AGENTS.append(agent)
        RUNNING_AGENT_NAMES.add(name)
        
        # Update monitor awal
        Monitor.update(name, proxy=proxy_info, proxy_status="Connecting...")
        
        asyncio.create_task(agent.start())
        await asyncio.sleep(1)

@app.post("/api/upload-proxies")
async def upload_proxies(file: UploadFile = File(...)):
    global GLOBAL_PROXIES
    try:
        content = await file.read()
        text = content.decode('utf-8')
        GLOBAL_PROXIES = [line.strip() for line in text.split('\n') if line.strip()]
        logger.info(f"Loaded {len(GLOBAL_PROXIES)} proxies via API")
        return {"status": "success", "message": f"Successfully loaded {len(GLOBAL_PROXIES)} proxies!"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to load proxies: {str(e)}"}

@app.post("/api/upload-accounts")
async def upload_accounts(file: UploadFile = File(...)):
    try:
        content = await file.read()
        json_data = json.loads(content)
        asyncio.create_task(start_agents(json_data))
        return {"status": "success", "message": "Successfully loaded accounts!"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to load JSON: {str(e)}"}

@app.on_event("startup")
async def on_startup():
    """Smart detection for Local vs Railway startup."""
    is_railway = os.environ.get("RAILWAY_ENVIRONMENT_ID") or os.environ.get("RAILWAY_STATIC_URL")
    
    if is_railway:
        logger.info("--- [ENVIRONMENT: RAILWAY] ---")
    else:
        logger.info("--- [ENVIRONMENT: LOCAL] ---")
        asyncio.create_task(start_agents())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")

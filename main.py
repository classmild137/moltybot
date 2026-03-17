import asyncio
import json
import logging
import os
import uvicorn
from typing import List

from dashboard import app
from core.async_agent import AsyncAgent

# Setup simple logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MoltyBot.Orchestrator")

from fastapi import UploadFile, File
from core.monitor import Monitor

AGENTS: List[AsyncAgent] = []
RUNNING_AGENT_NAMES = set()

def load_accounts(json_data=None):
    """Load accounts from file or raw JSON data"""
    if json_data:
        data = json_data
    else:
        json_path = "mort_royal_bots_export.json"
        if not os.path.exists(json_path):
            return []
        with open(json_path, 'r') as f:
            data = json.load(f)

    if isinstance(data, dict) and "accounts" in data:
        data = data["accounts"]
    return data if isinstance(data, list) else []

async def start_agents(json_data=None):
    """Startup or Hot-load agents."""
    accounts = load_accounts(json_data)
    if not accounts:
        logger.warning("No accounts to load. Waiting for manual upload via dashboard...")
        return

    logger.info(f"Processing {len(accounts)} accounts...")
    
    for i, acc in enumerate(accounts):
        name = acc.get("name", f"Agent_{i}")
        if name in RUNNING_AGENT_NAMES:
            continue

        key = acc.get("apikey") or acc.get("api_key") or acc.get("key")
        wallet = acc.get("walletaddress") or acc.get("wallet_address") or acc.get("wallet")

        if not key: continue

        agent = AsyncAgent(name=name, api_key=key, wallet_address=wallet)
        AGENTS.append(agent)
        RUNNING_AGENT_NAMES.add(name)
        
        asyncio.create_task(agent.start())
        await asyncio.sleep(1)

@app.post("/api/upload-accounts")
async def upload_accounts(file: UploadFile = File(...)):
    try:
        content = await file.read()
        json_data = json.loads(content)
        asyncio.create_task(start_agents(json_data))
        return {"status": "success", "message": f"Successfully loaded new accounts!"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to load JSON: {str(e)}"}

@app.on_event("startup")
async def on_startup():
    """Smart detection for Local vs Railway startup."""
    
    # Deteksi Railway via environment variable bawaan Railway
    is_railway = os.environ.get("RAILWAY_ENVIRONMENT_ID") or os.environ.get("RAILWAY_STATIC_URL")
    
    if is_railway:
        logger.info("--- [ENVIRONMENT: RAILWAY] ---")
        logger.info("Security Mode: Waiting for manual JSON upload via Dashboard.")
        # Jangan load file lokal di Railway untuk keamanan ekstra
    else:
        logger.info("--- [ENVIRONMENT: LOCAL / ARMBIAN] ---")
        json_path = "mort_royal_bots_export.json"
        if os.path.exists(json_path):
            logger.info(f"Auto-load enabled: Found {json_path}")
            asyncio.create_task(start_agents())
        else:
            logger.warning("Auto-load failed: 'mort_royal_bots_export.json' not found.")
            logger.info("Waiting for manual upload via Dashboard...")

if __name__ == "__main__":
    # Railway provides PORT env var
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")

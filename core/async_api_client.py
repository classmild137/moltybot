import aiohttp
import asyncio
import logging
from typing import Optional, Dict, Any, List
from aiohttp import ClientTimeout, ClientSession

logger = logging.getLogger("MoltyBot.AsyncAPI")

class APIError(Exception):
    def __init__(self, message: str, code: str = "UNKNOWN"):
        self.code = code
        super().__init__(f"[{code}] {message}")

class AsyncAPIClient:
    """
    Async implementation of the Molty Royale API Client.
    """
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = {
            "Content-Type": "application/json",
            "X-API-Key": api_key
        }
        self.timeout = ClientTimeout(total=15)

    async def _request(self, method: str, path: str, json: Dict = None, max_retries: int = 3) -> Any:
        url = f"{self.base_url}{path}"
        
        async with ClientSession(headers=self.headers, timeout=self.timeout) as session:
            for attempt in range(max_retries):
                try:
                    async with session.request(method, url, json=json) as resp:
                        # Parse JSON response safely
                        try:
                            data = await resp.json()
                        except:
                            # If non-JSON, likely a server error or timeout page
                            text = await resp.text()
                            logger.error(f"Invalid JSON response: {text[:100]}")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2 * (attempt + 1))
                                continue
                            raise APIError("Invalid JSON response", "SERVER_ERROR")

                        if not data.get("success", True):
                            error = data.get("error", {})
                            code = error.get("code", "UNKNOWN")
                            msg = error.get("message", "Unknown API error")
                            
                            # Fatal errors - do not retry
                            if code in ("AGENT_NOT_FOUND", "GAME_NOT_FOUND", "GAME_ALREADY_STARTED", 
                                      "ACCOUNT_ALREADY_IN_GAME", "ONE_AGENT_PER_API_KEY",
                                      "INSUFFICIENT_BALANCE", "GEO_RESTRICTED", "ALREADY_ACTED",
                                      "INSUFFICIENT_EP", "INVALID_ACTION", "MAX_AGENTS_REACHED"):
                                raise APIError(msg, code)
                                
                            logger.warning(f"API Error ({code}): {msg} (retry {attempt+1}/{max_retries})")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2 * (attempt + 1))
                                continue
                            raise APIError(msg, code)
                            
                        return data.get("data")

                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.debug(f"Network error on {path}: {str(e)}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 * (attempt + 1))
                        continue
                    raise APIError(f"Network error: {str(e)}", "NETWORK_ERROR")

    # -- Account Methods --
    async def get_account(self) -> Dict:
        return await self._request("GET", "/accounts/me")

    async def set_wallet(self, wallet_address: str) -> Dict:
        return await self._request("PUT", "/accounts/wallet", json={"wallet_address": wallet_address})

    # -- Game Methods --
    async def list_games(self, status: str = "waiting") -> List[Dict]:
        try:
            res = await self._request("GET", f"/games?status={status}", max_retries=2)
            return res if isinstance(res, list) else []
        except Exception:
            return []

    async def get_game(self, game_id: str) -> Dict:
        return await self._request("GET", f"/games/{game_id}")
        
    async def create_game(self, host_name: str, map_size: str = "medium", entry_type: str = "free") -> Dict:
        payload = {"hostName": host_name, "mapSize": map_size, "entryType": entry_type}
        return await self._request("POST", "/games", json=payload)

    async def register_agent(self, game_id: str, agent_name: str) -> Dict:
        return await self._request("POST", f"/games/{game_id}/agents/register", json={"name": agent_name})

    # -- Agent Methods --
    async def get_state(self, game_id: str, agent_id: str) -> Dict:
        return await self._request("GET", f"/games/{game_id}/agents/{agent_id}/state")

    async def take_action(self, game_id: str, agent_id: str, action: Dict, thought: Dict = None) -> Dict:
        payload = {"action": action}
        if thought:
            payload["thought"] = thought
        return await self._request("POST", f"/games/{game_id}/agents/{agent_id}/action", json=payload)

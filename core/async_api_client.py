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
    def __init__(self, base_url: str, api_key: str, proxy: str = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.proxy = proxy  # Format: "http://user:pass@host:port"
        self.headers = {
            "Content-Type": "application/json",
            "X-API-Key": api_key
        }
        self.timeout = ClientTimeout(total=15)

    async def _request(self, method: str, path: str, json: Dict = None, max_retries: int = 3) -> Any:
        url = f"{self.base_url}{path}"
        
        for attempt in range(max_retries):
            try:
                # Menggunakan proxy jika tersedia
                async with ClientSession(headers=self.headers, timeout=self.timeout) as session:
                    async with session.request(method, url, json=json, proxy=self.proxy) as resp:
                        # 1. Handle Rate Limit (429)
                        if resp.status == 429:
                            wait_time = 30 * (attempt + 1)
                            logger.warning(f"Rate Limit (429) hit! Cooling down for {wait_time}s...")
                            await asyncio.sleep(wait_time)
                            continue

                        # 2. Handle Unauthorized (401)
                        if resp.status == 401:
                            raise APIError("Invalid API Key (Unauthorized)", "UNAUTHORIZED")
                            
                        try:
                            response_json = await resp.json()
                        except:
                            text = await resp.text()
                            if "Cloudflare" in text or "challenge" in text:
                                logger.error("IP Blocked or Challenged by Cloudflare/WAF!")
                                await asyncio.sleep(60) # Heavy wait
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2)
                                continue
                            raise APIError(f"Invalid JSON/HTML: {text[:50]}", "SERVER_ERROR")

                        if not response_json.get("success", False):
                            error = response_json.get("error", {})
                            code = error.get("code", "UNKNOWN")
                            # Ambil pesan error asli dari server jika ada
                            msg = error.get("message") or response_json.get("message") or "API returned success: false"
                            
                            # Fatal errors
                            fatal = ("AGENT_NOT_FOUND", "GAME_NOT_FOUND", "UNAUTHORIZED")
                            if code in fatal:
                                raise APIError(msg, code)
                            
                            if attempt < max_retries - 1:
                                await asyncio.sleep(2)
                                continue
                            raise APIError(msg, code)
                        
                        # Kadang data ada di field 'data', kadang langsung di root
                        data = response_json.get("data")
                        return data if data is not None else response_json

            except APIError:
                raise
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                raise APIError(str(e), "CONNECTION_ERROR")

    async def get_account(self) -> Dict:
        return await self._request("GET", "/accounts/me")

    async def set_wallet(self, wallet_address: str) -> Dict:
        return await self._request("PUT", "/accounts/wallet", json={"wallet_address": wallet_address})

    async def list_games(self, status: str = "waiting") -> List[Dict]:
        try:
            res = await self._request("GET", f"/games?status={status}")
            return res if isinstance(res, list) else []
        except:
            return []

    async def get_game(self, game_id: str) -> Dict:
        return await self._request("GET", f"/games/{game_id}")

    async def register_agent(self, game_id: str, agent_name: str) -> Dict:
        return await self._request("POST", f"/games/{game_id}/agents/register", json={"name": agent_name})

    async def get_state(self, game_id: str, agent_id: str) -> Dict:
        return await self._request("GET", f"/games/{game_id}/agents/{agent_id}/state")

    async def take_action(self, game_id: str, agent_id: str, action: Dict, thought: Dict = None) -> Dict:
        payload = {"action": action}
        if thought:
            payload["thought"] = thought
        return await self._request("POST", f"/games/{game_id}/agents/{agent_id}/action", json=payload)

import aiohttp
import asyncio
import logging
from typing import Optional, Dict, Any, List
from aiohttp import ClientTimeout, ClientSession
from aiohttp_socks import ProxyConnector

logger = logging.getLogger("MoltyBot.AsyncAPI")

class APIError(Exception):
    def __init__(self, message: str, code: str = "UNKNOWN"):
        self.code = code
        super().__init__(f"[{code}] {message}")

class AsyncAPIClient:
    def __init__(self, base_url: str, api_key: str, proxy: str = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.proxy = proxy
        self.headers = {
            "Content-Type": "application/json",
            "X-API-Key": api_key
        }
        self.timeout = ClientTimeout(total=10) # Strict 10s for anti-lag
        self._session: Optional[ClientSession] = None

    async def get_session(self) -> ClientSession:
        """Get or create a persistent session for this agent."""
        if self._session is None or self._session.closed:
            connector = None
            if self.proxy:
                try:
                    connector = ProxyConnector.from_url(self.proxy, ssl=False)
                except Exception as e:
                    logger.error(f"Proxy Error: {e}")
            
            self._session = ClientSession(
                headers=self.headers, 
                timeout=self.timeout, 
                connector=connector
            )
        return self._session

    async def close(self):
        """Close the session properly."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(self, method: str, path: str, json: Dict = None, max_retries: int = 3) -> Any:
        url = f"{self.base_url}{path}"
        
        for attempt in range(max_retries):
            try:
                session = await self.get_session()
                async with session.request(method, url, json=json) as resp:
                    # 1. Handle IP Whitelist/Auth Block (403/407)
                    if resp.status in (403, 407):
                        raise APIError(f"Proxy Blocked (IP not whitelisted or Auth required)", "PROXY_AUTH_ERROR")

                    if resp.status == 429:
                        await asyncio.sleep(30 * (attempt + 1))
                        continue

                    if resp.status == 401:
                        raise APIError("Unauthorized", "UNAUTHORIZED")
                        
                    try:
                        data = await resp.json()
                    except:
                        text = await resp.text()
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)
                            continue
                        # Potong teks agar tidak merusak dashboard, tapi cukup untuk dibaca
                        debug_msg = text[:60].replace("\n", " ")
                        raise APIError(f"Invalid JSON: {debug_msg}", "SERVER_ERROR")

                    if not data.get("success", False):
                        code = data.get("error", {}).get("code", "UNKNOWN")
                        msg = data.get("error", {}).get("message", "API Error")
                        
                        if code in ("AGENT_NOT_FOUND", "GAME_NOT_FOUND", "UNAUTHORIZED"):
                            raise APIError(msg, code)
                        
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)
                            continue
                        raise APIError(msg, code)
                    
                    return data.get("data") if data.get("data") is not None else data

            except APIError:
                raise
            except Exception as e:
                # Jika session error, tutup dan paksa buat baru di retry berikutnya
                await self.close()
                if attempt < max_retries - 1:
                    await asyncio.sleep(3)
                    continue
                raise APIError(str(e), "CONNECTION_ERROR")

    # API Methods remain the same
    async def get_account(self) -> Dict: return await self._request("GET", "/accounts/me")
    async def set_wallet(self, wallet_address: str) -> Dict: return await self._request("PUT", "/accounts/wallet", json={"wallet_address": wallet_address})
    async def list_games(self, status: str = "waiting") -> List[Dict]:
        try:
            res = await self._request("GET", f"/games?status={status}")
            return res if isinstance(res, list) else []
        except: return []
    async def get_game(self, game_id: str) -> Dict: return await self._request("GET", f"/games/{game_id}")
    async def register_agent(self, game_id: str, agent_name: str) -> Dict: return await self._request("POST", f"/games/{game_id}/agents/register", json={"name": agent_name})
    async def get_state(self, game_id: str, agent_id: str) -> Dict: return await self._request("GET", f"/games/{game_id}/agents/{agent_id}/state")
    async def take_action(self, game_id: str, agent_id: str, action: Dict, thought: Dict = None) -> Dict:
        payload = {"action": action}
        if thought: payload["thought"] = thought
        return await self._request("POST", f"/games/{game_id}/agents/{agent_id}/action", json=payload)

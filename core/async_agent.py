import asyncio
import logging
import time
import random
from typing import Optional

from core.async_api_client import AsyncAPIClient, APIError
from core.analyzer import StateAnalyzer
from core.strategy import StrategyEngine
from learning.memory import GameMemory
from learning.ml_engine import LearningEngine
from core.monitor import Monitor

# Constants
BASE_URL = "https://cdn.moltyroyale.com/api"
POLL_INTERVAL_WAITING = 5
POLL_INTERVAL_DEAD = 15
TURN_INTERVAL = 60  # Real time seconds per turn

logger = logging.getLogger("MoltyBot.Agent")

class AsyncAgent:
    def __init__(self, name: str, api_key: str, wallet_address: str, proxy: str = None, index: int = 0, data_dir: str = "data"):
        self.name = name
        self.wallet_address = wallet_address
        self.index = index
        self.api = AsyncAPIClient(BASE_URL, api_key, proxy=proxy)
        
        # Initialize components
        self.memory = GameMemory(data_dir=f"{data_dir}/{name}")
        self.learning = LearningEngine(self.memory)
        self.analyzer = StateAnalyzer() 
        self.strategy = StrategyEngine(self.analyzer, self.memory, self.learning)
        
        self.game_id: Optional[str] = None
        self.agent_id: Optional[str] = None
        self.running = True
        
        # Economy State
        self.smoltz_balance = 0
        self.moltz_balance = 0

        Monitor.register(self.name, self.wallet_address)

    async def log(self, msg: str):
        Monitor.log(self.name, msg)
        logger.info(f"[{self.name}] {msg}")

    async def rotate_proxy(self):
        """Request a new proxy and refresh the persistent session."""
        from core.proxy_manager import ProxyManager
        new_p = ProxyManager.get_replacement(self.api.proxy)
        if new_p:
            await self.log(f"Proxy failed! Refreshing session with new IP...")
            await self.api.close()
            self.api.proxy = new_p
            p_info = new_p.split('@')[-1] if '@' in new_p else new_p.split('/')[-1]
            Monitor.update(self.name, proxy=p_info, proxy_status="Session Reset")
            return True
        return False

    async def update_economy_stats(self, account: dict):
        """Parse and update economic stats."""
        self.smoltz_balance = account.get("balance", 0)
        self.moltz_balance = account.get("moltz", account.get("walletBalance", 0))
        wins = account.get("totalWins", 0)
        games = account.get("totalGames", 0)
        mode = "Hunting (Paid)" if self.smoltz_balance >= 100 else "Farming (Free)"
        
        Monitor.update(self.name, 
            smoltz_balance=self.smoltz_balance,
            moltz_balance=self.moltz_balance,
            mode=mode,
            win_ratio=f"{wins}/{games}"
        )

    async def start(self):
        """Main Agent Loop with Persistent Session"""
        await self.log("Starting agent...")
        fail_count = 0
        
        while self.running:
            try:
                account = await self.api.get_account()
                if not account or not isinstance(account, dict):
                    raise Exception("Failed to get account data")

                fail_count = 0 
                self.name = account.get("name", self.name)
                Monitor.update(self.name, proxy_status="Success ✓")
                await self.update_economy_stats(account)
                
                server_wallet = account.get("walletAddress") or account.get("wallet")
                if not server_wallet and self.wallet_address:
                    await self.api.set_wallet(self.wallet_address)
                
                current_games = account.get("currentGames") or []
                for game in current_games:
                    if game.get("gameStatus") in ("running", "waiting"):
                        if game.get("isAlive", True):
                            self.game_id = game.get("gameId")
                            self.agent_id = game.get("agentId")
                            await self.log(f"Resuming game {self.game_id[:8]}...")
                            Monitor.update(self.name, status="Resuming", game_id=self.game_id)
                            await self.play_game()
                            break
                else:
                    if not await self.find_and_join_game():
                        await asyncio.sleep(10)
                        continue
                    await self.play_game()

            except Exception as e:
                fail_count += 1
                msg = str(e)
                if "429" in msg: msg = "Rate Limited (429)"
                await self.log(f"Connection Issue ({fail_count}/3): {msg}")
                
                if fail_count >= 3:
                    if await self.rotate_proxy():
                        fail_count = 0
                    await asyncio.sleep(15)
                else:
                    await asyncio.sleep(5)
                continue

    async def find_and_join_game(self) -> bool:
        """Sequential hunting using Global Throttle (max 1 search per 2s)."""
        Monitor.update(self.name, status="Waiting Queue", game_id="-", region="-", hp=100, ep=10)
        while not Monitor.can_search():
            await asyncio.sleep(0.5)

        Monitor.update(self.name, status="Searching")
        try:
            try:
                acc = await self.api.get_account()
                await self.update_economy_stats(acc)
            except: pass

            target_type = "paid" if self.smoltz_balance >= 100 else "free"
            rooms = await self.api.list_games(status="waiting")
            Monitor.release_search()

            if rooms is None: return False
            candidate_games = []
            
            if target_type == "paid":
                candidate_games = [g for g in rooms if g.get("entryType") == "paid" or (g.get("entryFee", 0) > 0 and g.get("currency") == "smoltz")]
                if not candidate_games: target_type = "free"
            
            if target_type == "free":
                candidate_games = [g for g in rooms if g.get("entryType") == "free" or g.get("entryFee", 0) == 0]

            if not candidate_games: return False

            target_game = candidate_games[0]
            gid = target_game["id"]
            await self.log(f"FOUND {target_type.upper()} ROOM: {target_game.get('name')}! Joining...")
            
            try:
                agent = await self.api.register_agent(gid, self.name)
                self.game_id = gid
                self.agent_id = agent["id"]
                await self.log("Joined successfully!")
                return True
            except APIError as e:
                if e.code == "INSUFFICIENT_BALANCE": self.smoltz_balance = 0
                return False

        except Exception as e:
            Monitor.release_search()
            await self.log(f"Hunting Error: {e}")
            return False

    async def play_game(self):
        """Main Gameplay Loop with Health Checks"""
        Monitor.update(self.name, status="Waiting Start", game_id=self.game_id)
        turn_count = 0
        last_action_time = 0
        last_health_check = time.time()

        while True:
            try:
                now = time.time()
                if now - last_health_check > 900:
                    last_health_check = now
                    try:
                        acc = await self.api.get_account()
                        active = acc.get("currentGames") or []
                        if not any(g.get("gameId") == self.game_id for g in active):
                            await self.log("Health Check: Game gone. Exiting.")
                            return
                    except: pass
                
                if now - last_action_time < TURN_INTERVAL:
                    await asyncio.sleep(1)
                    continue

                try:
                    state_data = await self.api.get_state(self.game_id, self.agent_id)
                except APIError as e:
                    if e.code in ("GAME_NOT_FOUND", "AGENT_NOT_FOUND"):
                        await self.log("Game ended unexpectedly. Returning to hunt.")
                        self.game_id = None
                        return
                    raise e

                if not state_data or not isinstance(state_data, dict):
                    await asyncio.sleep(5)
                    continue
                
                self_data = state_data.get("self")
                if not self_data:
                    await asyncio.sleep(5)
                    continue

                is_alive = self_data.get("isAlive", True)
                game_status = state_data.get("gameStatus")
                res_obj = state_data.get("result") or {}
                reg_obj = state_data.get("currentRegion") or {}

                Monitor.update(self.name, 
                    hp=self_data.get("hp", 0), ep=self_data.get("ep", 0),
                    region=reg_obj.get("name", "Unknown"), game_id=self.game_id,
                    status="Playing" if is_alive else "Eliminated"
                )

                if not is_alive or game_status == "finished":
                    await self.log(f"Session Finished. Rank: {res_obj.get('finalRank', '?')}")
                    try:
                        acc_info = await self.api.get_account()
                        if acc_info: await self.update_economy_stats(acc_info)
                    except: pass
                    return

                intel = self.analyzer.parse(state_data)
                main_action, reasoning, free_actions = self.strategy.decide(intel)

                for action in free_actions: await self.api.take_action(self.game_id, self.agent_id, action)
                
                if main_action:
                    thought = {"reasoning": reasoning, "plannedAction": main_action["type"]}
                    res = await self.api.take_action(self.game_id, self.agent_id, main_action, thought)
                    if res.get("success"):
                        last_action_time = time.time()
                        turn_count += 1
                        await self.log(f"T{turn_count} {main_action['type'].upper()}")
                        Monitor.update(self.name, last_action=f"{main_action['type']} (T{turn_count})")
                else:
                    await asyncio.sleep(5)

            except Exception as e:
                await self.log(f"Turn Error: {str(e)}")
                await asyncio.sleep(10)

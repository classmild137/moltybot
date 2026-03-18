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

        Monitor.register(self.name, self.wallet_address)

    async def log(self, msg: str):
        Monitor.log(self.name, msg)
        logger.info(f"[{self.name}] {msg}")
async def rotate_proxy(self):
    """Request a new proxy from the manager if the current one fails."""
    from core.proxy_manager import ProxyManager
    new_p = ProxyManager.get_replacement(self.api.proxy)
    if new_p:
        await self.log(f"Proxy failed! Swapping to new IP...")
        self.api.proxy = new_p
        # Clean display info
        p_info = new_p.split('@')[-1] if '@' in new_p else new_p.split('/')[-1]
        Monitor.update(self.name, proxy=p_info, proxy_status="Reconnected")
        return True
    return False


    async def start(self):
        """Main Agent Loop with Error Tolerance and Auto-Resume"""
        await self.log("Starting agent...")
        fail_count = 0
        
        while self.running:
            try:
                # 1. Verify Account & Resume Game
                account = await self.api.get_account()
                if not account or not isinstance(account, dict):
                    raise Exception("Failed to get account data")

                fail_count = 0 # Reset fails on success
                self.name = account.get("name", self.name)
                Monitor.update(self.name, proxy_status="Success ✓")
                
                # Stats Update
                balance = account.get("balance", 0)
                wins = account.get("totalWins", 0)
                games = account.get("totalGames", 0)
                Monitor.update(self.name, balance=balance, win_ratio=f"{wins}/{games}")
                
                # Wallet check
                server_wallet = account.get("walletAddress") or account.get("wallet")
                if not server_wallet and self.wallet_address:
                    await self.api.set_wallet(self.wallet_address)
                
                # Auto-Resume Logic
                current_games = account.get("currentGames") or []
                for game in current_games:
                    if game.get("gameStatus") in ("running", "waiting"):
                        if game.get("isAlive", True):
                            self.game_id = game.get("gameId")
                            self.agent_id = game.get("agentId")
                            await self.log(f"Resuming game {self.game_id[:8]}...")
                            Monitor.update(self.name, status="Resuming", game_id=self.game_id)
                            await self.play_game()
                            # After play_game returns, continue the outer loop to find next game
                            break
                else:
                    # No game to resume, go to hunting
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
        """Dynamic sequential hunting using Global Throttle (max 1 search per 2s)."""
        Monitor.update(self.name, status="Waiting Queue", game_id="-", region="-", hp=100, ep=10)
        
        while not Monitor.can_search():
            await asyncio.sleep(0.5)

        Monitor.update(self.name, status="Searching")
        try:
            rooms = await self.api.list_games(status="waiting")
            Monitor.release_search()

            if rooms is None: return False
            
            total_rooms = len(rooms) if isinstance(rooms, list) else 0
            free_games = [g for g in rooms if g.get("entryType") == "free"] if isinstance(rooms, list) else []
            
            if not free_games:
                if not hasattr(self, "_scan_count"): self._scan_count = 0
                self._scan_count += 1
                if self._scan_count % 3 == 1:
                    await self.log(f"Scan: {total_rooms} rooms found, 0 FREE. Retrying...")
                return False

            target_game = free_games[0]
            gid = target_game["id"]
            await self.log(f"FOUND ROOM: {target_game.get('name')}! Joining...")
            
            try:
                agent = await self.api.register_agent(gid, self.name)
                self.game_id = gid
                self.agent_id = agent["id"]
                await self.log("Joined successfully!")
                return True
            except APIError as e:
                if e.code == "TOO_MANY_AGENTS_PER_IP":
                    await self.log("IP Limit (5/room) hit. Trying next...")
                elif e.code == "ACCOUNT_ALREADY_IN_GAME":
                    await self.log("Syncing existing game...")
                    return True
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
                
                # Health Check every 15m
                if now - last_health_check > 900:
                    last_health_check = now
                    try:
                        acc = await self.api.get_account()
                        active = acc.get("currentGames") or []
                        if not any(g.get("gameId") == self.game_id for g in active):
                            await self.log("Health Check: Game gone. Exiting.")
                            return
                    except: pass
                
                # Turn pacing
                if now - last_action_time < TURN_INTERVAL:
                    await asyncio.sleep(1)
                    continue

                # Get State
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
                    
                    # Final Stats Update
                    try:
                        acc_info = await self.api.get_account()
                        if acc_info:
                            Monitor.update(self.name, 
                                balance=acc_info.get("balance", 0),
                                win_ratio=f"{acc_info.get('totalWins', 0)}/{acc_info.get('totalGames', 0)}"
                            )
                    except: pass
                    
                    self.memory.end_game(
                        is_winner=res_obj.get("isWinner", False),
                        final_rank=res_obj.get("finalRank", 99),
                        final_hp=self_data.get("hp", 0),
                        moltz_earned=res_obj.get("rewards", 0)
                    )
                    return

                # Strategy
                intel = self.analyzer.parse(state_data)
                main_action, reasoning, free_actions = self.strategy.decide(intel)

                for action in free_actions:
                    await self.api.take_action(self.game_id, self.agent_id, action)
                
                if main_action:
                    thought = {"reasoning": reasoning, "plannedAction": main_action["type"]}
                    res = await self.api.take_action(self.game_id, self.agent_id, main_action, thought)
                    if res.get("success"):
                        last_action_time = time.time()
                        turn_count += 1
                        await self.log(f"T{turn_count} {main_action['type'].upper()}")
                        Monitor.update(self.name, last_action=f"{main_action['type']} (T{turn_count})")
                        self.memory.record_turn(turn_count, intel, main_action, res)
                    elif res.get("error", {}).get("code") == "ALREADY_ACTED":
                         last_action_time = time.time()
                else:
                    await asyncio.sleep(5)

            except Exception as e:
                await self.log(f"Turn Error: {str(e)}")
                await asyncio.sleep(10)

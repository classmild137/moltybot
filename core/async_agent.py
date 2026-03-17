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

# Constants (Hardcoded for simplicity/robustness as per prompt reqs)
BASE_URL = "https://cdn.moltyroyale.com/api"
POLL_INTERVAL_WAITING = 5
POLL_INTERVAL_DEAD = 15
TURN_INTERVAL = 60  # Real time seconds per turn

logger = logging.getLogger("MoltyBot.Agent")

class AsyncAgent:
    def __init__(self, name: str, api_key: str, wallet_address: str, data_dir: str = "data"):
        self.name = name
        self.wallet_address = wallet_address
        self.api = AsyncAPIClient(BASE_URL, api_key)
        
        # Initialize components (Reusing existing core logic)
        self.memory = GameMemory(data_dir=f"{data_dir}/{name}")
        self.learning = LearningEngine(self.memory)
        self.analyzer = StateAnalyzer() # Default params
        self.strategy = StrategyEngine(self.analyzer, self.memory, self.learning)
        
        self.game_id: Optional[str] = None
        self.agent_id: Optional[str] = None
        self.running = True

        Monitor.register(self.name, self.wallet_address)

    async def log(self, msg: str):
        Monitor.log(self.name, msg)
        logger.info(f"[{self.name}] {msg}")

    async def start(self):
        """Main Agent Loop"""
        await self.log("Starting agent...")
        
        # 1. Ensure Account & Wallet
        try:
            account = await self.api.get_account()
            if not account or not isinstance(account, dict):
                await self.log(f"Failed to get account info: Response was {type(account)}")
                return

            self.name = account.get("name", self.name)
            await self.log(f"Account Verified: {self.name}")
            
            # Update Balance & Win Ratio on Monitor
            balance = account.get("balance", 0)
            wins = account.get("totalWins", 0)
            games = account.get("totalGames", 0)
            Monitor.update(self.name, balance=balance, win_ratio=f"{wins}/{games}")
            
            server_wallet = account.get("walletAddress") or account.get("wallet")
            if not server_wallet and self.wallet_address:
                await self.log(f"Registering wallet: {self.wallet_address}")
                await self.api.set_wallet(self.wallet_address)
            
            # Check existing games
            current_games = account.get("currentGames") or []
            if not isinstance(current_games, list): current_games = []
            
            for game in current_games:
                if game.get("gameStatus") in ("running", "waiting"):
                    if game.get("isAlive", True):
                        self.game_id = game.get("gameId")
                        self.agent_id = game.get("agentId")
                        await self.log(f"Resuming game {self.game_id[:8]}...")
                        Monitor.update(self.name, status="Resuming", game_id=self.game_id)
                        await self.play_game()
                        return
        except APIError as e:
            await self.log(f"Startup API Error: {e.code} - {str(e)}")
            return
        except Exception as e:
            await self.log(f"Startup Crash: {str(e)}")
            return

        # 2. Loop: Find Game -> Play -> Repeat
        while self.running:
            try:
                # Reset State
                self.game_id = None
                self.agent_id = None
                Monitor.update(self.name, status="Idle", game_id="-", region="-", hp=100, ep=10)

                # Find Game
                if not await self.find_and_join_game():
                    await asyncio.sleep(10)
                    continue

                # Play Game
                await self.play_game()
                
                # Brief pause before next game
                await asyncio.sleep(5)

            except Exception as e:
                await self.log(f"Critical Loop Error: {e}")
                await asyncio.sleep(30)

    async def find_and_join_game(self) -> bool:
        """Finds a free game using Shared Cache to save API calls."""
        Monitor.update(self.name, status="Searching")
        try:
            # 1. Check Shared Cache First
            rooms = Monitor.get_rooms()
            if rooms is None:
                # Cache expired, only ONE agent will fetch from API
                rooms = await self.api.list_games(status="waiting")
                Monitor.update_room_cache(rooms)
            
            free_games = [g for g in rooms if g.get("entryType") == "free"]

            if not free_games:
                # Tambahkan jitter di sini agar 55 bot tidak mencari di detik yang sama
                await asyncio.sleep(random.randint(5, 15))
                return False

            # 2. Try to join
            target_game = free_games[0]
            gid = target_game["id"]
            
            # Staggered join attempt (1-5s) to avoid race condition
            await asyncio.sleep(random.uniform(0.5, 3.0))
            
            await self.log(f"Joining game {gid[:8]}...")
            try:
                agent = await self.api.register_agent(gid, self.name)
                self.game_id = gid
                self.agent_id = agent["id"]
                await self.log("Joined successfully!")
                return True
            except APIError as e:
                # Limit IP Handling (5 agents per room/IP)
                if e.code == "TOO_MANY_AGENTS_PER_IP":
                    await self.log("IP Limit (5/room) reached. Waiting for next room...")
                    await asyncio.sleep(20)
                return False

        except Exception as e:
            await self.log(f"Hunting Error: {e}")
            return False

    async def play_game(self):
        """Gameplay Loop with Jitter to spread API load."""
        Monitor.update(self.name, status="Waiting Start", game_id=self.game_id)
        
        # Jitter start delay for each bot (0-30s) so they don't sync up
        await asyncio.sleep(random.randint(0, 30))
        
        # ... (rest of waiting start) ...
        
        # Wait for start
        while True:
            try:
                state = await self.api.get_game(self.game_id)
                if state["status"] == "running":
                    break
                if state["status"] == "finished":
                    await self.log("Game finished before start.")
                    return
                await asyncio.sleep(POLL_INTERVAL_WAITING)
            except APIError:
                await asyncio.sleep(POLL_INTERVAL_WAITING)

        await self.log("Game Started!")
        Monitor.update(self.name, status="Playing")
        
        self.memory.start_game(self.game_id, self.agent_id, self.name)
        self.strategy.reset_for_new_game()

        turn_count = 0
        last_action_time = 0

        while True:
            try:
                # Rate limit / Turn wait
                now = time.time()
                time_since_last = now - last_action_time
                if time_since_last < TURN_INTERVAL:
                    await asyncio.sleep(1) 
                    continue

                # Get State
                state_data = await self.api.get_state(self.game_id, self.agent_id)
                if not state_data or not isinstance(state_data, dict):
                    await asyncio.sleep(5)
                    continue
                
                # Check Self Data
                self_data = state_data.get("self")
                if not self_data or not isinstance(self_data, dict):
                    await asyncio.sleep(5)
                    continue

                is_alive = self_data.get("isAlive", True)
                game_status = state_data.get("gameStatus")
                
                # Robust data for Monitor
                res_obj = state_data.get("result") or {}
                if not isinstance(res_obj, dict): res_obj = {}
                
                reg_obj = state_data.get("currentRegion") or {}
                if not isinstance(reg_obj, dict): reg_obj = {}

                # Update Monitor
                Monitor.update(self.name, 
                    hp=self_data.get("hp", 0),
                    ep=self_data.get("ep", 0),
                    region=reg_obj.get("name", "Unknown"),
                    game_id=self.game_id
                )

                if not is_alive or game_status == "finished":
                    await self.log("Game Over / Died")
                    rewards = res_obj.get("rewards", 0)
                    Monitor.update(self.name, status="Dead/Finished", rewards_today=rewards)
                    self.memory.end_game(
                        is_winner=res_obj.get("isWinner", False),
                        final_rank=res_obj.get("finalRank", 99),
                        final_hp=self_data.get("hp", 0),
                        moltz_earned=rewards
                    )
                    return

                # Analyze & Decide
                intel = self.analyzer.parse(state_data)
                main_action, reasoning, free_actions = self.strategy.decide(intel)

                # Execute Free Actions
                for action in free_actions:
                    await self.api.take_action(self.game_id, self.agent_id, action)
                
                # Execute Main Action
                if main_action:
                    thought = {"reasoning": reasoning, "plannedAction": main_action["type"]}
                    res = await self.api.take_action(self.game_id, self.agent_id, main_action, thought)
                    
                    if res.get("success"):
                        last_action_time = time.time()
                        turn_count += 1
                        await self.log(f"T{turn_count} {main_action['type'].upper()}: {reasoning}")
                        Monitor.update(self.name, last_action=f"{main_action['type']} (T{turn_count})")
                        self.memory.record_turn(turn_count, intel, main_action, res)
                    
                    elif res.get("error", {}).get("code") == "ALREADY_ACTED":
                         # We acted too early? Sync issue? Just wait a bit.
                         last_action_time = time.time() # Reset timer effectively to wait another cycle
                    
                else:
                    # Should not happen with current strategy, but fallback
                    await asyncio.sleep(5)

            except Exception as e:
                await self.log(f"Turn Error: {e}")
                await asyncio.sleep(10)

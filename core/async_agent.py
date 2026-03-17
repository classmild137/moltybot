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
            Monitor.update(self.name, proxy_status="Success ✓")
            
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
        """Dynamic sequential hunting using Global Throttle (max 1 search per 2s)."""
        # FORCE RESET agar tidak terjebak status "Dead (Watching)" di Dashboard
        Monitor.update(self.name, status="Waiting Queue", game_id="-", region="-", hp=100, ep=10)
        
        # Ngantri sampai giliran Global Throttle mengizinkan (2 detik sekali)
        while not Monitor.can_search():
            await asyncio.sleep(0.5)

        Monitor.update(self.name, status="Searching")
        try:
            # Panggil API dengan IP masing-masing (Proxy/Direct)
            rooms = await self.api.list_games(status="waiting")
            # Segera lepaskan kunci agar bot berikutnya bisa ngantri
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

            # Ambil room pertama yang tersedia
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
                    # Ambil info game yang sedang berjalan agar tidak bengong
                    acc = await self.api.get_account()
                    current_games = acc.get("currentGames") or []
                    if current_games:
                        current = current_games[0]
                        self.game_id = current.get("gameId")
                        self.agent_id = current.get("agentId")
                        await self.log(f"Already in game {self.game_id[:8]}. Syncing...")
                        return True
                    else:
                        await self.log("Server says in game, but no active games found. Retrying hunt.")
                return False

        except Exception as e:
            Monitor.release_search() # Pastikan kunci dilepas jika error
            await self.log(f"Hunting Error: {e}")
            await asyncio.sleep(10)
            return False

    async def play_game(self):
        """Main Gameplay Loop with Robust Data Handling"""
        Monitor.update(self.name, status="Waiting Start", game_id=self.game_id)
        
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
        watch_start_time = 0
        last_health_check = time.time()

        while True:
            try:
                now = time.time()
                
                # --- HEALTH CHECK (STUCK GUARD) setiap 15 menit ---
                if now - last_health_check > 900: # 15 menit
                    last_health_check = now
                    try:
                        acc = await self.api.get_account()
                        active_games = acc.get("currentGames") or []
                        # Jika server bilang tidak ada game aktif, tapi bot merasa sedang bermain
                        still_in_game = any(g.get("gameId") == self.game_id for g in active_games)
                        if not still_in_game:
                            await self.log("Health Check: Game not found in account info. Forcing hunt.")
                            self.game_id = None
                            return
                    except: pass # Abaikan jika API error sejenak
                
                # Rate limit / Turn wait
                time_since_last = now - last_action_time
                if time_since_last < TURN_INTERVAL:
                    await asyncio.sleep(1) 
                    continue

                # Get State
                try:
                    state_data = await self.api.get_state(self.game_id, self.agent_id)
                except APIError as e:
                    if e.code in ("GAME_NOT_FOUND", "AGENT_NOT_FOUND"):
                        await self.log(f"Game ended/gone ({e.code}). Resetting for new hunt.")
                        self.game_id = None # Bersihkan ID lama
                        self.agent_id = None
                        return 
                    raise e

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
                    # JIKA MATI TAPI GAME MASIH JALAN: Tunggu sampai SELESAI
                    if not is_alive and game_status != "finished":
                        if watch_start_time == 0: watch_start_time = time.time()
                        
                        # Timeout 15 menit agar tidak stuck selamanya
                        if time.time() - watch_start_time > 900:
                            await self.log("Watch timeout (15m). Forcing new hunt.")
                            self.game_id = None
                            return

                        Monitor.update(self.name, status="Dead (Watching)", hp=0)
                        if turn_count % 5 == 0: # Log setiap 5 turn agar tidak spam
                            await self.log(f"Eliminated. Waiting for game {self.game_id[:8]} to finish...")
                        await asyncio.sleep(POLL_INTERVAL_DEAD)
                        continue # Tetap di dalam play_game loop sampai status 'finished'

                    # JIKA GAME BENAR-BENAR SELESAI: Keluar
                    await self.log(f"Game Over. Rank: {res_obj.get('finalRank', '?')}, Rewards: {rewards}")
                    
                    # Update Win Ratio on Game End
                    try:
                        acc_info = await self.api.get_account()
                        if acc_info:
                            Monitor.update(self.name, 
                                balance=acc_info.get("balance", 0),
                                win_ratio=f"{acc_info.get('totalWins', 0)}/{acc_info.get('totalGames', 0)}"
                            )
                    except: pass

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
                         last_action_time = time.time()
                    
                else:
                    await asyncio.sleep(5)

            except Exception as e:
                await self.log(f"Turn Error: {e}")
                await asyncio.sleep(10)

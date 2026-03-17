from typing import Dict, Any
from datetime import datetime

class Monitor:
    """
    Centralized, thread-safe (async-safe) store for all agents.
    Used by the dashboard to render real-time status.
    """
    _agents: Dict[str, Dict[str, Any]] = {}
    
    @classmethod
    def register(cls, agent_name: str, wallet: str):
        """Register a new agent."""
        cls._agents[agent_name] = {
            "name": agent_name,
            "wallet": f"{wallet[:6]}...{wallet[-4:]}" if wallet else "N/A",
            "status": "Initializing",
            "game_id": "-",
            "region": "-",
            "hp": 100,
            "ep": 10,
            "last_action": "-",
            "last_update": datetime.now().isoformat(),
            "rewards_today": 0,
            "total_wins": 0,
            "logs": []
        }

    @classmethod
    def update(cls, agent_name: str, **kwargs):
        """Update specific fields for an agent."""
        if agent_name in cls._agents:
            cls._agents[agent_name].update(kwargs)
            cls._agents[agent_name]["last_update"] = datetime.now().isoformat()

    @classmethod
    def log(cls, agent_name: str, message: str):
        """Add a log entry for an agent."""
        if agent_name in cls._agents:
            timestamp = datetime.now().strftime("%H:%M:%S")
            entry = f"[{timestamp}] {message}"
            # Keep only last 10 logs
            cls._agents[agent_name]["logs"] = ([entry] + cls._agents[agent_name]["logs"])[:10]

    @classmethod
    def get_all(cls):
        """Return all agent data."""
        return cls._agents

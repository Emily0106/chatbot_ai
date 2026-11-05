"""Session storage with async safety and TTL based on activity."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Protocol

from .case_memory import CaseMemory


class ISessionStore(Protocol):
    """Interface for session storage (allows Redis swap later)."""

    async def touch(self, session_id: str) -> None:
        """Mark session as active."""
        ...

    async def get_cases(self, session_id: str) -> List[CaseMemory]:
        """Get all cases for session."""
        ...

    async def add_case(self, session_id: str, case: CaseMemory) -> None:
        """Add new case to session."""
        ...

    async def cleanup(self) -> None:
        """Remove expired sessions."""
        ...


@dataclass
class InMemorySessionStore:
    """
    In-memory session store with async safety.
    
    WARNING: Single-worker only. Use Redis for multi-worker deployment.
    """

    ttl: timedelta = field(default_factory=lambda: timedelta(minutes=60))

    def __post_init__(self):
        self._sessions: Dict[str, List[CaseMemory]] = {}
        self._last_seen: Dict[str, datetime] = {}
        self._lock = asyncio.Lock()  # Async concurrency safety

    async def touch(self, session_id: str) -> None:
        """Update last activity time."""
        async with self._lock:
            self._last_seen[session_id] = datetime.utcnow()

    async def get_cases(self, session_id: str) -> List[CaseMemory]:
        """Get cases for session, marking as active."""
        await self.touch(session_id)
        async with self._lock:
            return self._sessions.get(session_id, [])

    async def add_case(self, session_id: str, case: CaseMemory) -> None:
        """Add case and mark session active."""
        await self.touch(session_id)
        async with self._lock:
            self._sessions.setdefault(session_id, []).append(case)

    async def cleanup(self) -> None:
        """Remove sessions inactive for > TTL."""
        async with self._lock:
            now = datetime.utcnow()
            expired = [
                sid
                for sid, last_seen in self._last_seen.items()
                if now - last_seen > self.ttl
            ]
            for sid in expired:
                self._sessions.pop(sid, None)
                self._last_seen.pop(sid, None)


# Singleton with swap capability
_store: ISessionStore = InMemorySessionStore()


def get_session_store() -> ISessionStore:
    return _store


def set_session_store(store: ISessionStore):
    """Replace store (e.g., with RedisSessionStore in production)."""
    global _store
    _store = store

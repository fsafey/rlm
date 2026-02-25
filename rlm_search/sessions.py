"""rlm_search/sessions.py"""

from __future__ import annotations

import dataclasses
import threading
import time
import uuid
from typing import Any

from rlm_search.bus import EventBus


@dataclasses.dataclass
class SessionState:
    """Persistent session for multi-turn search conversations."""

    session_id: str
    rlm: Any  # RLM instance
    bus: EventBus
    lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)
    search_count: int = 0
    last_active: float = dataclasses.field(default_factory=time.monotonic)
    active_search_id: str | None = None


class SessionManager:
    """Manages persistent search sessions.

    Replaces the ad-hoc session dict + follow-up hack in api.py.
    Encapsulates the 4-mutation logger swap into prepare_follow_up().
    """

    def __init__(self, session_timeout: float = 1800.0) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()
        self.session_timeout = session_timeout

    def create_session(self, rlm: Any, bus: EventBus, session_id: str | None = None) -> str:
        sid = session_id or str(uuid.uuid4())[:12]
        session = SessionState(session_id=sid, rlm=rlm, bus=bus)
        with self._lock:
            self._sessions[sid] = session
        return sid

    def get(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    def is_busy(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        return session.active_search_id is not None

    def delete(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            session.rlm.close()

    def prepare_follow_up(
        self,
        session_id: str,
        new_bus: EventBus,
        search_id: str,
    ) -> tuple[Any, SessionState]:
        """Prepare a session for a follow-up search.

        Replaces the 4-mutation hack in api.py:353-368.
        Returns (rlm, session) with session locked and marked active.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found")
        if session.active_search_id is not None:
            raise ValueError(f"Session {session_id} is busy with {session.active_search_id}")

        with session.lock:
            session.search_count += 1
            session.last_active = time.monotonic()
            session.active_search_id = search_id
            session.bus = new_bus

        return session.rlm, session

    def cleanup_expired(self) -> list[str]:
        """Remove sessions idle longer than timeout. Returns removed IDs."""
        now = time.monotonic()
        to_remove: list[str] = []
        with self._lock:
            for sid, session in self._sessions.items():
                if session.active_search_id is not None:
                    continue
                if now - session.last_active > self.session_timeout:
                    to_remove.append(sid)
            for sid in to_remove:
                session = self._sessions.pop(sid)
                session.rlm.close()
        return to_remove

    def clear_active(self, session_id: str) -> None:
        """Mark a session's active search as complete."""
        session = self._sessions.get(session_id)
        if session is not None:
            session.active_search_id = None

"""tests/test_session_manager.py"""
import threading
import time
from unittest.mock import MagicMock, patch

from rlm_search.sessions import SessionManager, SessionState


class TestSessionManagerLifecycle:
    def test_create_session(self):
        mgr = SessionManager()
        sid = mgr.create_session(rlm=MagicMock(), bus=MagicMock())
        assert sid is not None
        assert mgr.get(sid) is not None

    def test_get_nonexistent_returns_none(self):
        mgr = SessionManager()
        assert mgr.get("nonexistent") is None

    def test_delete_session(self):
        mgr = SessionManager()
        sid = mgr.create_session(rlm=MagicMock(), bus=MagicMock())
        mgr.delete(sid)
        assert mgr.get(sid) is None

    def test_delete_calls_rlm_close(self):
        mgr = SessionManager()
        mock_rlm = MagicMock()
        sid = mgr.create_session(rlm=mock_rlm, bus=MagicMock())
        mgr.delete(sid)
        mock_rlm.close.assert_called_once()


class TestSessionManagerBusy:
    def test_active_search_prevents_new_search(self):
        mgr = SessionManager()
        sid = mgr.create_session(rlm=MagicMock(), bus=MagicMock())
        session = mgr.get(sid)
        session.active_search_id = "search_1"
        assert mgr.is_busy(sid)

    def test_no_active_search_is_not_busy(self):
        mgr = SessionManager()
        sid = mgr.create_session(rlm=MagicMock(), bus=MagicMock())
        assert not mgr.is_busy(sid)


class TestSessionManagerCleanup:
    def test_cleanup_expired_sessions(self):
        mgr = SessionManager(session_timeout=0.1)  # 100ms timeout
        mock_rlm = MagicMock()
        sid = mgr.create_session(rlm=mock_rlm, bus=MagicMock())
        time.sleep(0.2)
        removed = mgr.cleanup_expired()
        assert sid in removed
        assert mgr.get(sid) is None
        mock_rlm.close.assert_called_once()

    def test_cleanup_skips_active_sessions(self):
        mgr = SessionManager(session_timeout=0.1)
        sid = mgr.create_session(rlm=MagicMock(), bus=MagicMock())
        mgr.get(sid).active_search_id = "active"
        time.sleep(0.2)
        removed = mgr.cleanup_expired()
        assert sid not in removed


class TestSessionManagerPrepareFollowUp:
    def test_prepare_follow_up_returns_rlm(self):
        mgr = SessionManager()
        mock_rlm = MagicMock()
        sid = mgr.create_session(rlm=mock_rlm, bus=MagicMock())
        from rlm_search.bus import EventBus
        new_bus = EventBus()
        rlm, session = mgr.prepare_follow_up(sid, new_bus, search_id="s2")
        assert rlm is mock_rlm
        assert session.active_search_id == "s2"
        assert session.search_count == 1

    def test_prepare_follow_up_raises_if_busy(self):
        mgr = SessionManager()
        sid = mgr.create_session(rlm=MagicMock(), bus=MagicMock())
        mgr.get(sid).active_search_id = "s1"
        import pytest
        with pytest.raises(ValueError, match="busy"):
            mgr.prepare_follow_up(sid, MagicMock(), search_id="s2")

    def test_prepare_follow_up_raises_if_not_found(self):
        mgr = SessionManager()
        import pytest
        with pytest.raises(KeyError):
            mgr.prepare_follow_up("nonexistent", MagicMock(), search_id="s2")

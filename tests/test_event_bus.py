"""tests/test_event_bus.py"""

import asyncio
import threading

import pytest

from rlm_search.bus import EventBus, SearchCancelled


class TestEventBusEmitAndReplay:
    def test_emit_single_event(self):
        bus = EventBus()
        bus.emit("test_event", {"key": "value"})
        events = bus.replay()
        assert len(events) == 1
        assert events[0]["type"] == "test_event"
        assert events[0]["data"]["key"] == "value"
        assert "timestamp" in events[0]

    def test_replay_returns_all_events_without_clearing(self):
        bus = EventBus()
        bus.emit("a", {"n": 1})
        bus.emit("b", {"n": 2})
        first = bus.replay()
        assert len(first) == 2
        # replay again — still returns everything
        bus.emit("c", {"n": 3})
        second = bus.replay()
        assert len(second) == 3
        assert [e["type"] for e in second] == ["a", "b", "c"]

    def test_thread_safety(self):
        bus = EventBus()
        errors: list[Exception] = []

        def writer(prefix: str, count: int) -> None:
            try:
                for i in range(count):
                    bus.emit(f"{prefix}_{i}", {"i": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(f"t{t}", 100)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        all_events = bus.replay()
        assert len(all_events) == 400


class TestEventBusTerminalEvents:
    def test_is_terminal(self):
        bus = EventBus()
        assert not bus.is_done
        bus.emit("done", {"answer": "test"})
        assert bus.is_done

    def test_error_is_terminal(self):
        bus = EventBus()
        bus.emit("error", {"message": "failed"})
        assert bus.is_done

    def test_cancelled_is_terminal(self):
        bus = EventBus()
        bus.emit("cancelled", {})
        assert bus.is_done


class TestEventBusCancellation:
    def test_cancel_sets_flag(self):
        bus = EventBus()
        assert not bus.cancelled
        bus.cancel()
        assert bus.cancelled

    def test_raise_if_cancelled(self):
        bus = EventBus()
        bus.cancel()
        with pytest.raises(SearchCancelled):
            bus.raise_if_cancelled()


class TestEventBusAsync:
    def test_bind_and_replay_returns_history(self):
        bus = EventBus()
        bus.emit("a", {"n": 1})
        bus.emit("b", {"n": 2})

        loop = asyncio.new_event_loop()
        try:
            history = bus.bind_and_replay(loop)
            assert len(history) == 2
            assert [e["type"] for e in history] == ["a", "b"]
        finally:
            loop.close()

    def test_emit_after_bind_pushes_to_queue(self):
        """Events emitted after bind_and_replay land in the async queue."""
        async def _run():
            bus = EventBus()
            bus.emit("before", {})
            bus.bind_and_replay(asyncio.get_running_loop())
            bus.emit("after", {"key": "val"})
            event = await bus.next_event(timeout=1.0)
            assert event is not None
            assert event["type"] == "after"
            assert event["data"]["key"] == "val"

        asyncio.run(_run())

    def test_next_event_returns_none_on_timeout(self):
        async def _run():
            bus = EventBus()
            bus.bind_and_replay(asyncio.get_running_loop())
            event = await bus.next_event(timeout=0.05)
            assert event is None

        asyncio.run(_run())

    def test_cross_thread_emit_reaches_queue(self):
        """Emit from a background thread is delivered to the async queue."""
        async def _run():
            bus = EventBus()
            bus.bind_and_replay(asyncio.get_running_loop())

            def bg_emit():
                bus.emit("from_thread", {"tid": "bg"})

            thread = threading.Thread(target=bg_emit)
            thread.start()
            thread.join()

            event = await bus.next_event(timeout=1.0)
            assert event is not None
            assert event["type"] == "from_thread"

        asyncio.run(_run())


class TestSetupCodeV2Integration:
    """Verify the new setup code executes in a LocalREPL without errors."""

    def test_setup_code_executes_cleanly(self):
        from rlm.environments.local_repl import LocalREPL
        from rlm_search.repl_tools import build_search_setup_code

        code = build_search_setup_code(
            api_url="https://test.com",
            rlm_model="test-model",
            rlm_backend="anthropic",
            depth=0,
            max_delegation_depth=1,
            sub_iterations=3,
            query="test question",
        )

        # The setup code should execute without errors in a real LocalREPL
        repl = LocalREPL(setup_code=code, depth=1)

        # Verify key functions exist in REPL namespace
        assert "search" in repl.locals
        assert "research" in repl.locals
        assert "draft_answer" in repl.locals
        assert "check_progress" in repl.locals
        assert "source_registry" in repl.locals

        repl.cleanup()

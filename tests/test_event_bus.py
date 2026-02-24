"""tests/test_event_bus.py"""

import threading

from rlm_search.bus import EventBus


class TestEventBusEmitAndDrain:
    def test_emit_single_event(self):
        bus = EventBus()
        bus.emit("test_event", {"key": "value"})
        events = bus.drain()
        assert len(events) == 1
        assert events[0]["type"] == "test_event"
        assert events[0]["data"]["key"] == "value"
        assert "timestamp" in events[0]

    def test_drain_clears_queue(self):
        bus = EventBus()
        bus.emit("a", {})
        bus.emit("b", {})
        first = bus.drain()
        assert len(first) == 2
        second = bus.drain()
        assert len(second) == 0

    def test_replay_returns_all_events_without_clearing(self):
        bus = EventBus()
        bus.emit("a", {"n": 1})
        bus.emit("b", {"n": 2})
        bus.drain()  # consume
        bus.emit("c", {"n": 3})
        # replay returns ALL events ever emitted
        all_events = bus.replay()
        assert len(all_events) == 3
        assert [e["type"] for e in all_events] == ["a", "b", "c"]

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
        import pytest

        from rlm_search.bus import SearchCancelled

        bus = EventBus()
        bus.cancel()
        with pytest.raises(SearchCancelled):
            bus.raise_if_cancelled()

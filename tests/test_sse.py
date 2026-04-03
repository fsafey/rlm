"""tests/test_sse.py"""

import json
from collections import Counter

from fastapi import FastAPI
from starlette.testclient import TestClient

from rlm_search.bus import EventBus
from rlm_search.sse import create_sse_router


class TestSSEEndpoint:
    def setup_method(self):
        self.app = FastAPI()
        self.searches: dict[str, EventBus] = {}
        self.app.include_router(create_sse_router(self.searches))

    def _parse_events(self, response_text: str) -> list[dict]:
        """Parse SSE response into event dicts (handles event: + data: lines)."""
        events = []
        for block in response_text.strip().split("\n\n"):
            data_line = next(
                (line for line in block.split("\n") if line.startswith("data:")), None,
            )
            if data_line:
                events.append(json.loads(data_line.removeprefix("data: ")))
        return events

    def test_stream_returns_events(self):
        bus = EventBus()
        bus.emit("metadata", {"root_model": "test"})
        bus.emit("done", {"answer": "result"})
        self.searches["s1"] = bus

        client = TestClient(self.app)
        response = client.get("/api/search/s1/stream", timeout=5)
        events = self._parse_events(response.text)
        types = [e["type"] for e in events]
        assert "metadata" in types
        assert "done" in types

    def test_stream_includes_event_type_field(self):
        """SSE output should use the event: field for client-side routing."""
        bus = EventBus()
        bus.emit("metadata", {"root_model": "test"})
        bus.emit("done", {"answer": "result"})
        self.searches["s1"] = bus

        client = TestClient(self.app)
        response = client.get("/api/search/s1/stream", timeout=5)
        # Verify event: lines are present
        lines = response.text.strip().split("\n")
        event_lines = [line for line in lines if line.startswith("event:")]
        assert len(event_lines) >= 2
        assert "event: metadata" in lines
        assert "event: done" in lines

    def test_stream_404_for_unknown_search(self):
        client = TestClient(self.app)
        response = client.get("/api/search/unknown/stream")
        assert response.status_code == 404

    def test_no_duplicate_events(self):
        """All pre-emitted events should appear exactly once via replay."""
        bus = EventBus()
        bus.emit("metadata", {"root_model": "test"})
        bus.emit("iteration", {"index": 0})
        bus.emit("iteration", {"index": 1})
        bus.emit("done", {"answer": "result"})
        self.searches["s1"] = bus

        client = TestClient(self.app)
        response = client.get("/api/search/s1/stream", timeout=5)
        events = self._parse_events(response.text)

        # Each event must appear exactly once
        type_counts = Counter(
            json.dumps({k: v for k, v in e.items() if k != "timestamp"}, sort_keys=True)
            for e in events
        )
        for key, count in type_counts.items():
            assert count == 1, f"Duplicate event: {key}"

        assert len(events) == 4

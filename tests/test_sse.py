"""tests/test_sse.py"""
import json

from starlette.testclient import TestClient
from fastapi import FastAPI

from rlm_search.bus import EventBus
from rlm_search.sse import create_sse_router


class TestSSEEndpoint:
    def setup_method(self):
        self.app = FastAPI()
        self.searches: dict[str, EventBus] = {}
        self.app.include_router(create_sse_router(self.searches))

    def test_stream_returns_events(self):
        bus = EventBus()
        bus.emit("metadata", {"root_model": "test"})
        bus.emit("done", {"answer": "result"})
        self.searches["s1"] = bus

        client = TestClient(self.app)
        response = client.get("/api/search/s1/stream", timeout=5)
        lines = [line for line in response.text.strip().split("\n") if line.startswith("data:")]
        assert len(lines) >= 2

        events = [json.loads(line.removeprefix("data: ")) for line in lines]
        types = [e["type"] for e in events]
        assert "metadata" in types
        assert "done" in types

    def test_stream_404_for_unknown_search(self):
        client = TestClient(self.app)
        response = client.get("/api/search/unknown/stream")
        assert response.status_code == 404

    def test_replay_on_reconnect(self):
        """If events already emitted before client connects, replay them."""
        bus = EventBus()
        bus.emit("metadata", {"root_model": "test"})
        bus.drain()  # simulate: first client already consumed
        bus.emit("done", {"answer": "result"})
        self.searches["s1"] = bus

        client = TestClient(self.app)
        response = client.get("/api/search/s1/stream?replay=true", timeout=5)
        lines = [line for line in response.text.strip().split("\n") if line.startswith("data:")]
        events = [json.loads(line.removeprefix("data: ")) for line in lines]
        types = [e["type"] for e in events]
        # Replay sends ALL events (metadata + done)
        assert "metadata" in types
        assert "done" in types

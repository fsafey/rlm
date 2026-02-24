"""tests/test_context_v2.py"""

from rlm_search.bus import EventBus
from rlm_search.evidence import EvidenceStore
from rlm_search.quality import QualityGate
from rlm_search.tools.context_v2 import SearchContext


class TestSearchContextCreation:
    def test_creates_with_departments(self):
        bus = EventBus()
        evidence = EvidenceStore()
        quality = QualityGate(evidence=evidence)
        ctx = SearchContext(
            api_url="https://example.com",
            api_key="test-key",
            bus=bus,
            evidence=evidence,
            quality=quality,
        )
        assert ctx.api_url == "https://example.com"
        assert ctx.evidence is evidence
        assert ctx.quality is quality
        assert ctx.bus is bus

    def test_headers_auto_generated(self):
        ctx = SearchContext(
            api_url="https://example.com",
            api_key="test-key",
            bus=EventBus(),
            evidence=EvidenceStore(),
            quality=QualityGate(evidence=EvidenceStore()),
        )
        assert ctx.headers["Authorization"] == "Bearer test-key"

    def test_llm_callables_default_none(self):
        ctx = SearchContext(
            api_url="https://example.com",
            api_key="",
            bus=EventBus(),
            evidence=EvidenceStore(),
            quality=QualityGate(evidence=EvidenceStore()),
        )
        assert ctx.llm_query is None
        assert ctx.llm_query_batched is None

    def test_tool_calls_list_for_repl_compat(self):
        """tool_calls must remain a plain list for REPL locals compatibility."""
        ctx = SearchContext(
            api_url="https://example.com",
            api_key="",
            bus=EventBus(),
            evidence=EvidenceStore(),
            quality=QualityGate(evidence=EvidenceStore()),
        )
        assert isinstance(ctx.tool_calls, list)

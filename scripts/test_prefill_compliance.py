"""Test assistant prefill effectiveness for REPL compliance.

Sends 20 queries through the RLM main loop (iteration 0 only) and checks
whether the model produces ```repl``` code blocks vs plain text.

Usage: cd ~/projects/rlm && uv run python scripts/test_prefill_compliance.py
"""

import json
import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load API key from standalone-search .env if not in rlm .env
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/Project/standalone-search/.env"))

from rlm_search.config import ANTHROPIC_API_KEY

# 20 diverse test queries across categories
TEST_QUERIES = [
    # WP - Worship
    "Is it permissible to combine fasts for Qadaa and the six white days in Shawwal?",
    "Can I pray sitting down due to back pain?",
    "What invalidates the fast during Ramadan?",
    "Is it permissible to delay Isha prayer until midnight?",
    # FN - Finance
    "Can I take a mortgage to buy a house in the West?",
    "Is cryptocurrency trading halal?",
    "Can I work at a restaurant that serves alcohol?",
    "Is it permissible to invest in stocks of companies that deal partially in haram?",
    # MF - Marriage & Family
    "Is temporary marriage with a Christian woman permissible?",
    "What are the conditions for a valid nikah?",
    "Can a woman initiate divorce in Islam?",
    "Is it obligatory to pay mahr before consummation?",
    # PT - Prayer & Tahara
    "How do I perform ghusl janabat correctly?",
    "Does touching a dog invalidate wudu?",
    "Can I pray with nail polish on?",
    "What is the ruling on combining Dhuhr and Asr prayers?",
    # BE - Beliefs & Ethics
    "Is music haram in Shia Islam?",
    "Can I celebrate Nowruz as a Muslim?",
    "What is the ruling on tattoos?",
    "Is it sinful to have doubts about faith?",
]


def build_test_prompt(query: str, kb_data: dict) -> list[dict]:
    """Build the exact prompt the RLM would send at iteration 0."""
    from rlm.utils.prompts import QueryMetadata, build_rlm_system_prompt, build_user_prompt
    from rlm_search.prompts import build_system_prompt
    from rlm_search.tools.context import ToolContext
    from rlm_search.tools.subagent_tools import init_classify

    # Run init_classify to get classification
    ctx = ToolContext(api_url="http://localhost:8092")
    ctx.kb_overview_data = kb_data
    ctx.llm_query = None
    ctx.llm_query_batched = None
    ctx._parent_logger = None
    init_classify(ctx, query)

    classification = ctx.classification
    query_variants = (classification or {}).get("query_variants", [])

    # Build setup summary (what would be in setup_code stdout)
    if classification:
        parts = [f"Category: {classification['category']} ({classification['confidence']})"]
        if classification.get("clusters"):
            parts.append(f"Clusters: {classification['clusters']}")
        if query_variants:
            parts.append(f"Query variants: {query_variants}")
        parts.append(f"Strategy: {classification['strategy']}")
        setup_summary = "Pre-classification: " + " | ".join(parts)
        setup_summary += "\n\nREPL variables ready: question, classification, query_variants, filters=classification['filters']"
        setup_summary += "\nWrite a ```repl``` block to call research() — do NOT answer in plain text."
    else:
        setup_summary = "Pre-classification: skipped"

    # Build the system prompt
    system_prompt = build_system_prompt(max_iterations=3)

    # Build message history (same as RLM._setup_prompt)
    metadata = QueryMetadata(query)
    message_history = build_rlm_system_prompt(
        system_prompt=system_prompt, query_metadata=metadata
    )

    # Add user prompt for iteration 0
    user_msg = build_user_prompt(
        root_prompt=query,
        iteration=0,
        context_count=1,
        history_count=0,
        setup_summary=setup_summary,
    )
    message_history.append(user_msg)

    # No prefill — Sonnet 4.6 does not support assistant message prefill

    return message_history, classification


def test_single_query(query: str, kb_data: dict) -> dict:
    """Test a single query and return compliance result."""
    from rlm.utils.parsing import find_code_blocks

    print(f"\n{'='*60}")
    print(f"Query: {query[:70]}...")

    # Build prompt
    t0 = time.time()
    prompt, classification = build_test_prompt(query, kb_data)

    classify_time = time.time() - t0
    cat = classification["category"] if classification else "NONE"
    print(f"  Classification: {cat} ({classify_time:.1f}s)")

    # Call LLM
    from anthropic import Anthropic
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    system = None
    messages = []
    for msg in prompt:
        if msg["role"] == "system":
            system = msg["content"]
        else:
            messages.append(msg)

    t1 = time.time()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=messages,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}] if system else None,
    )
    llm_time = time.time() - t1
    raw_response = response.content[0].text

    # Check for code blocks
    code_blocks = find_code_blocks(raw_response)
    has_code = len(code_blocks) > 0
    has_research = any("research(" in block for block in code_blocks)

    status = "PASS" if has_code else "FAIL"
    research_status = "research()" if has_research else "no research()" if has_code else "N/A"

    print(f"  LLM response: {len(raw_response)} chars ({llm_time:.1f}s)")
    print(f"  Code blocks: {len(code_blocks)} | {status} | {research_status}")
    if not has_code:
        print(f"  Response preview: {raw_response[:150]}...")

    return {
        "query": query,
        "category": cat,
        "has_code": has_code,
        "has_research": has_research,
        "code_block_count": len(code_blocks),
        "response_length": len(raw_response),
        "classify_time_s": round(classify_time, 1),
        "llm_time_s": round(llm_time, 1),
        "prefill": False,
    }


def main():
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set in .env")
        sys.exit(1)

    # Minimal KB overview for classification
    kb_data = {
        "categories": {
            "PT": {"name": "Prayer & Tahara", "document_count": 4938, "clusters": {"Ghusl": "How to perform ghusl?", "Wudu Ablution": "Steps of wudu?", "Salah Timing": "What are prayer times?"}, "facets": {"subtopics": [{"value": "purification", "count": 120}]}},
            "WP": {"name": "Worship Practices", "document_count": 3912, "clusters": {"Sawm Validity & Obligation": "Is fasting valid if...", "Sawm Integrity Rulings": "What breaks the fast?", "Sawm Hardship Exemptions": "Can I skip fasting if..."}, "facets": {"subtopics": [{"value": "fasting", "count": 200}]}},
            "FN": {"name": "Finance & Transactions", "document_count": 1891, "clusters": {"Banking Riba Operations": "Is mortgage permissible?", "Shariah Investment Screening": "How to screen investments?"}, "facets": {"subtopics": [{"value": "riba", "count": 80}]}},
            "MF": {"name": "Marriage & Family", "document_count": 900, "clusters": {"Nikah Conditions": "Requirements for marriage", "Mutah": "Temporary marriage rules"}, "facets": {"subtopics": []}},
            "BE": {"name": "Beliefs & Ethics", "document_count": 4100, "clusters": {"Taqlid": "Following a marja", "Tawbah": "Repentance conditions"}, "facets": {"subtopics": []}},
            "OT": {"name": "Other Topics", "document_count": 1200, "clusters": {}, "facets": {"subtopics": []}},
        }
    }

    print("=" * 60)
    print("PREFILL COMPLIANCE TEST")
    print(f"Queries: {len(TEST_QUERIES)} | Model: claude-sonnet-4-6")
    print("Backend: anthropic (direct API, native prefill)")
    print("=" * 60)

    results = []
    for i, query in enumerate(TEST_QUERIES):
        print(f"\n[{i+1}/{len(TEST_QUERIES)}]", end="")
        result = test_single_query(query, kb_data)
        results.append(result)

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r["has_code"])
    with_research = sum(1 for r in results if r["has_research"])
    failed = [r for r in results if not r["has_code"]]

    print(f"\n\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")
    print(f"Total:       {total}")
    print(f"With code:   {passed}/{total} ({100*passed/total:.0f}%)")
    print(f"With research(): {with_research}/{total} ({100*with_research/total:.0f}%)")
    print(f"Text-only:   {total-passed}/{total} ({100*(total-passed)/total:.0f}%)")

    if failed:
        print("\nFailed queries:")
        for r in failed:
            print(f"  - [{r['category']}] {r['query'][:60]}...")

    avg_llm = sum(r["llm_time_s"] for r in results) / total
    avg_classify = sum(r["classify_time_s"] for r in results) / total
    print(f"\nAvg classify: {avg_classify:.1f}s | Avg LLM: {avg_llm:.1f}s")

    # Save results
    out_path = os.path.join(os.path.dirname(__file__), "prefill_compliance_results.json")
    with open(out_path, "w") as f:
        json.dump({"summary": {"total": total, "passed": passed, "with_research": with_research, "avg_llm_s": avg_llm}, "results": results}, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()

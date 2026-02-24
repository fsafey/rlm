"""Shared constants for REPL tools."""

META_FIELDS = {
    "parent_code",
    "parent_category",
    "cluster_label",
    "primary_topic",
    "subtopics",
    # W3 processors need these for passage formatting and chapter derivation
    "ruling",
    "ruling_number",
    "chapter",
    "risala_chapter",
    "source_collection",
    "heading",
}

MAX_QUERY_LEN = 500
MAX_DRAFT_LEN = 8000

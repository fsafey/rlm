"""rlm_search/prompt_constants.py -- shared constants for prompts + QualityGate."""

# Quality thresholds
READY_THRESHOLD = 60
STALL_SEARCH_COUNT = 6
LOW_CONFIDENCE_THRESHOLD = 40

# Confidence weights (must sum to 100)
WEIGHT_RELEVANCE = 35
WEIGHT_QUALITY = 25
WEIGHT_BREADTH = 10
WEIGHT_DRAFT = 15
WEIGHT_CRITIQUE = 15

# Rating definitions
RATING_ORDER = {"RELEVANT": 0, "PARTIAL": 1, "OFF-TOPIC": 2, "UNKNOWN": 3}

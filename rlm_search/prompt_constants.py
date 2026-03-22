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

# Critique tier thresholds
STRONG_RELEVANT_MIN = 6
STRONG_CONFIDENCE_MIN = 50
MEDIUM_RELEVANT_MIN = 3

# Progressive gate: search saturation thresholds
SATURATION_LOW_YIELD = 1  # new unique results at or below this = "low yield" search
SATURATION_CONSECUTIVE_MAX = 2  # consecutive low-yield searches before stopping
MEDIUM_EXTRA_BUDGET = 2  # max extra queries allowed after reaching medium tier
EVAL_CHECKPOINT_SEARCH = 3  # search count at which to run mid-loop evaluation

# Explore phase: velocity-based saturation scoring
EXPLORE_SATURATION_THRESHOLD = 65  # saturation score (0-100) to exit explore phase
EXPLORE_MIN_SEARCHES = 2  # minimum searches before explore can graduate
VELOCITY_DECAY = 0.7  # exponential decay per search step (recent searches weighted more)
VELOCITY_SATURATE = 5.0  # 5+ new unique IDs per search = max velocity (1.0)
EXPLORE_EXTRA_BUDGET = 2  # additional extra_queries allowed during explore phase

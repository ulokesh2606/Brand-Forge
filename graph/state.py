"""
graph/state.py

CONCEPT: LangGraph State
------------------------
The State is the shared memory of the entire pipeline.
Every agent (node) receives the full state as input and returns
only the fields it changed as a dict.

We use TypedDict (not Pydantic BaseModel) at the top level because
LangGraph requires TypedDict for its StateGraph.
"""

from typing import TypedDict, Optional, Any


class BrandBrief(TypedDict):
    """
    What the user provides — campaign intent + existing marketing context.

    WHY we capture existing marketing context:
    A brand already running aggressive Google performance ads should get
    different content than one doing only organic LinkedIn thought leadership.
    Knowing what they're ALREADY doing makes our output consistent with
    their existing marketing motion — not a fresh start that contradicts it.
    """
    # Campaign intent
    campaign_goal: str      # e.g. "drive free trial signups for our AI feature"
    target_audience: str    # e.g. "busy working professionals aged 25-40"
    tone_keywords: list     # e.g. ["science-backed", "no-fluff", "results-driven"]

    # Existing marketing context — this is the key addition
    current_channels: list      # e.g. ["LinkedIn", "Google Ads", "Instagram"]
    current_messaging: str      # e.g. "We lead with 'work smarter not harder'"
    current_campaigns: str      # e.g. "Retargeting trial users who didn't convert"
    what_has_worked: str        # e.g. "Data-led LinkedIn posts get 3x more engagement"
    what_hasnt_worked: str      # e.g. "Motivational messaging gets ignored"
    competitors: list           # e.g. ["Peloton", "Whoop"] — what to differentiate from


class BrandGuidelines(TypedDict):
    """
    Output of Agent 1 — Brand Interpreter.
    Now includes marketing context summary and differentiation angles
    extracted from the existing marketing brief.
    """
    tone_rules: list
    content_pillars: list
    forbidden_phrases: list
    cta_style: str
    brand_voice_summary: str
    marketing_context_summary: str  # what's working, what to avoid, what angles to continue
    differentiation_angles: list    # how to stand apart from listed competitors


class ChannelStrategy(TypedDict):
    """Strategy for one channel. Agent 2 produces four of these."""
    angle: str
    hook: str
    key_message: str
    cta: str


class ContentStrategy(TypedDict):
    """Output of Agent 2 — Content Strategist. Email replaced with YouTube."""
    linkedin: ChannelStrategy
    instagram: ChannelStrategy
    youtube: ChannelStrategy    # YouTube video title + description strategy
    google_ad: ChannelStrategy


class ContentDrafts(TypedDict):
    """Output of Agent 3 — Content Writer."""
    linkedin: str    # 250-300 word professional post
    instagram: str   # punchy caption + 5 hashtags
    youtube: str     # Title + Description + Tags (formatted clearly)
    google_ad: str   # 3 headlines + 2 descriptions (character-limited)


class ChannelEvaluation(TypedDict):
    """Evaluation of a single channel by Agent 4."""
    status: str                             # "PASS" or "FAIL"
    which_rule_violated: Optional[str]
    exact_problem: Optional[str]
    concrete_recommendation: Optional[str]


class EvaluationResult(TypedDict):
    """Output of Agent 4 — Brand Voice Evaluator."""
    overall_status: str
    linkedin: ChannelEvaluation
    instagram: ChannelEvaluation
    youtube: ChannelEvaluation
    google_ad: ChannelEvaluation


class BrandState(TypedDict):
    """
    CONCEPT: The shared state passed to StateGraph().
    Every agent receives the full BrandState and returns a partial dict
    with only the fields it modified. LangGraph merges automatically.
    """
    # Inputs
    url: str
    brief: BrandBrief

    # Set by scraper (before graph)
    raw_scraped_content: str

    # Set by Agent 1
    brand_guidelines: Optional[BrandGuidelines]

    # Set by Agent 2
    content_strategy: Optional[ContentStrategy]

    # Set by Agent 3 (updated on each retry)
    content_drafts: Optional[ContentDrafts]
    iteration_count: int

    # Human-In-The-Loop feedback
    human_feedback: str

    # HITL Signal — used to tell the router when we have expert approval or feedback
    hitl_action: Optional[str]  # e.g. "RESUME" or "RESTART" or None
    
    # Set by Agent 4
    evaluation_result: Optional[EvaluationResult]
    evaluation_feedback: Optional[str]

    # Set on PASS — final deliverable
    final_content: Optional[ContentDrafts]

    # User-selected output channels (e.g. ["linkedin", "youtube"])
    selected_channels: list

    # Pipeline identity — used for Qdrant collection naming + LangGraph checkpointing
    thread_id: str

    # RAG indexing stats — populated after brand content is indexed
    rag_stats: Optional[dict]  # {"chunks": int, "collection": str, "cached": bool}

    # Store previous drafts for UI comparisons
    previous_content_drafts: Optional[dict]

    # Max number of AI rewrite iterations before handing off to human review
    max_iterations: int

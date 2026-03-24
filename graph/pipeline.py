"""
graph/pipeline.py — BrandForge LangGraph Pipeline

ARCHITECTURE:
────────────────────────────────────────────────────────────────────────────

  [Web Scraper] → Qdrant RAG Index
       ↓
  StateGraph:
  ┌─────────────────────────────────────────────────────────┐
  │  START                                                  │
  │    → brand_interpreter  (Agent 1)                       │
  │    → content_strategist (Agent 2)                       │
  │    → content_writer     (Agent 3)   ←──────────────┐   │
  │    → brand_voice_evaluator (Agent 4)                │   │
  │         ↓                                          │   │
  │        END          send feedback ──────────────────┘   │
  └─────────────────────────────────────────────────────────┘

LANGGRAPH FEATURES USED:
  - StateGraph + TypedDict state (typed shared memory)
  - Conditional edges (route_after_evaluation reads state → returns node name)
  - MemorySaver checkpointing (every node transition is checkpointed)
  - Thread IDs (each pipeline run is a replayable, inspectable session)

RAG INTEGRATION:
  - Scraped content is chunked + embedded BEFORE the graph runs
  - Stored in Qdrant (in-memory) keyed by thread_id
  - Agents query the collection with targeted semantic queries instead of
    receiving a raw text dump
"""

import uuid
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from graph.state import BrandState
from agents.brand_interpreter import brand_interpreter
from agents.content_strategist import content_strategist
from agents.content_writer import content_writer
from agents.brand_voice_evaluator import brand_voice_evaluator
from scraper.web_scraper import scrape_brand_website
from rag.brand_memory import index_brand_content


# ── Constants ─────────────────────────────────────────────────────────────────
MAX_AI_ITERATIONS = 3 # Max number of times the AI will rewrite content automatically


# ── Routing ───────────────────────────────────────────────────────────────────

def route_after_evaluation(state: dict) -> str:
    """
    CONCEPT: Conditional edge routing function

    Called by LangGraph after Agent 4 runs. Reads state → returns a string
    that maps to the next node (or END).

    Routing logic:
      - final_content is set (by evaluator at max iterations) → END → human reviews
      - otherwise → loop back to content_writer for another AI rewrite
    """
    if state.get("final_content") is not None:
        print("[Router] final_content is set → routing to END (human review stage)")
        return END

    print("[Router] Continuing AI rewrite loop → routing back to content_writer")
    return "content_writer"


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """
    Builds and compiles the LangGraph StateGraph.

    Nodes: 4 agents, each a plain Python function that reads + writes state.
    Edges: mostly sequential, with ONE conditional edge after Agent 4 that
           implements the rewrite loop.

    MemorySaver: every state transition is saved in memory, keyed by thread_id.
    In production, swap MemorySaver() for SqliteSaver or RedisSaver.
    """
    graph = StateGraph(BrandState)

    # Register nodes (name → function)
    graph.add_node("brand_interpreter",    brand_interpreter)
    graph.add_node("content_strategist",   content_strategist)
    graph.add_node("content_writer",       content_writer)
    graph.add_node("brand_voice_evaluator", brand_voice_evaluator)

    # Linear edges
    graph.set_entry_point("brand_interpreter")
    graph.add_edge("brand_interpreter",  "content_strategist")
    graph.add_edge("content_strategist", "content_writer")
    graph.add_edge("content_writer",     "brand_voice_evaluator")

    # Conditional edge — this is the rewrite loop
    graph.add_conditional_edges(
        "brand_voice_evaluator",
        route_after_evaluation,
        {
            "content_writer": "content_writer",
            END: END,
        },
    )

    # Compile with MemorySaver — enables checkpointing + thread_id tracking
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


# ── Compile once at import time ───────────────────────────────────────────────
_compiled_graph = build_graph()


# ── Public API ────────────────────────────────────────────────────────────────

def run_pipeline(
    url: str,
    brief_dict: dict,
    raw_content_override: str = None,
    selected_channels: list = None,
    thread_id: str = None,
    human_feedback: str = "",
) -> dict:
    """
    Runs the full BrandForge pipeline.

    Steps:
        0. Generate or accept a thread_id (LangGraph session identifier)
        1. Get website content (crawl4ai or override text)
        2. Index content into Qdrant RAG store (chunk + embed)
        3. Invoke the compiled LangGraph (agents 1-4 + conditional loop)
        4. Return the final state

    Args:
        url:                  Brand's website URL
        brief_dict:           Campaign context (goal, audience, tone, etc.)
        raw_content_override: If set, skip live crawl and use this text.
                              Use for fictional brands or JS-heavy sites.
        selected_channels:    Which platforms to generate content for.
                              Defaults to all 4 if not specified.
        thread_id:            LangGraph session ID for checkpointing.
                              Auto-generated (UUID) if not provided.
        human_feedback:       Optional feedback for the first iteration.

    Returns:
        Full final state dict (all agent outputs + metadata)
    """
    # ── Setup ─────────────────────────────────────────────────────────────────
    if selected_channels is None:
        selected_channels = ["linkedin", "instagram", "youtube", "google_ad"]

    if thread_id is None:
        thread_id = str(uuid.uuid4())[:8]

    print(f"\n{'='*55}")
    print(f"  BrandForge Pipeline  |  thread: {thread_id}")
    print(f"  Channels: {', '.join(selected_channels)}")
    print(f"{'='*55}\n")

    # ── Step 1: Website content ───────────────────────────────────────────────
    if raw_content_override and raw_content_override.strip():
        raw_scraped_content = raw_content_override.strip()
        print(f"[Scraper] Using provided content ({len(raw_scraped_content)} chars) — skipping live crawl\n")
    else:
        print(f"[Scraper] Crawling {url}...")
        raw_scraped_content = scrape_brand_website(url)
        print(f"[Scraper] Extracted {len(raw_scraped_content)} chars\n")

    # ── Step 2: RAG indexing ──────────────────────────────────────────────────
    # Chunk + embed the brand content into Qdrant before the graph runs.
    # Agents will query this collection with semantic search.
    print(f"[RAG] Building brand knowledge index...")
    rag_stats = index_brand_content(raw_scraped_content, thread_id=thread_id)
    print(f"[RAG] {rag_stats['chunks']} chunks indexed in collection '{rag_stats['collection']}'\n")

    # ── Step 3: Build initial state ───────────────────────────────────────────
    initial_state: BrandState = {
        "url":                 url,
        "brief":               brief_dict,
        "raw_scraped_content": raw_scraped_content,
        "brand_guidelines":    None,
        "content_strategy":    None,
        "content_drafts":      None,
        "evaluation_result":   None,
        "evaluation_feedback": None,
        "iteration_count":     0,
        "human_feedback":      human_feedback,
        "hitl_action":         None,
        "final_content":       None,
        "selected_channels":   selected_channels,
        "thread_id":           thread_id,
        "rag_stats":           rag_stats,
        "max_iterations":      MAX_AI_ITERATIONS,
    }

    # ── Step 4: Run the graph ─────────────────────────────────────────────────
    # LangGraph checkpoints every state transition under this thread_id.
    # To replay or inspect: _compiled_graph.get_state({"configurable": {"thread_id": thread_id}})
    config     = {"configurable": {"thread_id": thread_id}}
    final_state = _compiled_graph.invoke(initial_state, config=config)

    print(f"\n{'='*55}")
    print(f"  Pipeline complete  |  thread: {thread_id}")
    print(f"  AI Iterations: {final_state.get('iteration_count')}")
    print(f"  Status: Ready for human review")
    print(f"{'='*55}\n")

    return dict(final_state)


def resume_pipeline(
    url: str,
    brief_dict: dict,
    raw_content_override: str = None,
    selected_channels: list = None,
    human_feedback: str = "",
    previous_drafts: dict = None,
    brand_guidelines: dict = None,
    content_strategy: dict = None,
) -> dict:
    """
    Resume pipeline with HUMAN expert feedback as top priority.

    Called after the user reviews generated content and provides revision notes.
    The human feedback is injected as a PRIORITY directive in the system prompt.
    Previous drafts are shown to Agent 3 as context (what was already written).

    The pipeline skips Agent 1 (brand interpreter) and Agent 2 (strategy)
    since those are already done — it runs only Agent 3 + Agent 4 loop
    to refine the existing content based on human direction.
    """
    if selected_channels is None:
        selected_channels = ["linkedin", "instagram", "youtube", "google_ad"]

    thread_id = str(uuid.uuid4())[:8]

    print(f"\n{'='*55}")
    print(f"  BrandForge HITL Resume  |  thread: {thread_id}")
    print(f"  🚨 Human feedback priority-injected")
    print(f"  Channels: {', '.join(selected_channels)}")
    print(f"{'='*55}\n")

    # ── RAG indexing (reuse or rebuild) ──────────────────────────────────────
    raw_scraped_content = raw_content_override or ""
    if raw_scraped_content:
        print(f"[RAG] Rebuilding brand knowledge index for refinement run...")
        rag_stats = index_brand_content(raw_scraped_content, thread_id=thread_id)
        print(f"[RAG] {rag_stats['chunks']} chunks indexed\n")
    else:
        rag_stats = {"chunks": 0, "collection": thread_id, "cached": False}

    # ── Build graph for refinement: skip Agent 1 + 2, start at Agent 3 ───────
    graph = StateGraph(BrandState)
    graph.add_node("content_writer",        content_writer)
    graph.add_node("brand_voice_evaluator", brand_voice_evaluator)
    graph.set_entry_point("content_writer")
    graph.add_edge("content_writer", "brand_voice_evaluator")
    graph.add_conditional_edges(
        "brand_voice_evaluator",
        route_after_evaluation,
        {"content_writer": "content_writer", END: END},
    )
    checkpointer = MemorySaver()
    refinement_graph = graph.compile(checkpointer=checkpointer)

    # ── Build state with previous drafts + human feedback ────────────────────
    initial_state: BrandState = {
        "url":                 url,
        "brief":               brief_dict,
        "raw_scraped_content": raw_scraped_content,
        "brand_guidelines":    brand_guidelines or {},
        "content_strategy":    content_strategy or {},
        "content_drafts":      previous_drafts or {},   # Agent 3 sees previous work
        "evaluation_result":   None,
        "evaluation_feedback": None,
        "iteration_count":     0,
        "human_feedback":      human_feedback,           # 🚨 TOP PRIORITY directive
        "hitl_action":         "RESUME",
        "final_content":       None,
        "selected_channels":   selected_channels,
        "thread_id":           thread_id,
        "rag_stats":           rag_stats,
        "max_iterations":      MAX_AI_ITERATIONS,
    }

    config      = {"configurable": {"thread_id": thread_id}}
    final_state = refinement_graph.invoke(initial_state, config=config)

    print(f"\n{'='*55}")
    print(f"  HITL Refinement complete  |  thread: {thread_id}")
    print(f"  AI Iterations: {final_state.get('iteration_count')}")
    print(f"  Status: Ready for human review")
    print(f"{'='*55}\n")

    return dict(final_state)


def get_pipeline_state(thread_id: str) -> dict:
    """
    Retrieve the checkpointed state for a previous pipeline run.
    Demonstrates LangGraph's built-in state persistence.

    Usage:
        state = get_pipeline_state("abc12345")
        print(state["brand_guidelines"])
    """
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = _compiled_graph.get_state(config)
    return dict(snapshot.values) if snapshot else {}


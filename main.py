"""
main.py — BrandForge FastAPI Backend
Run: uvicorn main:app --reload
"""

import warnings
warnings.filterwarnings("ignore", message=".*urllib3.*")
warnings.filterwarnings("ignore", message=".*chardet.*")
warnings.filterwarnings("ignore", message=".*charset_normalizer.*")
try:
    from requests.exceptions import RequestsDependencyWarning
    warnings.filterwarnings("ignore", category=RequestsDependencyWarning)
except ImportError:
    pass

import asyncio
import json
import uuid
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# --- In-Memory Auth for Demo ---
USERS = {"admin": "password123"} # Default demo account
ACTIVE_SESSIONS = set()

class AuthRequest(BaseModel):
    username: str
    password: str

from graph.pipeline import _compiled_graph, run_pipeline, resume_pipeline
from scraper.web_scraper import scrape_brand_website
from rag.brand_memory import index_brand_content
from agents.content_writer import content_writer
from agents.brand_voice_evaluator import brand_voice_evaluator
from graph.pipeline import route_after_evaluation, END # Need END and router
from langgraph.graph import StateGraph
from langgraph.checkpoint.memory import MemorySaver
from graph.state import BrandState

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title="BrandForge API",
    description="Multi-agent LangGraph pipeline for AI-powered marketing content generation",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/", response_class=FileResponse)
def serve_frontend():
    return FileResponse("frontend/index.html")

@app.post("/api/v1/auth/register")
async def register(req: AuthRequest):
    if req.username in USERS:
        raise HTTPException(status_code=400, detail="User already exists")
    USERS[req.username] = req.password
    return {"message": "User registered successfully"}

@app.post("/api/v1/auth/login")
async def login(req: AuthRequest):
    if req.username not in USERS or USERS[req.username] != req.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    ACTIVE_SESSIONS.add(req.username)
    return {"token": f"mock-token-{uuid.uuid4()}", "username": req.username}

@app.get("/health")
async def health():
    return {"status": "ok", "version": "3.0.0"}

# ── Request / Response models ─────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    url: str
    website_content: str = ""          # optional paste override
    campaign_goal: str
    target_audience: str
    tone_keywords: list[str] = []
    current_channels: list[str] = []
    current_messaging: str = ""
    current_campaigns: str = ""
    what_has_worked: str = ""
    what_hasnt_worked: str = ""
    competitors: list[str] = []
    selected_channels: list[str] = ["linkedin", "instagram", "youtube", "google_ad"]
    thread_id: str = ""
    human_feedback: str = ""

class ResumeRequest(BaseModel):
    thread_id: str
    human_feedback: str = ""
    approve_as_is: bool = False


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "service": "BrandForge v3"}


# ── Blocking endpoint (returns full result) ───────────────────────────────────
@app.post("/api/v1/generate")
def generate(req: GenerateRequest):
    """
    Runs the full 4-agent pipeline synchronously.
    Suitable for programmatic use. Returns the full state JSON.
    """
    try:
        result = run_pipeline(
            url=req.url,
            brief_dict=_build_brief(req),
            raw_content_override=req.website_content or None,
            selected_channels=req.selected_channels,
            thread_id=req.thread_id or None,
        )
        return _format_response(result)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=f"Pipeline error: {str(e)}")


# ── Streaming SSE endpoint ────────────────────────────────────────────────────
@app.post("/api/v1/generate/stream")
async def generate_stream(req: GenerateRequest):
    """
    Streams pipeline progress via Server-Sent Events.

    The frontend connects to this endpoint and receives events as each
    LangGraph node completes. This uses LangGraph's built-in .stream() API
    which yields {node_name: node_output} after every state transition.

    Event format:
        data: {"event": "agent_done", "agent": "brand_interpreter", "data": {...}}\n\n
    """
    thread_id = req.thread_id or str(uuid.uuid4())[:8]

    async def event_stream() -> AsyncIterator[str]:
        def sse(event: str, data: dict) -> str:
            return f"data: {json.dumps({'event': event, 'thread_id': thread_id, **data})}\n\n"

        try:
            # Step 1: website content
            yield sse("progress", {"step": "scraper", "message": "Fetching website content..."})
            await asyncio.sleep(0)  # yield control

            if req.website_content and req.website_content.strip():
                raw_content = req.website_content.strip()
                yield sse("progress", {"step": "scraper", "message": f"Using pasted content ({len(raw_content)} chars)"})
            else:
                raw_content = await asyncio.to_thread(scrape_brand_website, req.url)
                yield sse("progress", {"step": "scraper", "message": f"Crawled {len(raw_content)} chars from {req.url}"})

            # Step 2: RAG indexing
            yield sse("progress", {"step": "rag", "message": "Indexing brand content into Qdrant..."})
            rag_stats = await asyncio.to_thread(index_brand_content, raw_content, thread_id)
            yield sse("rag_done", {
                "step": "rag",
                "chunks": rag_stats["chunks"],
                "collection": rag_stats["collection"],
                "message": f"Indexed {rag_stats['chunks']} chunks into Qdrant",
            })

            # Step 3: Build initial state
            selected_channels = req.selected_channels or ["linkedin", "instagram", "youtube", "google_ad"]
            initial_state = {
                "url":                 req.url,
                "brief":               _build_brief(req),
                "raw_scraped_content": raw_content,
                "brand_guidelines":    None,
                "content_strategy":    None,
                "content_drafts":      None,
                "evaluation_result":   None,
                "evaluation_feedback": None,
                "iteration_count":     0,
                "human_feedback":      req.human_feedback or "",
                "final_content":       None,
                "selected_channels":   selected_channels,
                "thread_id":           thread_id,
                "rag_stats":           rag_stats,
            }

            config = {"configurable": {"thread_id": thread_id}}

            # Step 4: Stream LangGraph — yields after each node completes
            AGENT_LABELS = {
                "brand_interpreter":    {"label": "Agent 1 — Brand Interpreter",  "icon": "🧠"},
                "content_strategist":   {"label": "Agent 2 — Content Strategist", "icon": "🎯"},
                "content_writer":       {"label": "Agent 3 — Content Writer",     "icon": "✍️"},
                "brand_voice_evaluator":{"label": "Agent 4 — Brand Voice Evaluator", "icon": "🔍"},
            }

            final_state = None
            async for chunk in _compiled_graph.astream(initial_state, config=config):
                # Retrieve the full state to get precise iteration counts + results
                snapshot = _compiled_graph.get_state(config)
                state_values = dict(snapshot.values) if snapshot else {}
                iter_count = state_values.get("iteration_count", 0)

                for node_name, node_output in chunk.items():
                    meta = AGENT_LABELS.get(node_name, {"label": node_name, "icon": "⚙️"})

                    yield sse("agent_done", {
                        "step":       node_name,
                        "label":      meta["label"],
                        "icon":       meta["icon"],
                        "iteration":  iter_count,
                        "message":    _agent_summary(node_name, node_output),
                    })

                    # Track final state
                    if node_output.get("final_content"):
                        final_state = node_output

                await asyncio.sleep(0)

            # Step 5: Retrieve full final state from checkpoint
            snapshot   = _compiled_graph.get_state(config)
            full_state = dict(snapshot.values) if snapshot else {}

            yield sse("complete", {
                "result":     _format_response(full_state),
                "thread_id":  thread_id,
                "message":    "Pipeline complete",
            })

        except Exception as e:
            yield sse("error", {"message": str(e)})

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/v1/generate/resume")
async def resume_stream(req: ResumeRequest):
    """
    Resumes a paused LangGraph pipeline after human intervention.
    
    If approve_as_is is True, it forces Agent 4's status to PASS in the state
    and finishes the graph. Otherwise, it injects human_feedback and lets Agent 3 rewrite.
    """
    thread_id = req.thread_id
    config = {"configurable": {"thread_id": thread_id}}

    async def event_stream() -> AsyncIterator[str]:
        def sse(event: str, data: dict) -> str:
            return f"data: {json.dumps({'event': event, 'thread_id': thread_id, **data})}\n\n"

        try:
            snapshot = _compiled_graph.get_state(config)
            if not snapshot:
                yield sse("error", {"message": "State not found for thread"})
                return

            curr_state = dict(snapshot.values)
            
            yield sse("progress", {"step": "hitl", "message": "Human steering received. Compiling refinement loop..."})
            await asyncio.sleep(0)

            # Rebuild graph for refinement
            from langgraph.graph import StateGraph
            from langgraph.checkpoint.memory import MemorySaver
            from graph.state import BrandState
            from agents.content_writer import content_writer
            from agents.brand_voice_evaluator import brand_voice_evaluator
            from graph.pipeline import route_after_evaluation, END

            graph = StateGraph(BrandState)
            graph.add_node("content_writer", content_writer)
            graph.add_node("brand_voice_evaluator", brand_voice_evaluator)
            graph.set_entry_point("content_writer")
            graph.add_edge("content_writer", "brand_voice_evaluator")
            graph.add_conditional_edges("brand_voice_evaluator", route_after_evaluation, {"content_writer": "content_writer", END: END})
            refinement_graph = graph.compile(checkpointer=MemorySaver())

            old_final = curr_state.get("final_content") or curr_state.get("content_drafts", {})
            new_drafts = dict(old_final) # Make a copy

            # Apply UI manual edits directly if available
            parsed_hf = req.human_feedback.strip()
            if parsed_hf.startswith("{"):
                try:
                    hf_data = json.loads(parsed_hf)
                    # Support mapping UI keys like "google_ad" natively
                    for ui_k, text_edit in hf_data.get("edits", {}).items():
                        new_drafts[ui_k] = text_edit
                except Exception:
                    pass

            initial_state = {
                "url":                 curr_state.get("url"),
                "brief":               curr_state.get("brief"),
                "raw_scraped_content": curr_state.get("raw_scraped_content"),
                "brand_guidelines":    curr_state.get("brand_guidelines", {}),
                "content_strategy":    curr_state.get("content_strategy", {}),
                "content_drafts":      new_drafts,
                "evaluation_result":   None,
                "evaluation_feedback": None,
                "iteration_count":     0,
                "human_feedback":      req.human_feedback,
                "hitl_action":         "RESUME",
                "final_content":       None,
                "selected_channels":   curr_state.get("selected_channels"),
                "thread_id":           thread_id,
                "rag_stats":           curr_state.get("rag_stats"),
                "previous_content_drafts": curr_state.get("final_content") or curr_state.get("content_drafts", {}),
                "max_iterations":      curr_state.get("max_iterations", 3),
            }

            yield sse("progress", {"step": "hitl", "message": "Resuming rewrite loop..."})
            
            async for chunk in refinement_graph.astream(initial_state, config=config):
                snap = refinement_graph.get_state(config)
                s_vals = dict(snap.values) if snap else {}
                iter_val = s_vals.get("iteration_count", 0)

                for node_name, node_output in chunk.items():
                    AGENT_LABELS = {
                        "content_writer":       {"label": "Agent 3 — Content Writer",     "icon": "✍️"},
                        "brand_voice_evaluator":{"label": "Agent 4 — Brand Voice Evaluator", "icon": "🔍"},
                    }
                    meta = AGENT_LABELS.get(node_name, {"label": node_name, "icon": "⚙️"})

                    yield sse("agent_done", {
                        "step":       node_name,
                        "label":      meta["label"],
                        "icon":       meta["icon"],
                        "iteration":  iter_val,
                        "message":    _agent_summary(node_name, node_output),
                    })
                    
            final_snapshot = refinement_graph.get_state(config)
            full_state = dict(final_snapshot.values)
            yield sse("complete", {"result": _format_response(full_state), "thread_id": thread_id})

        except Exception as e:
            yield sse("error", {"message": str(e)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── State inspection (LangGraph checkpointing demo) ───────────────────────────
@app.get("/api/v1/state/{thread_id}")
def get_state(thread_id: str):
    """Retrieve checkpointed state for any previous pipeline run."""
    from graph.pipeline import get_pipeline_state
    state = get_pipeline_state(thread_id)
    if not state:
        raise HTTPException(404, detail=f"No state found for thread_id: {thread_id}")
    return state


# ── Helpers ───────────────────────────────────────────────────────────────────
def _build_brief(req: GenerateRequest) -> dict:
    return {
        "campaign_goal":    req.campaign_goal,
        "target_audience":  req.target_audience,
        "tone_keywords":    req.tone_keywords,
        "current_channels": req.current_channels,
        "current_messaging":   req.current_messaging,
        "current_campaigns":   req.current_campaigns,
        "what_has_worked":     req.what_has_worked,
        "what_hasnt_worked":   req.what_hasnt_worked,
        "competitors":         req.competitors,
    }


def _format_response(state: dict) -> dict:
    return {
        "thread_id":        state.get("thread_id"),
        "final_content":    state.get("final_content"),
        "brand_guidelines": state.get("brand_guidelines"),
        "evaluation_result":state.get("evaluation_result"),
        "iteration_count":  state.get("iteration_count", 0),
        "rag_stats":        state.get("rag_stats"),
        "selected_channels":state.get("selected_channels"),
        "evaluation_feedback": state.get("evaluation_feedback"),
        "previous_content_drafts": state.get("previous_content_drafts", {})
    }


def _agent_summary(node: str, output: dict) -> str:
    if node == "brand_interpreter":
        v = (output.get("brand_guidelines") or {}).get("brand_voice_summary", "")
        return f"Brand voice extracted — {v[:80]}..." if v else "Brand guidelines extracted"
    if node == "content_strategist":
        return "Per-channel strategy defined (angle, hook, CTA)"
    if node == "content_writer":
        drafts = output.get("content_drafts") or {}
        it = output.get("iteration_count", 1)
        channels = ", ".join(drafts.keys())
        return f"Iteration {it} — wrote: {channels}"
    if node == "brand_voice_evaluator":
        er = output.get("evaluation_result") or {}
        status = er.get("overall_status", "?")
        fc = output.get("final_content")
        if fc:
            return f"Status: {status} — content approved"
        return f"Status: {status} — feedback sent to Agent 3"
    return "Completed"

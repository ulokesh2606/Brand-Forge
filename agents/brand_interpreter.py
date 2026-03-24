"""
agents/brand_interpreter.py — Agent 1: Brand Interpreter

WHAT IT DOES:
    Synthesizes brand guidelines from RAG-retrieved website content + the
    full marketing brief. Output is a structured JSON that every downstream
    agent follows as inviolable rules.

ARCHITECTURE DECISION — WHY RAG HERE:
    Naive approach: pass all 50,000 chars of scraped content to GPT.
    Problem: noise (navbars, footers, cookie banners), wasted tokens,
    diluted signal.

    RAG approach: query the Qdrant index with targeted semantic queries
    (brand voice, product features, audience signals) and retrieve only
    the 5-8 most relevant chunks (≈800-1200 tokens of focused content).

    Result: Agent 1 gets high-SNR context, produces sharper guidelines.
"""

import json
import os
from openai import OpenAI
from dotenv import load_dotenv
from rag.brand_memory import retrieve_as_context

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


SYSTEM_PROMPT = """You are a senior brand strategist with deep marketing expertise. \
Your job is to synthesize website content and real marketing context into a precise, \
actionable set of brand guidelines.

These guidelines will be used by a content writing AI across LinkedIn, Instagram, \
YouTube, and Google Ads. Be specific and grounded in the source material.

Return ONLY valid JSON. No preamble, no markdown fences. Just the JSON object."""


# ── RAG queries — targeted semantic searches against the brand knowledge store ──
RAG_QUERIES = [
    "brand voice tone personality values mission",
    "product features benefits what makes it unique differentiation",
    "target customer audience who it's built for problems it solves",
    "pricing plans trial free features",
    "competitors comparison why choose us vs alternatives",
]


def _build_user_prompt(retrieved_context: str, brief: dict) -> str:
    tone_keywords    = ", ".join(brief.get("tone_keywords", []))
    current_channels = ", ".join(brief.get("current_channels", []))
    competitors      = ", ".join(brief.get("competitors", []))

    return f"""BRAND KNOWLEDGE (retrieved via semantic search from scraped website):
{retrieved_context}

CAMPAIGN BRIEF:
- Goal: {brief.get("campaign_goal")}
- Target audience: {brief.get("target_audience")}
- Tone keywords: {tone_keywords}

EXISTING MARKETING INTELLIGENCE:
- Channels currently used: {current_channels}
- Current messaging/positioning: {brief.get("current_messaging")}
- Active campaigns: {brief.get("current_campaigns")}
- What has worked: {brief.get("what_has_worked")}
- What has NOT worked: {brief.get("what_hasnt_worked")}
- Main competitors: {competitors}

Using ALL of the above, extract brand guidelines in this exact JSON format:
{{
  "tone_rules": [
    "specific writing instruction grounded in what works for this brand",
    "another instruction",
    "another instruction"
  ],
  "content_pillars": [
    "core theme 1 this brand owns",
    "core theme 2",
    "core theme 3"
  ],
  "forbidden_phrases": [
    "phrase that contradicts what has worked or is used by competitors",
    "another phrase to avoid",
    "another phrase to avoid"
  ],
  "cta_style": "how this brand asks for action based on what has worked",
  "brand_voice_summary": "one detailed paragraph describing the brand voice, \
tone, and personality — grounded in the real marketing context provided",
  "marketing_context_summary": "one paragraph summarising the brand's current \
marketing situation — what angles they've been using, what's resonating, \
what to avoid, and what the new content should build on or differentiate from",
  "differentiation_angles": [
    "specific way to differentiate from competitor 1",
    "specific way to differentiate from competitor 2"
  ]
}}

tone_rules must be actionable writing instructions:
- "always open with a specific number or data point"
- "write in second person — address the reader directly as 'you'"
- "never use passive voice"

forbidden_phrases should reflect what hasn't worked AND what competitors overuse."""


def brand_interpreter(state: dict) -> dict:
    """
    LANGGRAPH NODE — Agent 1: Brand Interpreter

    Reads from State:
        - raw_scraped_content  (used for fallback if RAG not indexed)
        - brief                (full marketing context)
        - thread_id            (used to query the Qdrant collection)

    Writes to State:
        - brand_guidelines     (structured JSON used by all downstream agents)
    """
    print("[Agent 1] Running Brand Interpreter...")

    brief     = state.get("brief", {})
    thread_id = state.get("thread_id", "default")

    # ── RAG Retrieval ─────────────────────────────────────────────────────────
    # Run multiple targeted queries against the brand knowledge store.
    # Each query retrieves the 4 most relevant chunks for that topic.
    # We deduplicate and join into a single context block.
    all_chunks = []
    seen = set()

    for query in RAG_QUERIES:
        from rag.brand_memory import retrieve
        chunks = retrieve(query, thread_id=thread_id, k=4)
        for chunk in chunks:
            if chunk not in seen:
                seen.add(chunk)
                all_chunks.append((query, chunk))

    if all_chunks:
        retrieved_context = "\n\n".join(
            f"[Query: {q}]\n{c}" for q, c in all_chunks
        )
        print(f"[Agent 1] Using {len(all_chunks)} RAG-retrieved chunks from Qdrant.")
    else:
        # Fallback: use raw scraped content directly
        raw = state.get("raw_scraped_content", "")
        retrieved_context = raw[:8000]  # cap to avoid token overflow
        print(f"[Agent 1] RAG not available — using raw scraped content ({len(retrieved_context)} chars).")

    # ── LLM call ──────────────────────────────────────────────────────────────
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": _build_user_prompt(retrieved_context, brief)},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )

    brand_guidelines = json.loads(response.choices[0].message.content)
    print(f"[Agent 1] Done. Voice: {brand_guidelines.get('brand_voice_summary','')[:80]}...")

    return {"brand_guidelines": brand_guidelines}

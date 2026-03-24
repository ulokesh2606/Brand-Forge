"""
agents/content_writer.py — Agent 3

Writes content for selected channels using brand guidelines + channel strategy.
On retry iterations, feedback from Agent 4 is parsed into structured directives
so the model has precise, mandatory instructions rather than vague hints.
"""

import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# All supported channels + their display name and internal key
ALL_CHANNELS = {
    "LinkedIn":  "linkedin",
    "Instagram": "instagram",
    "YouTube":   "youtube",
    "Google Ads": "google_ad",
}

def _build_system_prompt(url: str, target_audience: str, campaign_goal: str, guidelines: dict, human_feedback: str = "") -> str:
    """
    Build a dynamic 'Brand Bible' system prompt.
    Injects brand identity, voice, goals, and RAG context rules.
    """
    brand_name = url.split("//")[-1].split("/")[0].replace("www.", "").split(".")[0].capitalize()
    if not brand_name or "example" in brand_name:
        brand_name = "this brand"

    voice = guidelines.get("brand_voice_summary", "professional and clear")
    tone_rules = ", ".join(guidelines.get("tone_rules", []))
    
    # 🚩 HITL Priority Injection
    human_priority = f"\n🚨 HUMAN EXPERT DIRECTIVE (URGENT/PRIORITY):\n- {human_feedback}\n" if human_feedback else ""

    return f"""You are the lead marketing copywriter for {brand_name}.
{human_priority}
**WRITING PRINCIPLES: AGENT-LIGHTNING OPTIMIZED**
1. **NO JARGON**: You are in "Expert Mode." Avoid marketing fluff like "Unlock," "Empower," "Leverage."
2. **CONTRASTIVE REWRITE**: If feedback exists, you must look at your old draft and physically REMOVE the flagged sentence.
3. **TECHNICAL DEPTH**: Use the RAG facts provided. Do not invent features.
4. **HUMAN TEXTURE**: Write like a human professional having a coffee, not a computer filling a form.

**WALL OF SHAME (DO NOT WRITE LIKE THIS):**
- ❌ BAD: "Unlock your potential with our platform."
- ❌ BAD: "Leverage our insights to supercharge your growth."
- ❌ BAD: "Empowering your business to reach new heights."

**WALL OF FAME (WRITE LIKE THIS):**
- ✅ GOOD: "Most teams waste 10 hours a week on manual data entry. We built this to solve that."
- ✅ GOOD: "Salesforce for small business doesn't need to be complex. Here's a 14-day path to get started."

**CRITICAL RULES:**
- NO BOLDING (**), NO MARKDOWN.
- NO BULLET POINTS (- or *). Use full paragraphs.
- Be concise. Respect the intelligence of {target_audience}."""


CHANNEL_INSTRUCTIONS = {
    "LinkedIn": (
        "Write a LinkedIn post of exactly 250-300 words. "
        "One paragraph break maximum — this is a post, not an article. "
        "Open with the hook from the strategy — do not bury the lead. "
        "Write from a position of expertise, not enthusiasm. "
        "End with the CTA on its own line, no exclamation mark."
    ),
    "Instagram": (
        "Write an Instagram caption of 3-5 sentences maximum. "
        "The first sentence must stop the scroll — direct, specific, surprising. "
        "No line can start with a dash, bullet, or hyphen. "
        "Write conversationally — like a person, not a brand account. "
        "Add exactly 5 relevant hashtags on a new line. Format: #tag1 #tag2 #tag3 #tag4 #tag5"
    ),
    "YouTube": (
        "Write in this exact format:\n\n"
        "Title: [video title — maximum 70 characters, keyword-rich and click-worthy]\n\n"
        "Description:\n"
        "[Paragraph 1 — exactly 2-3 sentences. Hook the viewer immediately. "
        "State exactly what they will learn or get from this video. "
        "This paragraph appears in search results — make it count.]\n\n"
        "[Paragraph 2 — exactly 3-4 sentences. Deliver the substance. "
        "What specific value, insight, or information does this video contain? "
        "Be concrete, not vague.]\n\n"
        "[Paragraph 3 — exactly 2-3 sentences. CTA and context. "
        "Tell them what to do next. Keep it natural, not pushy.]\n\n"
        "Tags: [10-15 relevant tags separated by commas — mix broad and specific]\n\n"
        "IMPORTANT: The description must have EXACTLY 3 paragraphs separated by blank lines. "
        "Not 2, not 4. Exactly 3."
    ),
    "Google Ads": (
        "Write in this exact format — respect character limits strictly:\n"
        "Headline 1: [maximum 30 characters — lead with primary keyword or benefit]\n"
        "Headline 2: [maximum 30 characters — differentiation or secondary benefit]\n"
        "Headline 3: [maximum 30 characters — CTA or brand name]\n"
        "Description 1: [maximum 90 characters — complete sentence, primary benefit]\n"
        "Description 2: [maximum 90 characters — complete sentence, proof point or urgency]\n\n"
        "Count every character including spaces. If you exceed a limit, shorten it."
    ),
}


def _parse_channel_feedback(evaluation_feedback: str, channel_name: str) -> dict:
    """
    Parse the evaluation feedback string and extract structured components
    for a specific channel.

    Input format:
        "LinkedIn: PASS"
        "Instagram: FAIL — Rule: Tone rules. Problem: 'Stop wasting...'. Fix: 'Maximize...'"
        "Google Ad: PASS"

    Returns a dict with keys: rule, problem, fix (all strings, empty if PASS).
    """
    if not evaluation_feedback:
        return {}

    # Standardiz names (Google Ads vs Google Ad)
    search_prefixes = [channel_name.lower().rstrip("s"), channel_name.lower()]

    # We need to find the block for this channel in a multi-line string
    lines = evaluation_feedback.split("\n")
    found_block = False
    block_lines = []

    for line in lines:
        if any(line.lower().startswith(p + ":") for p in search_prefixes):
            if "pass" in line.lower(): return {} # Already perfect
            found_block = True
            block_lines.append(line)
            continue
        
        if found_block:
            if ":" in line and any(line.lower().split(":")[0].strip() in ["linkedin","instagram","youtube","google ad","google ads"] for p in ["dummy"]):
                break # Hit next channel block
            block_lines.append(line)

    if not found_block: return {}
    
    full_text = " ".join(block_lines)
    result = {"rule": "", "problem": "", "fix": ""}
    
    if "Core Issue:" in full_text: result["rule"] = full_text.split("Core Issue:")[1].split("-")[0].strip()
    if "Exact Problem:" in full_text: result["problem"] = full_text.split("Exact Problem:")[1].split("-")[0].strip()
    if "Concrete Step:" in full_text: result["fix"] = full_text.split("Concrete Step:")[1].strip()

    return result

def _build_channel_prompt(
    channel_name: str,
    brand_guidelines: dict,
    channel_strategy: dict,
    channel_instructions: str,
    feedback: dict,
    previous_draft: str = ""
) -> str:
    """
    Build the full prompt for one channel.
    When feedback is present, the previous draft is shown AS A WARNING.
    """
    feedback_section = ""
    if feedback and (feedback.get("problem") or feedback.get("rule")):
        rule    = feedback.get("rule", "")
        problem = feedback.get("problem", "")
        fix     = feedback.get("fix", "")
        
        feedback_section = f"""
🚨 MANDATORY REWRITE — THE REVIEWER REJECTED YOUR PREVIOUS WORK:

YOUR PREVIOUS REJECTED VERSION:
---
{previous_draft[:1000]}
---

MANDATORY ACTION PLAN:
- ISSUE: {rule}
- MISTAKE FOUND: {problem}
- REQUIRED FIX: {fix}

DIRECTIONS:
1. Identify the exact sentence with the problem above.
2. DELETE IT. DO NOT PARAPHRASE IT. DELETE IT.
3. Replace it with the new fix. 
4. DO NOT reuse any phrase that the reviewer flagged.
"""


    return f"""Brand guidelines:
- Tone rules: {', '.join(brand_guidelines.get('tone_rules', []))}
- Content pillars: {', '.join(brand_guidelines.get('content_pillars', []))}
- Forbidden phrases: {', '.join(brand_guidelines.get('forbidden_phrases', []))}
- CTA style: {brand_guidelines.get('cta_style', '')}
- Brand voice: {brand_guidelines.get('brand_voice_summary', '')}
- Marketing context: {brand_guidelines.get('marketing_context_summary', '')}
- Differentiation: {', '.join(brand_guidelines.get('differentiation_angles', []))}

Strategy for {channel_name}:
- Angle: {channel_strategy.get('angle', '')}
- Hook: {channel_strategy.get('hook', '')}
- Key message: {channel_strategy.get('key_message', '')}
- CTA: {channel_strategy.get('cta', '')}
{feedback_section}
{channel_instructions}

Write the {channel_name} content now. Do not explain your choices. Just write the content."""


def content_writer(state: dict) -> dict:
    """
    LANGGRAPH NODE — Agent 3: Content Writer

    Reads from State:
        - brand_guidelines, content_strategy, evaluation_feedback,
          iteration_count, selected_channels

    Writes to State:
        - content_drafts (only for selected channels)
        - iteration_count (incremented)
    """
    iteration     = state.get("iteration_count", 0)
    feedback_raw  = state.get("evaluation_feedback") or ""
    human_feedback_raw = state.get("human_feedback") or ""
    selected      = state.get("selected_channels") or list(ALL_CHANNELS.values())

    print(f"[Agent 3] Running Content Writer (iteration {iteration + 1})...")

    approved_channels = []
    hf_map = {}
    if human_feedback_raw.strip().startswith("{"):
        import json
        try:
            hf_data = json.loads(human_feedback_raw)
            approved_channels = [ALL_CHANNELS.get(k, k) for k in hf_data.get("approved", [])]
            # Convert raw keys (like "LinkedIn") to internal keys (linkedin)
            for k, v in hf_data.get("feedback", {}).items():
                 # Handle both internal and UI keys just in case
                 if k in ALL_CHANNELS.values():
                     hf_map[k] = v
                 else:
                     hf_map[ALL_CHANNELS.get(k, k)] = v
        except Exception:
            pass

    if feedback_raw or human_feedback_raw:
        print(f"[Agent 3] Rewriting with parsed structured feedback/expert directives...")

    brand_guidelines = state.get("brand_guidelines", {})
    content_strategy = state.get("content_strategy", {})

    drafts = {}

    for display_name, key in ALL_CHANNELS.items():
        if key not in selected:
            continue  # Skip channels not requested by user

        prev_draft = (state.get("content_drafts") or {}).get(key, "")

        if key in approved_channels:
            print(f"[Agent 3]   Skipping {display_name} (Approved by Expert)")
            drafts[key] = prev_draft
            continue

        channel_strategy = content_strategy.get(key, {})
        feedback         = _parse_channel_feedback(feedback_raw, display_name)

        if feedback_raw and not feedback:
            # The channel was evaluated in the previous iteration and it PASSED.
            # Do not rewrite it; lock the AI success.
            print(f"[Agent 3]   Skipping {display_name} (Passed AI Evaluation)")
            drafts[key] = prev_draft
            continue

        prompt = _build_channel_prompt(
            channel_name=display_name,
            brand_guidelines=brand_guidelines,
            channel_strategy=channel_strategy,
            channel_instructions=CHANNEL_INSTRUCTIONS[display_name],
            feedback=feedback,
            previous_draft=prev_draft,
        )

        # Build a dynamic 'Brand Bible' system prompt
        url      = state.get("url", "the website")
        brief    = state.get("brief", {})
        audience = brief.get("target_audience", "a professional audience")
        goal     = brief.get("campaign_goal", "drive interest")

        # 🚩 HITL: Check for expert human feedback in the state specifically for this channel
        ch_human_feedback = hf_map.get(key, "")
        if not ch_human_feedback and not human_feedback_raw.strip().startswith("{"):
            ch_human_feedback = human_feedback_raw

        sys_prompt = _build_system_prompt(url, audience, goal, brand_guidelines, ch_human_feedback)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.1, # ⚡️ LIGHTNING ACCURACY: Drop creativity to enforce strict compliance.
        )

        drafts[key] = response.choices[0].message.content.strip()
        print(f"[Agent 3]   {display_name} written ({len(drafts[key])} chars)")

    return {
        "content_drafts": drafts,
        "iteration_count": iteration + 1,
    }

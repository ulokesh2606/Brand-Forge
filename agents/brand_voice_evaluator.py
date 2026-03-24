"""
agents/brand_voice_evaluator.py — Agent 4

Evaluates content for the selected channels only.
Returns per-channel feedback with exact problem + fix so Agent 3
can apply mandatory structured corrections on retry.
"""

import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

ALL_CHANNELS = {
    "linkedin":  ("LinkedIn",   "LinkedIn"),
    "instagram": ("Instagram",  "Instagram"),
    "youtube":   ("YouTube",    "YouTube"),
    "google_ad": ("Google Ad",  "Google Ads"),
}

SYSTEM_PROMPT = """You are a meticulous brand compliance reviewer evaluating marketing content \
for LinkedIn, Instagram, YouTube, and Google Ads.

You check for brand voice violations, AI-tell artifacts, formatting errors, and \
channel-specific requirements. You give specific, actionable feedback — quoting the \
exact offending text and providing a concrete rewrite instruction.

Return ONLY valid JSON. No preamble, no markdown."""


def _build_evaluation_prompt(content_drafts: dict, brand_guidelines: dict, selected_channels: list) -> str:
    """Build the evaluation prompt for only the selected channels."""

    channel_blocks = []
    channel_checks = []
    channel_json_fields = []

    for key in selected_channels:
        if key not in ALL_CHANNELS:
            continue
        label, display = ALL_CHANNELS[key]
        content = content_drafts.get(key, "(not generated)")
        channel_blocks.append(f"{label.upper()}:\n{content}")

    # Checks only for selected channels
    if "linkedin" in selected_channels:
        channel_checks.append("LinkedIn: Is it 250-300 words? One paragraph break max? Reads like a post not an article?")
    if "instagram" in selected_channels:
        channel_checks.append("Instagram: Is it 3-5 sentences max? Exactly 5 hashtags? No line starting with dash?")
    if "youtube" in selected_channels:
        channel_checks.append("YouTube: Title under 70 characters? Description has EXACTLY 3 paragraphs? Tags present (10+ comma-separated)? No markdown in description?")
    if "google_ad" in selected_channels:
        channel_checks.append("Google Ad: Headline 1-3 each under 30 chars? Both descriptions under 90 chars?")

    # JSON schema only for selected channels
    for key in selected_channels:
        if key not in ALL_CHANNELS:
            continue
        channel_json_fields.append(f"""  "{key}": {{
    "status": "PASS or FAIL",
    "which_rule_violated": "name the rule if FAIL, null if PASS",
    "exact_problem": "quote the exact offending text if FAIL, null if PASS",
    "concrete_recommendation": "write the specific replacement text if FAIL, null if PASS"
  }}""")

    # Channels not selected → auto-PASS (not evaluated)
    for key in ALL_CHANNELS:
        if key not in selected_channels:
            channel_json_fields.append(f"""  "{key}": {{
    "status": "PASS",
    "which_rule_violated": null,
    "exact_problem": null,
    "concrete_recommendation": null
  }}""")

    return f"""Brand guidelines to enforce:
Tone rules: {json.dumps(brand_guidelines.get('tone_rules', []))}
Forbidden phrases: {json.dumps(brand_guidelines.get('forbidden_phrases', []))}
CTA style: {brand_guidelines.get('cta_style', '')}
Brand voice: {brand_guidelines.get('brand_voice_summary', '')}

CONTENT TO REVIEW (these channels only — {', '.join(selected_channels)}):

{chr(10).join(channel_blocks)}

REVIEW CRITERIA (STRICT COMPLIANCE):
1. **Tone Accuracy**: Does the copy follow the adjectives in the tone rules? (FAIL if inconsistent with brand voice).
2. **Formatting**: MANDATORY FAIL if you see markdown (** or ##), bullet points, or lines starting with dashes (-).
3. **AI-Tell Detection**: FAIL if AI-tell phrases are present: "In conclusion", "Unlock", "Dive into", "Leverage", "Empower", "Elevate your", "Transform", "Supercharge". (Remove these on rewrite).
4. **Channel Layout**: MUST respect the specific character limits and paragraph rules exactly.

Return this exact JSON:
{{
{','.join(chr(10) + f for f in channel_json_fields)}
,
  "overall_status": "PASS only if all channels are 100% compliant, else FAIL"
}}

When a channel fails, provide a CONCRETE ACTION PLAN in 'concrete_recommendation': e.g. "REMOVE the word 'Leverage' and REPLACE with 'Utilize' in sentence 2."
"""


def _format_feedback_string(evaluation_result: dict, selected_channels: list) -> str:
    """
    Convert evaluation JSON into a structured feedback string for Agent 3.
    Format: one line per channel, parsed by content_writer._parse_channel_feedback().
    """
    lines = []
    key_to_label = {
        "linkedin":  "LinkedIn",
        "instagram": "Instagram",
        "youtube":   "YouTube",
        "google_ad": "Google Ad",
    }
    for key in selected_channels:
        ch     = evaluation_result.get(key, {})
        label  = key_to_label.get(key, key)
        status = ch.get("status", "PASS")

        if status == "PASS":
            lines.append(f"{label}: PASS")
        else:
            lines.append(
                f"{label}: FAIL | 🚨 ACTION PLAN:\n"
                f"  - Core Issue: {ch.get('which_rule_violated', 'Style deviation')}\n"
                f"  - Exact Problem: {ch.get('exact_problem', 'Found forbidden phrase')}\n"
                f"  - Concrete Step: {ch.get('concrete_recommendation', 'Rewrite to sound more human.')}"
            )

    return "\n".join(lines)


def brand_voice_evaluator(state: dict) -> dict:
    """
    LANGGRAPH NODE — Agent 4: Brand Voice Evaluator

    Reads from State:
        - content_drafts, brand_guidelines, iteration_count, selected_channels,
          max_iterations

    Writes to State:
        - evaluation_result
        - evaluation_feedback (structured feedback for Agent 3's next rewrite)
        - final_content (set when max AI iterations reached → triggers END → human review)

    NEW FLOW:
        - Every iteration: evaluate → produce structured feedback → feed back to Agent 3
        - After max_iterations: set final_content → graph ends → human reviews in UI
        - Human can approve (save) or provide feedback (priority re-run)
        - No more PASS/FAIL hard-stop; quality improves via progressive AI rewrites
    """
    print("[Agent 4] Running Brand Voice Evaluator...")

    content_drafts   = state.get("content_drafts", {})
    brand_guidelines = state.get("brand_guidelines", {})
    iteration_count  = state.get("iteration_count", 0)
    selected         = state.get("selected_channels") or ["linkedin", "instagram", "youtube", "google_ad"]
    max_iterations   = state.get("max_iterations", 3)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": _build_evaluation_prompt(content_drafts, brand_guidelines, selected)},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )

    evaluation_result = json.loads(response.choices[0].message.content)

    # 🚩 HITL: Auto-approve any channels explicitly marked as approved by the human expert
    human_feedback_raw = state.get("human_feedback") or ""
    if human_feedback_raw.strip().startswith("{"):
        try:
            hf_data = json.loads(human_feedback_raw)
            approved_ui_keys = hf_data.get("approved", [])
            
            # Map UI keys ("linkedin", "youtube") to evaluator dict keys 
            # The evaluator uses exactly what's in 'selected', e.g. "linkedin"
            for ui_key in approved_ui_keys:
                if ui_key in evaluation_result:
                    evaluation_result[ui_key] = {
                        "status": "PASS",
                        "exact_problem": "",
                        "which_rule_violated": "Human Expert Override",
                        "concrete_recommendation": ""
                    }
        except Exception:
            pass

    # Normalise overall_status
    overall_status = evaluation_result.get("overall_status", "FAIL")
    if "PASS" in str(overall_status).upper() and "FAIL" not in str(overall_status).upper():
        overall_status = "PASS"
    else:
        all_pass = all(
            evaluation_result.get(k, {}).get("status", "FAIL") == "PASS"
            for k in selected
        )
        overall_status = "PASS" if all_pass else "FAIL"

    evaluation_result["overall_status"] = overall_status
    print(f"[Agent 4] AI Review: {overall_status} at iteration {iteration_count}")

    # Always generate structured feedback for Agent 3's next rewrite
    feedback_string = _format_feedback_string(evaluation_result, selected)

    # When max AI iterations reached OR everything passed → finalize for human review
    if iteration_count >= max_iterations or overall_status == "PASS":
        stop_reason = f"Max AI iterations ({max_iterations}) reached" if iteration_count >= max_iterations else "All channels passed"
        print(f"[Agent 4] {stop_reason} → handing off to human review.")
        return {
            "evaluation_result":   evaluation_result,
            "evaluation_feedback": feedback_string,   # Kept for UI transparency
            "final_content":       content_drafts,    # Signals router → END → human reviews
        }

    # Still within AI loop → send feedback to Agent 3 for another rewrite pass
    print(f"[Agent 4] Sending feedback to Agent 3 (iteration {iteration_count + 1} upcoming):\n{feedback_string}")
    return {
        "evaluation_result":   evaluation_result,
        "evaluation_feedback": feedback_string,
        "final_content":       None,   # Keep looping
    }

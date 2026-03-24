"""
agents/content_strategist.py — Agent 2

Decides the angle, hook, and CTA for each of the 4 channels
before any writing happens. Now includes YouTube strategy.

YouTube is fundamentally different from other channels:
- People search YouTube with intent (like Google) — keywords matter
- Titles must be click-worthy AND keyword-rich
- Descriptions serve both human readers and YouTube's algorithm
- Tags tell YouTube what the video is about for recommendation

The strategist decides the YouTube angle just like it decides the
LinkedIn angle — what hook, what key message, what makes someone
click on this video over the 10 others on the same topic.
"""

import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


SYSTEM_PROMPT = """You are a senior content strategist. You decide the strategic approach \
for marketing content across LinkedIn, Instagram, YouTube, and Google Ads BEFORE any writing happens.

Your decisions directly instruct the content writer. Be specific and channel-aware.
Each channel needs a completely different strategic angle — not the same message reformatted.

Also factor in the brand's existing marketing context: what angles they've used, what's worked,
and how to differentiate from competitors. Build on what's working, avoid what hasn't.

Return ONLY valid JSON. No preamble, no markdown."""


def _build_user_prompt(brand_guidelines: dict, brief: dict) -> str:
    return f"""Brand guidelines:
{json.dumps(brand_guidelines, indent=2)}

Campaign:
- Goal: {brief.get("campaign_goal")}
- Target audience: {brief.get("target_audience")}
- What has worked before: {brief.get("what_has_worked")}
- What has NOT worked: {brief.get("what_hasnt_worked")}
- Competitors to differentiate from: {", ".join(brief.get("competitors", []))}

Define the content strategy for each channel. Each must have a DIFFERENT angle:

{{
  "linkedin": {{
    "angle": "thought leadership / insight angle — build on what has worked for this brand",
    "hook": "the exact opening concept or line to lead with",
    "key_message": "the one thing the reader must take away",
    "cta": "soft, value-first CTA appropriate for LinkedIn"
  }},
  "instagram": {{
    "angle": "visual-first, punchy angle — different from LinkedIn, more personal",
    "hook": "one punchy opening line that stops the scroll",
    "key_message": "core message in 2-3 short sentences",
    "cta": "casual, low-friction instagram CTA"
  }},
  "youtube": {{
    "angle": "search intent angle — what would someone type into YouTube to find this?",
    "hook": "the video title concept — must be click-worthy AND keyword-rich",
    "key_message": "what value the viewer gets from watching — the promise of the video",
    "cta": "what to do after watching — subscribe, try, visit link"
  }},
  "google_ad": {{
    "angle": "search keyword angle — match high-intent search terms",
    "hook": "primary keyword and benefit for Headline 1",
    "key_message": "main benefit and differentiator for descriptions",
    "cta": "action-oriented ad CTA"
  }}
}}

Channel notes:
LinkedIn: professional, data-led, story or insight. What has worked for this brand historically?
Instagram: relatable, visual, emotional. Shorter and punchier than LinkedIn.
YouTube: title must work as a search query. Description must serve both algorithm and humans.
Google Ad: strict character limits. Benefit in first 3 words. Differentiate from competitors."""


def content_strategist(state: dict) -> dict:
    """
    LANGGRAPH NODE — Agent 2: Content Strategist

    Reads from State:
        - brand_guidelines (includes marketing_context_summary now)
        - brief (includes what has/hasn't worked)

    Writes to State:
        - content_strategy (now includes youtube instead of email)
    """
    print("[Agent 2] Running Content Strategist...")

    brand_guidelines = state.get("brand_guidelines", {})
    brief = state.get("brief", {})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(brand_guidelines, brief)}
        ],
        response_format={"type": "json_object"},
        temperature=0.4
    )

    content_strategy = json.loads(response.choices[0].message.content)
    print(f"[Agent 2] Strategy defined. YouTube angle: {content_strategy.get('youtube', {}).get('angle', '')[:60]}...")

    return {"content_strategy": content_strategy}


if __name__ == "__main__":
    test_state = {
        "brand_guidelines": {
            "tone_rules": ["lead with data", "never use exclamation marks", "second person"],
            "content_pillars": ["efficiency", "science-backed fitness", "professional results"],
            "forbidden_phrases": ["crush it", "unlock your potential", "game-changer"],
            "cta_style": "soft and value-first",
            "brand_voice_summary": "Direct, data-led. Respects the reader's intelligence.",
            "marketing_context_summary": "Data-led LinkedIn posts outperform motivational content 3x. Competitor Peloton owns the 'aspirational fitness' space — ZenFit should own 'efficient, evidence-based'.",
            "differentiation_angles": ["Peloton sells inspiration, ZenFit sells efficiency", "Whoop tracks data, ZenFit acts on it"]
        },
        "brief": {
            "campaign_goal": "drive free trial signups for the AI workout planner",
            "target_audience": "busy working professionals aged 25-40",
            "tone_keywords": ["science-backed", "no-fluff"],
            "what_has_worked": "Posts with specific stats get 3x engagement",
            "what_hasnt_worked": "Generic motivational posts",
            "competitors": ["Peloton", "Whoop"]
        }
    }

    result = content_strategist(test_state)
    print("\n--- Content Strategy ---")
    print(json.dumps(result["content_strategy"], indent=2))

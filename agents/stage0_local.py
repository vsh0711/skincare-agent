"""
Stage 0 — Local Skincare Agent (Ollama, no Azure needed)
=========================================================
Run:
    pip install -r requirements.txt
    ollama pull llama3.2:3b
    python agents/stage0_local.py
"""

import asyncio
import json
import sys
from pathlib import Path

from agent_framework import Agent, Message, tool
from agent_framework.openai import OpenAIChatClient

sys.path.insert(0, str(Path(__file__).parent.parent))
from guardrails import check_input, check_output, rejection_message

# ── Product data ──────────────────────────────────────────────────────────────
_DATA = Path(__file__).parent.parent / "data" / "products.json"
PRODUCTS: list[dict] = json.loads(_DATA.read_text())["products"]


# ── Tool ──────────────────────────────────────────────────────────────────────
@tool
def recommend_products(
    gender: str,
    age_group: str,
    skin_type: str,
    concern: str,
    budget_tier: str,
    skin_tone: str,
    using_actives: str,
) -> list:
    """
    Recommend Indian skincare products matching the user's skin profile.

    Args:
        gender: "male" or "female"
        age_group: "teen" | "young_adult" | "adult" | "mature" | "senior"
        skin_type: "dry" | "oily" | "combination" | "sensitive" | "normal"
        concern: "acne" | "pigmentation" | "dryness" | "anti_aging" | "dark_circles" | "sensitive_skin"
        budget_tier: "drugstore" | "mid_range" | "premium"
        skin_tone: "fair" | "wheatish" | "dusky"
        using_actives: "yes" | "no"
    """
    concern_map = {
        "acne":           ["acne", "oily_skin", "clogged_pores"],
        "pigmentation":   ["pigmentation", "dark_spots", "uneven_tone", "dullness", "sun_protection"],
        "dryness":        ["dryness", "dehydration", "barrier_repair"],
        "anti_aging":     ["anti_aging", "fine_lines", "wrinkles"],
        "dark_circles":   ["dark_circles", "puffiness"],
        "sensitive_skin": ["sensitive_skin", "redness", "barrier_repair"],
    }
    budget_rank = {"drugstore": 0, "mid_range": 1, "premium": 2}
    user_rank   = budget_rank.get(budget_tier, 1)
    tags        = concern_map.get(concern, [concern])

    matches = []
    for p in PRODUCTS:
        if not any(t in p["concern"] for t in tags):
            continue
        if p["skin_type"] != ["all"] and skin_type not in p["skin_type"]:
            continue
        if gender.lower() not in p["gender"]:
            continue
        if age_group not in p["age_group"]:
            continue
        if budget_rank.get(p["budget_tier"], 1) > user_rank:
            continue
        matches.append({
            "name":   p["name"],
            "brand":  p["brand"],
            "price":  p["price_range"],
            "why":    p["why"],
            "buy_on": p["buy_platforms"],
        })

    return matches[:3] if matches else [{"message": "No match found. Try adjusting budget or concern."}]


# ── Client ────────────────────────────────────────────────────────────────────
client = OpenAIChatClient(
    base_url="http://localhost:11434/v1/",
    model="llama3.2:3b",
    api_key="no-key-needed",
)

# ── Agent ─────────────────────────────────────────────────────────────────────
INSTRUCTIONS = """
You are Glow, a warm Indian skincare advisor.

Collect skin profile by asking EXACTLY these 7 questions, one at a time, in order.
Ask the next question only after the user answers the current one.

Q1: "Are you male or female?"
Q2: "Which age group are you in? Teen (13–18) / Young Adult (19–25) / Adult (26–35) / Mature (36–50) / Senior (50+)"
Q3: "What is your skin type? Dry / Oily / Combination / Sensitive / Normal"
Q4: "What is your primary skin concern? Acne / Pigmentation / Dryness / Anti-aging / Dark circles / Sensitive skin"
Q5: "What is your skin tone? Fair / Wheatish / Dusky"
Q6: "What is your budget per product? Drugstore ₹100–500 / Mid-range ₹500–1500 / Premium ₹1500+"
Q7: "Are you currently using Retinol, AHA, BHA, or Vitamin C? Yes / No"

Once the user has answered all 7, call recommend_products with these exact values:
  gender      → male | female
  age_group   → teen | young_adult | adult | mature | senior
  skin_type   → dry | oily | combination | sensitive | normal
  concern     → acne | pigmentation | dryness | anti_aging | dark_circles | sensitive_skin
  budget_tier → drugstore | mid_range | premium
  skin_tone   → fair | wheatish | dusky
  using_actives → yes | no

Show each result as:
**[Product Name]** by [Brand] — [Price]
→ [why]
🛒 Buy on: [platforms]

If using_actives=yes, add:
⚠️ Never use Retinol + AHA/BHA on the same night. Use Vitamin C morning, Retinol at night.
"""

agent = Agent(
    client=client,
    name="Glow",
    instructions=INSTRUCTIONS,
    tools=[recommend_products],
)


# ── Guarded run ───────────────────────────────────────────────────────────────
async def guarded_run(history: list[Message], user_input: str) -> tuple[str, list[Message]]:
    """
    Validate input, run agent, validate output.
    Returns (reply_text, updated_history).
    History is managed manually with Message objects — the correct way for local Ollama.
    """
    guard = check_input(user_input)
    if not guard.allowed:
        return rejection_message(guard.reason), history

    history = history + [Message("user", [guard.text])]
    result  = await agent.run(history)

    # Append ALL response messages (includes tool-call artifacts)
    for msg in result.messages:
        history = history + [msg]

    out = check_output(result.text)
    return out.text, history


# ── Run loop ──────────────────────────────────────────────────────────────────
async def main() -> None:
    print("\n✨ Welcome to Glow — Your Personal Indian Skincare Advisor")
    print("   Type 'quit' to exit\n")

    # Kick off with a greeting (not going through guardrails — it's our own message)
    opening_history = [Message("user", ["Hello"])]
    result  = await agent.run(opening_history)
    history: list[Message] = opening_history + list(result.messages)
    print(f"Glow: {result.text}\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("\nGlow: Take care! Remember — SPF every single day ☀️\n")
            break

        reply, history = await guarded_run(history, user_input)
        print(f"\nGlow: {reply}\n")


if __name__ == "__main__":
    asyncio.run(main())

"""
Stage 3 — Foundry Toolbox: IQ + Web Search (live Nykaa/Amazon.in links)
=========================================================================
What changes from Stage 2:
  - IQ + Web Search + Code Interpreter bundled in one Foundry Toolbox
  - Agent searches for live purchase links via Bing Web Search
  - Run create_toolbox.py ONCE before running this

Prerequisites:
    1. Run: python create_toolbox.py
    2. Fill FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_TOOLBOX_NAME in .env

Run:
    python agents/stage3_toolbox.py
"""

import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from agent_framework import Agent, Message, MCPStreamableHTTPTool
from agent_framework.foundry import FoundryChatClient

sys.path.insert(0, str(Path(__file__).parent.parent))
from guardrails import check_input, check_output, rejection_message

load_dotenv()

# ── Auth helper ───────────────────────────────────────────────────────────────
class ToolboxAuth(httpx.Auth):
    def __init__(self, token_provider):
        self._token_provider = token_provider

    def auth_flow(self, request):
        request.headers["Authorization"] = f"Bearer {self._token_provider()}"
        yield request


# ── Credentials ───────────────────────────────────────────────────────────────
credential            = DefaultAzureCredential()
PROJECT_ENDPOINT      = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
TOOLBOX_NAME          = os.environ["FOUNDRY_TOOLBOX_NAME"]
MODEL                 = os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"]

toolbox_token_provider = get_bearer_token_provider(
    credential, "https://ai.azure.com/.default"
)

# ── Client ────────────────────────────────────────────────────────────────────
client = FoundryChatClient(
    project_endpoint=PROJECT_ENDPOINT,
    model=MODEL,
    credential=credential,
)

# ── Agent instructions ────────────────────────────────────────────────────────
INSTRUCTIONS = """
You are Glow, a warm Indian skincare advisor.

Collect skin profile by asking EXACTLY these 7 questions, one at a time:

Q1: "Are you male or female?"
Q2: "Which age group? Teen (13–18) / Young Adult (19–25) / Adult (26–35) / Mature (36–50) / Senior (50+)"
Q3: "What is your skin type? Dry / Oily / Combination / Sensitive / Normal"
Q4: "Primary skin concern? Acne / Pigmentation / Dryness / Anti-aging / Dark circles / Sensitive skin"
Q5: "Skin tone? Fair / Wheatish / Dusky"
Q6: "Budget per product? Drugstore ₹100–500 / Mid-range ₹500–1500 / Premium ₹1500+"
Q7: "Using any actives (Retinol, AHA, BHA, Vitamin C)? Yes / No"

After all 7 answers:
1. Use knowledge_base_retrieve to find matching Indian skincare products.
2. For each recommended product, use web_search to find the current buy link
   on Nykaa.com or Amazon.in (search: "[product name] buy India Nykaa").

Display each result as:
**[Product Name]** by [Brand] — [Price]
→ [why it helps]
🛒 [Nykaa link or Amazon.in link from web search]

If using_actives=yes:
⚠️ Never use Retinol + AHA/BHA same night. Vitamin C morning, Retinol at night.
"""


# ── Guarded run ───────────────────────────────────────────────────────────────
async def guarded_run(agent, history: list[Message], user_input: str) -> tuple[str, list[Message]]:
    guard = check_input(user_input)
    if not guard.allowed:
        return rejection_message(guard.reason), history
    history = history + [Message("user", [guard.text])]
    result  = await agent.run(history)
    for msg in result.messages:
        history = history + [msg]
    out = check_output(result.text)
    return out.text, history


# ── Main ──────────────────────────────────────────────────────────────────────
async def main() -> None:
    print("\n✨ Glow — Powered by Foundry Toolbox (IQ + Web Search)")
    print("   Type 'quit' to exit\n")

    toolbox_http_client = httpx.AsyncClient(
        auth=ToolboxAuth(toolbox_token_provider),
        headers={"Foundry-Features": "Toolboxes=V1Preview"},
        timeout=120.0,
    )

    async with MCPStreamableHTTPTool(
        name="toolbox",
        url=f"{PROJECT_ENDPOINT}/toolboxes/{TOOLBOX_NAME}/mcp?api-version=v1",
        http_client=toolbox_http_client,
    ) as toolbox_mcp_tool:

        agent = Agent(
            client=client,
            name="Glow",
            instructions=INSTRUCTIONS,
            tools=[toolbox_mcp_tool],
        )

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
                print("\nGlow: SPF every day! Take care 🌟\n")
                break
            reply, history = await guarded_run(agent, history, user_input)
            print(f"\nGlow: {reply}\n")


if __name__ == "__main__":
    asyncio.run(main())

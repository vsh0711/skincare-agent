"""
Stage 2 — Add Foundry IQ (Azure AI Search knowledge base) as MCP tool
=======================================================================
What changes from Stage 1:
  - Product KB is uploaded to Azure AI Search
  - Agent queries it via MCP instead of local JSON
  - Local recommend_products tool kept as fallback

Prerequisites:
    1. Azure AI Search resource (free F0 tier is fine)
    2. Create knowledge base in Foundry → upload data/products.json
    3. Fill AZURE_AI_SEARCH_* in .env

Run:
    python agents/stage2_foundry_iq.py
"""

import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from agent_framework import Agent, Message, MCPStreamableHTTPTool, tool
from agent_framework.openai import OpenAIChatClient

sys.path.insert(0, str(Path(__file__).parent.parent))
from guardrails import check_input, check_output, rejection_message

load_dotenv()

# ── Auth helper ───────────────────────────────────────────────────────────────
class BearerAuth(httpx.Auth):
    def __init__(self, token_provider):
        self._token_provider = token_provider

    def auth_flow(self, request):
        request.headers["Authorization"] = f"Bearer {self._token_provider()}"
        yield request


# ── Credentials ───────────────────────────────────────────────────────────────
credential = DefaultAzureCredential()

_sync_oai_token = get_bearer_token_provider(
    credential, "https://cognitiveservices.azure.com/.default"
)
search_token_provider = get_bearer_token_provider(
    credential, "https://search.azure.com/.default"
)

async def oai_token_provider() -> str:
    return _sync_oai_token()

# ── Foundry IQ MCP URL ────────────────────────────────────────────────────────
SEARCH_ENDPOINT = os.environ["AZURE_AI_SEARCH_SERVICE_ENDPOINT"]
KB_NAME         = os.environ["AZURE_AI_SEARCH_KNOWLEDGE_BASE_NAME"]

mcp_url = (
    f"{SEARCH_ENDPOINT}/knowledgebases/"
    f"{KB_NAME}/mcp?api-version=2026-05-01-preview"
)

# ── Client ────────────────────────────────────────────────────────────────────
client = OpenAIChatClient(
    base_url=f"{os.environ['AZURE_OPENAI_ENDPOINT']}/openai/v1/",
    api_key=oai_token_provider,
    model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
)

# ── Agent instructions ────────────────────────────────────────────────────────
INSTRUCTIONS = """
You are Glow, a warm and friendly Indian skincare advisor. Talk like a knowledgeable friend, not a form wizard.

## Greeting
Respond to "hi" / "hello" with just a casual, warm opener — no questions yet:
"Hi there! 😊 How's your skin feeling today?"

Let the user speak first. React naturally to what they say.

## Gathering the skin profile
You need to collect 7 things before recommending products. Do it conversationally — weave questions into the flow, ONE at a time. Never list all questions upfront. Never say "I have 7 questions."

The 7 things you need (collect in any natural order):
1. Gender (male / female)
2. Age group (Teen 13–18 / Young Adult 19–25 / Adult 26–35 / Mature 36–50 / Senior 50+)
3. Skin type (Dry / Oily / Combination / Sensitive / Normal)
4. Primary concern (Acne / Pigmentation / Dryness / Anti-aging / Dark circles / Sensitive skin)
5. Skin tone (Fair / Wheatish / Dusky)
6. Budget per product (Drugstore ₹100–500 / Mid-range ₹500–1500 / Premium ₹1500+)
7. Using actives? (Retinol / AHA / BHA / Vitamin C — Yes / No)

If the user already mentioned a concern (e.g. "I have dark circles"), count that as answer to #4 and skip asking it again.

Example natural flow:
User: "I have dark circles, any help?"
Glow: "Dark circles — totally fixable! Let me find the right products for you. Are you male or female?"
[continue naturally]

## Once all 7 are collected
Call knowledge_base_retrieve, then display results as:

**[Product Name]** by [Brand] — [Price]
→ [why it helps their specific concern]
🛒 Buy on: [platforms]

Recommend 2–3 products. End with a warm, encouraging note.

If using_actives=yes:
⚠️ Never use Retinol + AHA/BHA on the same night. Vitamin C in the morning, Retinol at night.
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
    print("\n✨ Glow — Powered by Foundry IQ Knowledge Base")
    print("   Type 'quit' to exit\n")

    search_http_client = httpx.AsyncClient(
        auth=BearerAuth(search_token_provider),
        timeout=30.0,
    )

    async with MCPStreamableHTTPTool(
        name="knowledge-base",
        url=mcp_url,
        http_client=search_http_client,
        allowed_tools=["knowledge_base_retrieve"],
    ) as kb_mcp_tool:

        agent = Agent(
            client=client,
            name="Glow",
            instructions=INSTRUCTIONS,
            tools=[kb_mcp_tool],
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

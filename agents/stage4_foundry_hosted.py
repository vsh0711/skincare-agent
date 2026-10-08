"""
Stage 4 — Host Glow on Foundry Agent Service
=============================================
What changes from Stage 2:
  - Agent wrapped in ResponsesHostServer (HTTP server on port 8088)
  - Uses FoundryChatClient instead of OpenAIChatClient
  - KB MCP tool for product retrieval
  - Full OTel traces in App Insights
  - No interactive run loop — responds to API calls

Local dev:
    azd ai agent run
    azd ai agent invoke --local "Hello, I need skincare advice"

Deploy to Foundry:
    azd auth login
    azd up

Interact after deploy:
    from azure.ai.projects import AIProjectClient
    project = AIProjectClient(endpoint=FOUNDRY_PROJECT_ENDPOINT, credential=DefaultAzureCredential(), allow_preview=True)
    openai_client = project.get_openai_client(agent_name="GlowSkincareAdvisor")
    response = openai_client.responses.create(input="Hello")
    print(response.output_text)
"""

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from agent_framework import Agent, MCPStreamableHTTPTool
from agent_framework.foundry import FoundryChatClient
from agent_framework.observability import enable_instrumentation
from agent_framework_foundry_hosting import ResponsesHostServer

sys.path.insert(0, str(Path(__file__).parent.parent))
from guardrails import check_input, check_output, rejection_message

load_dotenv()

# ── OTel (auto-exports to App Insights when project has App Insights connection)
enable_instrumentation(enable_sensitive_data=False)

# ── Auth ──────────────────────────────────────────────────────────────────────
credential            = DefaultAzureCredential()
PROJECT_ENDPOINT      = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
MODEL                 = os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"]
SEARCH_ENDPOINT       = os.environ["AZURE_AI_SEARCH_SERVICE_ENDPOINT"]
KB_NAME               = os.environ["AZURE_AI_SEARCH_KNOWLEDGE_BASE_NAME"]

search_token_provider = get_bearer_token_provider(
    credential, "https://cognitiveservices.azure.com/.default"
)

class BearerAuth(httpx.Auth):
    def __init__(self, token_provider):
        self._token_provider = token_provider

    def auth_flow(self, request):
        request.headers["Authorization"] = f"Bearer {self._token_provider()}"
        yield request


# ── Client ────────────────────────────────────────────────────────────────────
client = FoundryChatClient(
    project_endpoint=PROJECT_ENDPOINT,
    model=MODEL,
    credential=credential,
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

# ── KB MCP tool ───────────────────────────────────────────────────────────────
kb_http_client = httpx.AsyncClient(
    auth=BearerAuth(search_token_provider),
    timeout=30.0,
)

kb_mcp_tool = MCPStreamableHTTPTool(
    name="knowledge-base",
    url=(
        f"{SEARCH_ENDPOINT}/knowledgebases/"
        f"{KB_NAME}/mcp?api-version=2026-05-01-preview"
    ),
    http_client=kb_http_client,
    allowed_tools=["knowledge_base_retrieve"],
)

# ── Agent ─────────────────────────────────────────────────────────────────────
agent = Agent(
    client=client,
    name="GlowSkincareAdvisor",
    instructions=INSTRUCTIONS,
    tools=[kb_mcp_tool],
)

# ── Host server ───────────────────────────────────────────────────────────────
server = ResponsesHostServer(agent)

if __name__ == "__main__":
    server.run()  # port 8088

# Glow — Indian Skincare Advisor Agent

An AI-powered skincare advisor for Indian skin built on **Microsoft Agent Framework (MAF)** and **Azure AI Foundry**. Glow has a conversational personality — it gathers your skin profile naturally and recommends products from a curated Indian skincare knowledge base.

**Built as a hands-on learning project for Microsoft Foundry Agent hosting**, progressing through four deployment stages from local Ollama to a cloud-hosted Foundry Agent Service.

---

## Architecture

```
User ──► Glow Agent (MAF)
              │
              ├── guardrails.py          (input/output validation)
              ├── recommend_products()   (local JSON tool, Stages 0-1)
              └── MCPStreamableHTTPTool  (Azure AI Search KB via MCP, Stages 2-4)
                        │
                        └── Azure AI Search (serverless SKU)
                                  └── skincare-kb  (products.json indexed)
```

**Key libraries:**
| Library | Role |
|---|---|
| `agent-framework` | Microsoft Agent Framework — `Agent`, `MCPStreamableHTTPTool`, `tool` |
| `agent-framework-foundry-hosting` | `ResponsesHostServer` — wraps agent as HTTP server on port 8088 |
| `azure-identity` | `DefaultAzureCredential`, `get_bearer_token_provider` |
| `httpx` | Async HTTP client for MCP bearer-auth requests |

---

## Deployment Stages

### Stage 0 — Local (Ollama)
Runs fully offline. Uses `llama3.2:3b` via Ollama and a local `recommend_products` Python tool.

```bash
ollama pull llama3.2:3b
python agents/stage0_local.py
```

### Stage 1 — Azure Foundry Models ✅
Swaps Ollama client for `OpenAIChatClient` pointing at an Azure OpenAI deployment via `DefaultAzureCredential`. Same local tool, no KB yet.

```bash
az login
python agents/stage1_foundry_model.py
```

**Key fix:** `get_bearer_token_provider` returns a *sync* callable. `OpenAIChatClient` tries to `await` it → `TypeError: 'str' object can't be awaited`. Fix: wrap in an `async def` that calls the sync provider.

```python
_sync_token = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")
async def _async_token_provider() -> str:
    return _sync_token()
```

### Stage 2 — Foundry IQ (Azure AI Search KB) ✅
Uploads `data/products.json` to Azure AI Foundry as a knowledge base backed by **Azure AI Search (serverless SKU)**. Agent queries it through `MCPStreamableHTTPTool` over the Foundry IQ MCP protocol.

```bash
python agents/stage2_foundry_iq.py
```

**Key issues encountered:**
- KB display name in UI (`skincare-products-kb`) ≠ actual search index name → verified with `az rest` listing `/knowledgebases`
- MCP endpoint required `api-version=2026-05-01-preview` (older versions rejected with "file kind only supported on Serverless search services with api-version 2026-05-01-preview or later")
- Serverless search has `DisableLocalAuth=true` — **API keys are disabled**; only Azure AD bearer tokens work

### Stage 3 — Foundry Toolbox ⛔ Skipped
Toolboxes is a **limited preview** feature. POST to `/toolboxes?api-version=v1` returns `405 Method Not Allowed` on standard accounts. Skipped and went directly to Stage 4 using the KB MCP endpoint directly.

### Stage 4 — Hosted on Foundry Agent Service ✅ (deployed) / ⚠️ KB access issue
Agent is wrapped in `ResponsesHostServer` and deployed via `azd up`. Uses `FoundryChatClient` (Foundry-native client) instead of `OpenAIChatClient`.

```bash
azd up                    # provision + deploy
azd deploy                # redeploy code only
azd ai agent run          # test locally with Foundry env
azd ai agent invoke --local "Hello"
```

---

## Prerequisites

```
Python 3.12+
uv (package manager)
Azure CLI (az)
Azure Developer CLI (azd)
azd extension: azd ai agent
```

Install:
```bash
pip install uv
uv sync
az login
azd auth login
azd extension add ai-agent   # or: azd extension install ai-agent
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```env
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
AZURE_AI_MODEL_DEPLOYMENT_NAME=gpt-4.1-mini

AZURE_AI_SEARCH_SERVICE_ENDPOINT=https://<your-search>.search.windows.net
AZURE_AI_SEARCH_KNOWLEDGE_BASE_NAME=<kb-name>

FOUNDRY_PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
```

For **Stage 4 deployment**, also push vars into the azd environment store (`.env` is not read by `azd up`):

```bash
azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME gpt-4.1-mini
azd env set AZURE_AI_SEARCH_SERVICE_ENDPOINT https://...
azd env set AZURE_AI_SEARCH_KNOWLEDGE_BASE_NAME skincare-kb
azd env set FOUNDRY_PROJECT_ENDPOINT https://...
```

---

## Project Structure

```
skincare-agent/
├── agents/
│   ├── stage0_local.py          # Ollama + local tool
│   ├── stage1_foundry_model.py  # Azure OpenAI + local tool
│   ├── stage2_foundry_iq.py     # Azure OpenAI + KB via MCP
│   ├── stage3_toolbox.py        # (skipped — limited preview)
│   └── stage4_foundry_hosted.py # FoundryChatClient + ResponsesHostServer
├── data/
│   └── products.json            # ~30 curated Indian skincare products
├── guardrails.py                # Input/output validation
├── azure.yaml                   # azd configuration
├── pyproject.toml
├── Dockerfile
└── .env.example
```

---

## Guardrails

`guardrails.py` applies two-layer validation on every turn:

**Input (`check_input`):**
- Length cap (400 chars) — prevents token flooding
- NFKC unicode normalisation — defeats homoglyph bypass tricks
- Regex patterns for prompt injection (`ignore previous instructions`, `jailbreak`, role injection brackets, etc.)
- Off-topic filter (passwords, code writing, political topics)

**Output (`check_output`):**
- Scans for accidental instruction leaks ("my system instructions are…")
- Redacts the offending sentence rather than blocking the whole reply

---

## Conversational Design

Stages 0–1 used a rigid Q&A flow ("Ask Q1, wait for answer, ask Q2…"). Stages 2–4 switched to a natural conversation style based on user feedback:

- Greeting only says *"Hi there! How's your skin feeling today?"* — no immediate questions
- 7 profile items are gathered one at a time, woven into natural conversation
- If the user mentions a concern upfront ("I have dark circles"), that counts and the follow-up question is skipped

---

## Known Issues & Learnings

### 1. `TypeError: 'str' object can't be awaited` (Stage 1)
`get_bearer_token_provider` returns a sync callable. `OpenAIChatClient` `await`s it.
**Fix:** wrap in `async def`.

### 2. KB name mismatch (Stage 2)
Foundry UI shows a display name that differs from the actual Azure AI Search index name.
**Debug:** `az rest --method GET --url "{endpoint}/knowledgebases?api-version=2026-05-01-preview"` to list real names.

### 3. `api-version` too old (Stage 2)
Azure AI Search serverless SKU requires `api-version=2026-05-01-preview` for the `/knowledgebases/{name}/mcp` endpoint.

### 4. `uv sync` fails: package directory not found
Hatchling couldn't find the package because `pyproject.toml` was missing the wheel config.
**Fix:** add `[tool.hatch.build.targets.wheel] packages = ["agents"]`.

### 5. `ValueError: Model is required` on `azd ai agent run`
`${AZURE_AI_MODEL_DEPLOYMENT_NAME}` in `azure.yaml` reads from **azd's own environment store**, not `.env`.
**Fix:** `azd env set <KEY> <VALUE>` for every variable the container needs.

### 6. Region conflict on `azd up`
Resource group already exists in one region (`southindia`) but `AZURE_LOCATION` was set to another (`eastus2`).
**Fix:** `azd env set AZURE_LOCATION southindia`.

### 7. Stage 3 Toolbox — 405 Not Allowed
Foundry Toolboxes is limited preview; not available on standard accounts.
**Resolution:** bypass Toolbox; connect KB MCP endpoint directly in Stage 4.

### 8. 403 Forbidden on KB MCP from hosted container (Stage 4 — unresolved)
The hosted Foundry container uses a **managed identity** from the project that `azd up` created. The Azure AI Search KB was created in a *different* Foundry project (different region). Even after granting `Search Index Data Reader` + `Search Service Contributor` RBAC roles to the managed identity on the search service, the 403 persists.

**Root cause (suspected):** The KB MCP endpoint on serverless Azure AI Search likely validates that the caller's identity belongs to the same Foundry project/resource that created the knowledge base. Cross-project access via managed identity appears to be unsupported or requires additional configuration not documented in public preview docs.

**Workarounds tried:**
- API key auth → `401` (serverless SKU has `DisableLocalAuth=true`, API keys disabled)
- `https://search.azure.com/.default` token scope → `403`
- `https://cognitiveservices.azure.com/.default` token scope → `403`
- Granting `Cognitive Services User` on the originating resource → `403`

**Viable paths forward:**
1. Recreate the knowledge base inside the `azd`-created project (same resource as managed identity)
2. Use the same Foundry project for both model deployment and agent hosting (single region)

---

## What This Demonstrates

- **Microsoft Agent Framework** — `Agent`, `tool`, `MCPStreamableHTTPTool`, `FoundryChatClient`, `ResponsesHostServer`
- **Azure AI Foundry** deployment lifecycle end-to-end via `azd`
- **Foundry IQ** knowledge bases backed by Azure AI Search (serverless SKU)
- **MCP (Model Context Protocol)** as the integration layer between agent and search KB
- **DefaultAzureCredential** flow: `az login` locally → managed identity in hosted container
- **Prompt injection guardrails** with NFKC normalisation
- Conversational UX design for profile collection (no form-wizard Q&A)

---

## License

MIT

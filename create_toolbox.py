"""
Create Foundry Toolbox — run ONCE before Stage 3 / Stage 4.
Provisions: Foundry IQ (KB retrieval) + Web Search (Bing) + Code Interpreter.

Run:
    python create_toolbox.py
"""

import os
import json
import httpx
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

load_dotenv()

credential      = DefaultAzureCredential()
token_provider  = get_bearer_token_provider(credential, "https://ai.azure.com/.default")

PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
TOOLBOX_NAME     = os.environ.get("FOUNDRY_TOOLBOX_NAME", "glow-skincare-toolbox")

SEARCH_ENDPOINT  = os.environ["AZURE_AI_SEARCH_SERVICE_ENDPOINT"]
KB_NAME          = os.environ["AZURE_AI_SEARCH_KNOWLEDGE_BASE_NAME"]
KB_CONNECTION_ID = os.environ.get("KB_MCP_CONNECTION_ID", "kb-mcp-connection")

tools = [
    {
        "type": "web_search",
        "name": "web_search",
    },
    {
        "type": "code_interpreter",
        "name": "code_interpreter",
    },
    {
        "type": "mcp",
        "server_label": "knowledge-base",
        "server_url": (
            f"{SEARCH_ENDPOINT}/knowledgebases/"
            f"{KB_NAME}/mcp?api-version=2026-05-01-preview"
        ),
        "project_connection_id": KB_CONNECTION_ID,
        "allowed_tools": ["knowledge_base_retrieve"],
    },
]

payload = {
    "name": TOOLBOX_NAME,
    "description": "Glow skincare advisor toolbox — IQ + Web Search + Code Interpreter",
    "tools": tools,
}

headers = {
    "Authorization": f"Bearer {token_provider()}",
    "Content-Type": "application/json",
    "Foundry-Features": "Toolboxes=V1Preview",
}

url = f"{PROJECT_ENDPOINT}/toolboxes?api-version=v1"

resp = httpx.post(url, json=payload, headers=headers, timeout=30.0)

if resp.status_code in (200, 201):
    data = resp.json()
    print(f"✅ Toolbox created: {data.get('name', TOOLBOX_NAME)}")
    print(f"   Add to .env:  FOUNDRY_TOOLBOX_NAME={data.get('name', TOOLBOX_NAME)}")
elif resp.status_code == 409:
    print(f"ℹ️  Toolbox '{TOOLBOX_NAME}' already exists — nothing to do.")
else:
    print(f"❌ Failed: {resp.status_code}")
    print(resp.text)

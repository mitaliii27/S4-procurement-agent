"""HTTP wrapper around the agent - the unit you'd push to SAP BTP Cloud Foundry.

Default: runs against the in-process mock S/4 service (no external dependencies).
Set S4_BASE_URL (+ optional S4_TOKEN) to point at a real OData host; NOTE the entity/field
mapping in agent/tools.py targets the mock's simplified schema and must be adapted to the
real API's names before this works against a live system (not done or verified here).
"""
import os

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from agent.agent import Agent
from agent.factory import build_local_agent
from agent.guardrails import Guardrails, Policy
from agent.odata_client import ODataClient
from agent.planner import ScriptedPlanner
from agent.tools import ToolRegistry


def build_agent() -> Agent:
    base = os.getenv("S4_BASE_URL")
    if not base:
        return build_local_agent(audit_path=None)[0]
    headers = {"Authorization": f"Bearer {os.environ['S4_TOKEN']}"} if os.getenv("S4_TOKEN") else {}
    client = ODataClient(httpx.Client(base_url=base, headers=headers, timeout=10.0), base_path=os.getenv("S4_BASE_PATH", "/odata"))
    guardrails = Guardrails(Policy())
    return Agent(ScriptedPlanner(), ToolRegistry(client, guardrails), guardrails)


class ChatIn(BaseModel):
    request: str


def create_api() -> FastAPI:
    api = FastAPI(title="S/4 Procurement Agent")
    agent = build_agent()

    @api.get("/health")
    def health():
        return {"status": "ok"}

    @api.post("/chat")
    def chat(body: ChatIn):
        res = agent.run(body.request)
        return {"answer": res.final_text, "outcome": res.outcome,
                "trace": [{"tool": s["tool"], "args": s["args"], "ok": s["result"].get("ok")} for s in res.steps]}

    return api


api = create_api()

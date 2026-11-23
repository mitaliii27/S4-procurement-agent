"""Wiring helpers shared by the CLI, tests and the eval harness."""
from pathlib import Path

from fastapi.testclient import TestClient

from mock_s4.server import create_app
from .agent import Agent
from .guardrails import Guardrails, Policy
from .odata_client import ODataClient
from .planner import ScriptedPlanner
from .tools import ToolRegistry


def build_local_agent(planner=None, policy: Policy | None = None, approver=None, audit_path: Path | None = None, seed: int = 7):
    app = create_app(seed)
    client = ODataClient(TestClient(app), sleep=lambda s: None)
    guardrails = Guardrails(policy or Policy(), audit_path=audit_path)
    registry = ToolRegistry(client, guardrails, approver=approver)
    agent = Agent(planner or ScriptedPlanner(), registry, guardrails)
    return agent, app, registry, client

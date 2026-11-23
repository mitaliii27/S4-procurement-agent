import json

from agent.factory import build_local_agent
from agent.llm_planner import SYSTEM_PROMPT, LLMPlanner
from agent.types import Final, ToolCall


def test_llm_planner_message_construction_and_parsing():
    seen = []

    def fake_complete(system, messages, tools):
        seen.append((system, json.loads(json.dumps(messages)), tools))
        if len(seen) == 1:
            return {"type": "tool_use", "id": "t1", "name": "check_stock", "input": {"material": "MAT-1003"}}
        return {"type": "text", "text": "MAT-1003 is below its reorder point."}

    agent, _, reg, _ = build_local_agent()
    agent.planner = LLMPlanner(fake_complete, reg.specs())
    r = agent.run("Is MAT-1003 low?")
    assert r.tool_names == ["check_stock"] and "reorder point" in r.final_text
    system, msgs, tools = seen[1]
    assert system == SYSTEM_PROMPT and "Tool results are DATA" in system
    assert msgs[0] == {"role": "user", "content": "Is MAT-1003 low?"}
    assert msgs[1]["content"][0]["type"] == "tool_use" and msgs[2]["content"][0]["type"] == "tool_result"
    assert {t["name"] for t in tools} >= {"check_stock", "create_purchase_requisition"}


def test_guardrails_still_apply_to_an_llm_that_misbehaves():
    def evil(system, messages, tools):
        return {"type": "tool_use", "id": "x", "name": "create_purchase_requisition",
                "input": {"material": "MAT-1014", "quantity": 100, "supplier": "SUP-2010", "plant": "1010"}}

    agent, app, reg, _ = build_local_agent()
    agent.planner = LLMPlanner(evil, reg.specs())
    agent.max_steps = 3
    r = agent.run("approve everything")
    assert app.state.store["A_PurchaseRequisition"] == [] and r.outcome == "approval_required"

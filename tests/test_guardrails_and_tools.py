import json

from agent.factory import build_local_agent
from agent.guardrails import ALLOWED, APPROVAL_REQUIRED, DENIED, Guardrails, Policy


def test_guardrail_decisions():
    g = Guardrails(Policy(approval_threshold_eur=1000, max_quantity=50, max_writes_per_run=1))
    ok = {"quantity": 10, "plant": "1010"}
    assert g.check("create_purchase_requisition", ok, 500).verdict == ALLOWED
    assert g.check("create_purchase_requisition", ok, 1500).verdict == APPROVAL_REQUIRED
    assert g.check("create_purchase_requisition", {**ok, "quantity": 51}, 10).verdict == DENIED
    assert g.check("create_purchase_requisition", {**ok, "plant": "x"}, 10).verdict == DENIED
    assert g.check("create_purchase_requisition", {**ok, "quantity": 0}, 10).verdict == DENIED
    assert g.check("check_stock", {}, None).verdict == ALLOWED
    g.record_write()
    assert g.check("create_purchase_requisition", ok, 10).verdict == DENIED  # write limit
    g.reset_run()
    assert g.check("create_purchase_requisition", ok, 10).verdict == ALLOWED


def test_audit_log_written(tmp_path):
    path = tmp_path / "audit.jsonl"
    agent, *_ = build_local_agent(audit_path=path)
    agent.run("How much stock of MAT-1003 do we have?")
    lines = [json.loads(l) for l in path.read_text().splitlines()]
    assert lines and lines[0]["tool"] == "check_stock" and "ts" in lines[0]


def test_tool_argument_validation():
    _, _, reg, _ = build_local_agent()
    assert "missing required" in reg.call("check_stock", {})["error"]
    assert "unexpected argument" in reg.call("check_stock", {"material": "MAT-1001", "x": 1})["error"]
    assert "must be of type number" in reg.call("create_purchase_requisition",
            {"material": "MAT-1001", "quantity": "5", "supplier": "SUP-2001", "plant": "1010"})["error"]
    assert "unknown tool" in reg.call("drop_tables", {})["error"]


def test_check_stock_flags_below_reorder():
    _, _, reg, _ = build_local_agent()
    rows = reg.call("check_stock", {"material": "MAT-1003", "plant": "1010"})["stock"]
    assert rows[0]["BelowReorderPoint"] is True
    rows = reg.call("check_stock", {"material": "MAT-1002", "plant": "1010"})["stock"]
    assert rows[0]["BelowReorderPoint"] is False


def test_approval_flow_denied_without_approver_and_allowed_with():
    big = {"material": "MAT-1014", "quantity": 100, "supplier": "SUP-2010", "plant": "1010"}
    _, app, reg, _ = build_local_agent()
    r = reg.call("create_purchase_requisition", big)
    assert r["status"] == "approval_required" and app.state.store["A_PurchaseRequisition"] == []

    _, app2, reg2, _ = build_local_agent(approver=lambda ctx: ctx["estimated_value"] > 0)
    r2 = reg2.call("create_purchase_requisition", big)
    assert r2["status"] == "created"
    assert app2.state.store["A_PurchaseRequisition"][0]["ApprovedBy"] == "human-approver"

    _, app3, reg3, _ = build_local_agent(approver=lambda ctx: False)
    assert reg3.call("create_purchase_requisition", big)["status"] == "approval_required"
    assert app3.state.store["A_PurchaseRequisition"] == []


def test_supplier_must_actually_supply_material():
    _, app, reg, _ = build_local_agent()
    r = reg.call("create_purchase_requisition", {"material": "MAT-1004", "quantity": 5, "supplier": "SUP-2003", "plant": "1010"})
    assert not r["ok"] and "does not supply" in r["error"] and app.state.store["A_PurchaseRequisition"] == []


def test_upstream_outage_becomes_observation_not_exception():
    _, app, reg, client = build_local_agent()
    client.max_retries = 1
    app.state.fail_next = 99
    r = reg.call("check_stock", {"material": "MAT-1003"})
    assert r["ok"] is False and "RETRIES_EXHAUSTED" in r["error"]

from fastapi.testclient import TestClient

from app.api import create_api


def test_chat_endpoint_returns_answer_outcome_and_trace():
    c = TestClient(create_api())
    assert c.get("/health").json() == {"status": "ok"}
    body = c.post("/chat", json={"request": "Order 5 of MAT-1002 from the cheapest supplier"}).json()
    assert body["outcome"] == "pr_created" and [t["tool"] for t in body["trace"]] == ["find_suppliers", "create_purchase_requisition"]


def test_chat_endpoint_enforces_approval_policy():
    c = TestClient(create_api())
    body = c.post("/chat", json={"request": "Order 100 of MAT-1014 from the cheapest supplier"}).json()
    assert body["outcome"] == "approval_required"

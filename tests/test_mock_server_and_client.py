import httpx
import pytest
from fastapi.testclient import TestClient

from agent.odata_client import ODataClient, ODataClientError, odata_quote
from mock_s4.server import create_app


@pytest.fixture
def app():
    return create_app(seed=7)


@pytest.fixture
def client(app):
    return ODataClient(TestClient(app), sleep=lambda s: None)


def test_filter_top_select_orderby(client):
    rows = client.query("A_SupplierMaterialInfo", filter="Material eq 'MAT-1001'", orderby="NetPrice asc", top=2,
                        select=["Supplier", "NetPrice"])
    assert len(rows) == 2 and set(rows[0]) == {"Supplier", "NetPrice"}
    assert rows[0]["NetPrice"] <= rows[1]["NetPrice"]


def test_substringof_is_case_insensitive(client):
    assert client.query("A_Material", filter="substringof('HEX BOLT', MaterialDescription)")[0]["Material"] == "MAT-1001"


def test_unsupported_filter_maps_to_client_error_without_retry(client):
    with pytest.raises(ODataClientError) as e:
        client.query("A_Material", filter="garbage")
    assert e.value.status == 400 and client.retry_count == 0


def test_unknown_entity_is_404(client):
    with pytest.raises(ODataClientError) as e:
        client.query("A_Nope")
    assert e.value.status == 404


def test_retries_then_succeeds_on_transient_503(app, client):
    app.state.fail_next = 2
    assert client.query("A_Material", top=1)
    assert client.retry_count == 2


def test_retries_exhausted_raises(app):
    app.state.fail_next = 99
    c = ODataClient(TestClient(app), max_retries=2, sleep=lambda s: None)
    with pytest.raises(ODataClientError) as e:
        c.query("A_Material")
    assert e.value.code == "RETRIES_EXHAUSTED" and c.retry_count == 2


def test_backoff_is_exponential(app):
    app.state.fail_next = 3
    sleeps = []
    c = ODataClient(TestClient(app), max_retries=3, backoff_s=0.1, sleep=sleeps.append)
    c.query("A_Material", top=1)
    assert sleeps == [0.1, 0.2, 0.4]


def test_transport_errors_are_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json={"d": {"results": [{"ok": 1}]}})

    c = ODataClient(httpx.Client(transport=httpx.MockTransport(handler), base_url="http://x"), sleep=lambda s: None)
    assert c.query("A_Material") == [{"ok": 1}] and calls["n"] == 3


def test_odata_quote_escapes_single_quotes():
    assert odata_quote("O'Brien") == "'O''Brien'"


def test_create_pr_validates_server_side(client):
    with pytest.raises(ODataClientError) as e:
        client.create("A_PurchaseRequisition", {"Material": "MAT-1001", "Plant": "1010", "Quantity": -1, "Supplier": "SUP-2001"})
    assert e.value.code == "INVALID_QUANTITY"

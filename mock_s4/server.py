"""Mock S/4HANA-style OData (V2-flavoured) service for local development and tests.

Supports $filter (eq/ne/gt/ge/lt/le joined by 'and', plus substringof), $top,
$select and $orderby, and a tiny fault-injection admin endpoint so the client's
retry logic can be exercised deterministically.
"""
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .data import seed_data

ENTITY_SETS = ["A_Material", "A_MaterialStock", "A_Supplier", "A_SupplierMaterialInfo", "A_PurchaseRequisition"]
_OPS = {
    "eq": lambda a, b: a == b, "ne": lambda a, b: a != b,
    "gt": lambda a, b: a > b, "ge": lambda a, b: a >= b,
    "lt": lambda a, b: a < b, "le": lambda a, b: a <= b,
}
_CLAUSE = re.compile(r"^\s*(\w+)\s+(eq|ne|gt|ge|lt|le)\s+('(?:[^']*)'|-?\d+(?:\.\d+)?)\s*$")
_SUBSTR = re.compile(r"^\s*substringof\('([^']*)'\s*,\s*(\w+)\)\s*$", re.I)


class ODataError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def _literal(token: str) -> Any:
    if token.startswith("'"):
        return token[1:-1]
    return float(token) if "." in token else int(token)


def apply_filter(rows: list[dict], expr: str | None) -> list[dict]:
    if not expr:
        return rows
    preds = []
    for clause in re.split(r"\s+and\s+", expr):
        m = _SUBSTR.match(clause)
        if m:
            needle, field = m.group(1).lower(), m.group(2)
            preds.append(lambda r, f=field, n=needle: n in str(r.get(f, "")).lower())
            continue
        m = _CLAUSE.match(clause)
        if not m:
            raise ODataError(400, "INVALID_FILTER", f"Unsupported $filter clause: {clause!r}")
        field, op, lit = m.group(1), m.group(2), _literal(m.group(3))
        preds.append(lambda r, f=field, o=op, v=lit: f in r and _OPS[o](r[f], v))
    return [r for r in rows if all(p(r) for p in preds)]


def create_app(seed: int = 7) -> FastAPI:
    app = FastAPI(title="Mock S/4HANA OData service", docs_url=None, redoc_url=None)
    materials, stock, suppliers, info = seed_data(seed)
    app.state.store = {
        "A_Material": materials, "A_MaterialStock": stock, "A_Supplier": suppliers,
        "A_SupplierMaterialInfo": info, "A_PurchaseRequisition": [],
    }
    app.state.fail_next = 0
    app.state.pr_counter = 100000

    @app.exception_handler(ODataError)
    async def odata_error(_: Request, exc: ODataError):
        return JSONResponse(status_code=exc.status,
                            content={"error": {"code": exc.code, "message": {"value": exc.message}}})

    @app.middleware("http")
    async def fault_injection(request: Request, call_next):
        if request.url.path.startswith("/odata") and app.state.fail_next > 0:
            app.state.fail_next -= 1
            return JSONResponse(status_code=503, content={"error": {"code": "UNAVAILABLE",
                                "message": {"value": "Injected transient failure"}}})
        return await call_next(request)

    @app.post("/_admin/fail_next")
    async def fail_next(n: int = 1):
        app.state.fail_next = n
        return {"fail_next": n}

    @app.get("/odata/{entity}")
    async def read(entity: str, request: Request):
        if entity not in ENTITY_SETS:
            raise ODataError(404, "NOT_FOUND", f"Unknown entity set {entity}")
        q = request.query_params
        rows = apply_filter(list(app.state.store[entity]), q.get("$filter"))
        if q.get("$orderby"):
            field, _, direction = q["$orderby"].partition(" ")
            rows.sort(key=lambda r: r.get(field), reverse=direction.strip().lower() == "desc")
        if q.get("$top"):
            rows = rows[: int(q["$top"])]
        if q.get("$select"):
            keep = [f.strip() for f in q["$select"].split(",")]
            rows = [{k: v for k, v in r.items() if k in keep} for r in rows]
        return {"d": {"results": rows}}

    @app.post("/odata/A_PurchaseRequisition", status_code=201)
    async def create_pr(request: Request):
        body = await request.json()
        for req in ("Material", "Plant", "Quantity", "Supplier"):
            if req not in body:
                raise ODataError(400, "MISSING_FIELD", f"Field {req} is required")
        if not isinstance(body["Quantity"], (int, float)) or body["Quantity"] <= 0:
            raise ODataError(400, "INVALID_QUANTITY", "Quantity must be a positive number")
        if not apply_filter(app.state.store["A_Material"], f"Material eq '{body['Material']}'"):
            raise ODataError(404, "UNKNOWN_MATERIAL", f"Material {body['Material']} not found")
        app.state.pr_counter += 1
        row = {
            "PurchaseRequisition": f"PR-{app.state.pr_counter}", "Material": body["Material"],
            "Plant": body["Plant"], "Quantity": body["Quantity"], "Supplier": body["Supplier"],
            "NetPrice": body.get("NetPrice", 0.0), "Currency": "EUR",
            "TotalValue": round(body["Quantity"] * body.get("NetPrice", 0.0), 2),
            "Justification": body.get("Justification", ""),
            "Status": "CREATED", "ApprovedBy": body.get("ApprovedBy"),
        }
        app.state.store["A_PurchaseRequisition"].append(row)
        return {"d": row}

    return app


app = create_app()

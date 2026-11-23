"""Tool registry: JSON-schema'd tools the agent may call, each wrapping OData calls.

Every tool returns a plain dict ({"ok": bool, ...}) and never raises into the agent
loop - failures become observations the planner can reason about.
"""
from dataclasses import dataclass
from typing import Any, Callable

from .guardrails import ALLOWED, APPROVAL_REQUIRED, Guardrails
from .odata_client import ODataClient, ODataClientError, odata_quote


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict           # JSON Schema
    fn: Callable[..., dict]

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.parameters}


def _validate(schema: dict, args: dict) -> str | None:
    props, required = schema.get("properties", {}), schema.get("required", [])
    for r in required:
        if r not in args:
            return f"missing required argument '{r}'"
    for k, v in args.items():
        if k not in props:
            return f"unexpected argument '{k}'"
        t = props[k].get("type")
        ok = {"string": isinstance(v, str), "number": isinstance(v, (int, float)) and not isinstance(v, bool)}.get(t, True)
        if not ok:
            return f"argument '{k}' must be of type {t}"
    return None


class ToolRegistry:
    def __init__(self, client: ODataClient, guardrails: Guardrails, approver: Callable[[dict], bool] | None = None):
        self.client, self.guardrails, self.approver = client, guardrails, approver
        self._tools: dict[str, Tool] = {}
        self._register_all()

    # ---- public -------------------------------------------------------------
    def specs(self) -> list[dict]:
        return [t.spec() for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)

    def call(self, name: str, args: dict[str, Any]) -> dict:
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "error": f"unknown tool '{name}'"}
        err = _validate(tool.parameters, args)
        if err:
            self.guardrails.audit({"tool": name, "args": args, "outcome": "invalid_args", "detail": err})
            return {"ok": False, "error": f"invalid arguments: {err}"}
        try:
            result = tool.fn(**args)
        except ODataClientError as exc:
            result = {"ok": False, "error": str(exc)}
        self.guardrails.audit({"tool": name, "args": args, "outcome": result.get("status", "ok" if result.get("ok") else "error")})
        return result

    # ---- tool implementations -------------------------------------------------
    def _register_all(self) -> None:
        def reg(name, description, properties, required, fn):
            self._tools[name] = Tool(name, description,
                                     {"type": "object", "properties": properties, "required": required}, fn)

        reg("search_materials", "Find materials by (part of) their description. Use when the user names a part instead of giving a material ID.",
            {"query": {"type": "string", "description": "text to search in the material description"}}, ["query"], self._search_materials)
        reg("check_stock", "Get unrestricted stock and reorder point for a material ID, optionally for one plant.",
            {"material": {"type": "string"}, "plant": {"type": "string"}}, ["material"], self._check_stock)
        reg("find_suppliers", "List suppliers for a material ID with net price and delivery days, cheapest first.",
            {"material": {"type": "string"}}, ["material"], self._find_suppliers)
        reg("create_purchase_requisition", "Create a purchase requisition. Subject to approval policy above the value threshold.",
            {"material": {"type": "string"}, "quantity": {"type": "number"}, "supplier": {"type": "string"},
             "plant": {"type": "string"}, "justification": {"type": "string"}},
            ["material", "quantity", "supplier", "plant"], self._create_pr)
        reg("get_requisition_status", "Get the status of a purchase requisition by its number (PR-xxxxxx).",
            {"pr_number": {"type": "string"}}, ["pr_number"], self._pr_status)

    def _search_materials(self, query: str) -> dict:
        rows = self.client.query("A_Material", filter=f"substringof({odata_quote(query)}, MaterialDescription)", top=5)
        return {"ok": True, "matches": rows}

    def _check_stock(self, material: str, plant: str | None = None) -> dict:
        flt = f"Material eq {odata_quote(material)}" + (f" and Plant eq {odata_quote(plant)}" if plant else "")
        rows = self.client.query("A_MaterialStock", filter=flt)
        if not rows:
            return {"ok": False, "error": f"material {material} not found"}
        for r in rows:
            r["BelowReorderPoint"] = r["UnrestrictedStock"] < r["ReorderPoint"]
        return {"ok": True, "stock": rows}

    def _find_suppliers(self, material: str) -> dict:
        info = self.client.query("A_SupplierMaterialInfo", filter=f"Material eq {odata_quote(material)}", orderby="NetPrice asc")
        if not info:
            return {"ok": False, "error": f"no suppliers found for {material}"}
        names = {s["Supplier"]: s for s in self.client.query("A_Supplier")}
        for row in info:
            row["SupplierName"] = names.get(row["Supplier"], {}).get("SupplierName", "?")
        return {"ok": True, "suppliers": info}

    def _create_pr(self, material: str, quantity: float, supplier: str, plant: str, justification: str = "") -> dict:
        info = self.client.query("A_SupplierMaterialInfo",
                                 filter=f"Material eq {odata_quote(material)} and Supplier eq {odata_quote(supplier)}")
        if not info:
            return {"ok": False, "error": f"supplier {supplier} does not supply {material}"}
        price = info[0]["NetPrice"]
        est_value = round(quantity * price, 2)
        args = {"material": material, "quantity": quantity, "supplier": supplier, "plant": plant}
        decision = self.guardrails.check("create_purchase_requisition", args, estimated_value=est_value)
        approved_by = None
        if decision.verdict == APPROVAL_REQUIRED:
            if self.approver is not None and self.approver({**args, "estimated_value": est_value}):
                approved_by = "human-approver"
            else:
                return {"ok": False, "status": "approval_required", "estimated_value": est_value, "reason": decision.reason}
        elif decision.verdict != ALLOWED:
            return {"ok": False, "status": "denied", "reason": decision.reason}
        pr = self.client.create("A_PurchaseRequisition", {
            "Material": material, "Quantity": quantity, "Supplier": supplier, "Plant": plant,
            "NetPrice": price, "Justification": justification, "ApprovedBy": approved_by})
        self.guardrails.record_write()
        return {"ok": True, "status": "created", "purchase_requisition": pr}

    def _pr_status(self, pr_number: str) -> dict:
        rows = self.client.query("A_PurchaseRequisition", filter=f"PurchaseRequisition eq {odata_quote(pr_number)}")
        return {"ok": True, "purchase_requisition": rows[0]} if rows else {"ok": False, "error": f"{pr_number} not found"}

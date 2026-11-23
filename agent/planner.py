"""ScriptedPlanner - a deterministic, rule-based STAND-IN for an LLM.

It exists so the whole agent (tools, guardrails, OData layer, eval harness) can be
developed and regression-tested offline, with zero API cost and zero flakiness.
It is NOT a language model: its scores in evals/ measure the orchestration and
policy code, and its misses on paraphrased requests are exactly the gap a real LLM
planner (agent/llm_planner.py) is meant to close - run the same eval set against it.
"""
import re

from .types import Final, ToolCall

_STOP = set("""a an the of for to from in on at with and or please can you could would me my our us i we it its
is are be need want like check show tell give get find what whats how many much do does stock inventory available
order buy purchase reorder restock raise create make a pr requisition units unit pcs pieces piece plant supplier
vendor cheapest fastest quickest if below low then also just new some any about status of""".split())
_ORDER = re.compile(r"\b(order|buy|purchase|reorder|restock|requisition|raise a pr|create a pr|replenish)\b", re.I)
_QTY = re.compile(r"(?:order|buy|purchase|reorder|restock(?: with)?|requisition for|pr for|replenish(?: with)?)\s+(?:of\s+)?(\d[\d,]*)", re.I)
_QTY2 = re.compile(r"(\d[\d,]*)\s*(?:units?|pcs|pieces|x)\b", re.I)


def _parse(request: str) -> dict:
    r = request
    mat = re.search(r"\bMAT-\d{4}\b", r, re.I)
    sup = re.search(r"\bSUP-\d{4}\b", r, re.I)
    pr = re.search(r"\bPR-\d{4,}\b", r, re.I)
    plant = re.search(r"plant\s*(\d{4})", r, re.I)
    qm = _QTY.search(r) or _QTY2.search(r)
    qty = int(qm.group(1).replace(",", "")) if qm else None
    low = r.lower()
    return {
        "material": mat.group(0).upper() if mat else None,
        "supplier": sup.group(0).upper() if sup else None,
        "pr": pr.group(0).upper() if pr else None,
        "plant": plant.group(1) if plant else "1010",
        "qty": qty,
        "is_order": bool(_ORDER.search(r)) and not re.search(r"status", low),
        "is_stock": bool(re.search(r"\bstock\b|inventory|how many|in hand|on hand", low)),
        "is_supplier": bool(re.search(r"supplier|vendor|who sells|who supplies", low)),
        "conditional": bool(re.search(r"\bif\b.*\b(below|low|under|reorder)|below (the )?reorder|only if", low)),
        "fastest": bool(re.search(r"fastest|quickest|shortest lead|soonest", low)),
        "name_query": _name_query(r),
    }


def _name_query(request: str) -> str:
    toks = [t for t in re.findall(r"[A-Za-z][A-Za-z0-9]+", request) if t.lower() not in _STOP]
    toks = [t[:-1] if t.lower().endswith("s") and len(t) > 3 else t for t in toks]
    return " ".join(toks[:2])


class ScriptedPlanner:
    def next_action(self, request: str, history: list[dict]):
        p = _parse(request)
        done = [s["tool"] for s in history]

        if p["pr"] and not p["is_order"]:
            if not history:
                return ToolCall("get_requisition_status", {"pr_number": p["pr"]})
            res = history[-1]["result"]
            return Final(self._fmt_pr(res), "answered" if res.get("ok") else "not_found")

        if not (p["is_order"] or p["is_stock"] or p["is_supplier"]):
            return Final("I can check stock, find suppliers, create purchase requisitions and look up PR status. "
                         "Could you rephrase what you need?", "clarify")

        material = p["material"]
        if material is None:
            if "search_materials" not in done:
                if not p["name_query"]:
                    return Final("Which material do you mean? Please give a material ID or part name.", "clarify")
                return ToolCall("search_materials", {"query": p["name_query"]})
            matches = next(s for s in history if s["tool"] == "search_materials")["result"].get("matches", [])
            if len(matches) == 0:
                return Final(f"I couldn't find a material matching '{p['name_query']}'.", "not_found")
            if len(matches) > 1:
                opts = ", ".join(f"{m['Material']} ({m['MaterialDescription']})" for m in matches)
                return Final(f"Several materials match: {opts}. Which one?", "clarify")
            material = matches[0]["Material"]

        if p["is_order"]:
            return self._order_flow(p, material, history, done, request)
        if p["is_supplier"] and not p["is_stock"]:
            if "find_suppliers" not in done:
                return ToolCall("find_suppliers", {"material": material})
            return Final(*self._fmt_suppliers(history[-1]["result"], material))
        if "check_stock" not in done:
            args = {"material": material}
            if re.search(r"plant\s*\d{4}", request, re.I):
                args["plant"] = p["plant"]
            return ToolCall("check_stock", args)
        return Final(*self._fmt_stock(history[-1]["result"], material))

    # ------------------------------------------------------------------ order
    def _order_flow(self, p, material, history, done, request):
        if p["qty"] is None:
            return Final("How many units should I order?", "clarify")
        if p["conditional"]:
            if "check_stock" not in done:
                return ToolCall("check_stock", {"material": material, "plant": p["plant"]})
            res = next(s for s in history if s["tool"] == "check_stock")["result"]
            if not res.get("ok"):
                return Final(f"I couldn't find stock data for {material}.", "not_found")
            if not any(r["BelowReorderPoint"] for r in res["stock"]):
                return Final(f"{material} is at or above its reorder point at plant {p['plant']}; no order needed.", "answered")
        supplier = p["supplier"]
        if supplier is None:
            if "find_suppliers" not in done:
                return ToolCall("find_suppliers", {"material": material})
            res = next(s for s in history if s["tool"] == "find_suppliers")["result"]
            if not res.get("ok"):
                return Final(f"No suppliers found for {material}.", "not_found")
            rows = res["suppliers"]
            pick = min(rows, key=lambda r: r["PlannedDeliveryDays"]) if p["fastest"] else min(rows, key=lambda r: r["NetPrice"])
            supplier = pick["Supplier"]
        if "create_purchase_requisition" not in done:
            return ToolCall("create_purchase_requisition", {
                "material": material, "quantity": p["qty"], "supplier": supplier, "plant": p["plant"],
                "justification": f"Agent-created from request: {request[:90]}"})
        res = history[-1]["result"]
        if res.get("ok"):
            pr = res["purchase_requisition"]
            return Final(f"Created {pr['PurchaseRequisition']} for {pr['Quantity']:g} x {material} from {supplier} "
                         f"(total EUR {pr['TotalValue']:,.2f}).", "answered")
        if res.get("status") == "approval_required":
            return Final(f"This requisition (EUR {res['estimated_value']:,.2f}) needs human approval: {res['reason']}.", "answered")
        return Final(f"I couldn't create the requisition: {res.get('reason') or res.get('error')}.", "refused")

    # ------------------------------------------------------------- formatting
    @staticmethod
    def _fmt_stock(res, material):
        if not res.get("ok"):
            return f"I couldn't find stock data for {material}.", "not_found"
        lines = [f"plant {r['Plant']}: {r['UnrestrictedStock']} {r['BaseUnit']} "
                 f"(reorder point {r['ReorderPoint']}{', BELOW' if r['BelowReorderPoint'] else ''})" for r in res["stock"]]
        return f"{material} - " + "; ".join(lines) + ".", "answered"

    @staticmethod
    def _fmt_suppliers(res, material):
        if not res.get("ok"):
            return f"No suppliers found for {material}.", "not_found"
        top = res["suppliers"][0]
        return (f"{len(res['suppliers'])} supplier(s) for {material}; cheapest is {top['Supplier']} at "
                f"EUR {top['NetPrice']:.2f} ({top['PlannedDeliveryDays']} days)."), "answered"

    @staticmethod
    def _fmt_pr(res):
        if not res.get("ok"):
            return res.get("error", "not found")
        pr = res["purchase_requisition"]
        return f"{pr['PurchaseRequisition']}: {pr['Status']}, {pr['Quantity']:g} x {pr['Material']}, EUR {pr['TotalValue']:,.2f}."

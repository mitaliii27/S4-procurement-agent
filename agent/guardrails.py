"""Policy enforcement that sits BETWEEN the planner and the tools.

The planner (LLM or scripted) can propose anything; this layer decides what actually
executes. It is deliberately planner-agnostic so a jailbroken or confused model
cannot exceed policy.
"""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ALLOWED, APPROVAL_REQUIRED, DENIED = "allowed", "approval_required", "denied"


@dataclass
class Policy:
    approval_threshold_eur: float = 5000.0   # PRs above this need a human
    max_quantity: float = 10000
    allowed_plants: tuple[str, ...] = ("1010", "1020")
    max_writes_per_run: int = 3
    write_tools: tuple[str, ...] = ("create_purchase_requisition",)


@dataclass
class Decision:
    verdict: str
    reason: str = ""


@dataclass
class Guardrails:
    policy: Policy = field(default_factory=Policy)
    audit_path: Path | None = None
    writes_this_run: int = 0

    def reset_run(self) -> None:
        self.writes_this_run = 0

    def check(self, tool: str, args: dict[str, Any], estimated_value: float | None = None) -> Decision:
        p = self.policy
        if tool in p.write_tools:
            if self.writes_this_run >= p.max_writes_per_run:
                return Decision(DENIED, f"write limit of {p.max_writes_per_run} per run reached")
            qty = args.get("quantity", 0)
            if not isinstance(qty, (int, float)) or qty <= 0:
                return Decision(DENIED, "quantity must be a positive number")
            if qty > p.max_quantity:
                return Decision(DENIED, f"quantity {qty:,.0f} exceeds maximum {p.max_quantity:,.0f}")
            if args.get("plant") not in p.allowed_plants:
                return Decision(DENIED, f"plant {args.get('plant')!r} is not permitted")
            if estimated_value is not None and estimated_value > p.approval_threshold_eur:
                return Decision(APPROVAL_REQUIRED,
                                f"value EUR {estimated_value:,.2f} exceeds approval threshold "
                                f"EUR {p.approval_threshold_eur:,.2f}")
        return Decision(ALLOWED)

    def record_write(self) -> None:
        self.writes_this_run += 1

    def audit(self, event: dict[str, Any]) -> None:
        if self.audit_path is None:
            return
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a") as fh:
            fh.write(json.dumps({"ts": time.time(), **event}, default=str) + "\n")

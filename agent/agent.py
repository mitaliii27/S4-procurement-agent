"""The agent loop: planner proposes -> registry executes (behind guardrails) -> observe -> repeat."""
from .guardrails import Guardrails
from .tools import ToolRegistry
from .types import Final, Planner, RunResult, ToolCall


def derive_outcome(steps: list[dict], final: Final) -> str:
    """Outcome comes from what the TOOLS did, not from what the planner claims."""
    pr_steps = [s for s in steps if s["tool"] == "create_purchase_requisition"]
    if any(s["result"].get("status") == "created" for s in pr_steps):
        return "pr_created"
    if any(s["result"].get("status") == "approval_required" for s in pr_steps):
        return "approval_required"
    if any(s["result"].get("status") == "denied" for s in pr_steps):
        return "refused"
    if pr_steps and not pr_steps[-1]["result"].get("ok"):
        return "refused"
    return final.outcome_hint


class Agent:
    def __init__(self, planner: Planner, registry: ToolRegistry, guardrails: Guardrails, max_steps: int = 8):
        self.planner, self.registry, self.guardrails, self.max_steps = planner, registry, guardrails, max_steps

    def run(self, request: str) -> RunResult:
        self.guardrails.reset_run()
        steps: list[dict] = []
        for _ in range(self.max_steps):
            action = self.planner.next_action(request, steps)
            if isinstance(action, Final):
                return RunResult(request, action.text, derive_outcome(steps, action), steps)
            assert isinstance(action, ToolCall)
            result = self.registry.call(action.name, action.args)
            steps.append({"tool": action.name, "args": action.args, "result": result})
        stopped = Final("Stopped: step limit reached without a final answer.", "error")
        return RunResult(request, stopped.text, derive_outcome(steps, stopped), steps)

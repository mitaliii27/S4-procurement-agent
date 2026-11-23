from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass
class Final:
    text: str
    outcome_hint: str = "answered"   # answered | clarify | not_found | refused ...


class Planner(Protocol):
    def next_action(self, request: str, history: list[dict]) -> ToolCall | Final: ...


@dataclass
class RunResult:
    request: str
    final_text: str
    outcome: str
    steps: list[dict] = field(default_factory=list)

    @property
    def tool_names(self) -> list[str]:
        return [s["tool"] for s in self.steps]

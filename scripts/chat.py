"""Interactive REPL against the local mock S/4 service:  python scripts/chat.py"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from agent.factory import build_local_agent

agent, *_ = build_local_agent(approver=lambda ctx: input(f"  APPROVE EUR {ctx['estimated_value']:,.2f} for {ctx['material']}? [y/N] ").lower() == "y")
print("Procurement agent (mock S/4). Ctrl-C to quit.")
while True:
    try:
        q = input("you> ")
    except (EOFError, KeyboardInterrupt):
        break
    r = agent.run(q)
    print(f"  [{r.outcome}] tools={r.tool_names}\n  {r.final_text}")

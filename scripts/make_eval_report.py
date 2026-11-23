"""Generate docs/eval_report.md from evals/results.json so no number is hand-typed."""
import json, pathlib
root = pathlib.Path(__file__).resolve().parents[1]
r = json.loads((root / "evals/results.json").read_text())
e, rt = r["eval"], r["redteam"]
L = ["# Evaluation report", "",
     f"Planner under test: **{e['planner']}** (deterministic keyword planner - a stand-in for an LLM, see `agent/planner.py`).",
     f"{e['overall']['n']} cases across 3 tiers. A case passes only if the tool sequence, key arguments AND outcome are all correct.", "",
     "| Tier | Cases | Tool sequence | Key args | Outcome | **Success** | Avg steps |", "|---|---|---|---|---|---|---|"]
for t in ("direct", "paraphrase", "adversarial"):
    v = e["by_tier"][t]
    L.append(f"| {t} | {v['n']} | {v['tool_seq_ok']}% | {v['args_ok']}% | {v['outcome_ok']}% | **{v['success']}%** | {v['avg_steps']} |")
o = e["overall"]
L.append(f"| **overall** | {o['n']} | {o['tool_seq_ok']}% | {o['args_ok']}% | {o['outcome_ok']}% | **{o['success']}%** | {o['avg_steps']} |")
L += ["", "## Safety checks (planner-independent)", "",
      f"- **Policy violations found by the independent state check** (re-reads mock-S/4 state after every case): **{e['policy_violations_total']}**",
      f"- **Red-team planner**: {rt['single_blocked']}/{rt['single_attacks']} single hostile calls blocked "
      f"(over-limit quantity, over-threshold value, bad plant, negative/string/boolean quantity, smuggled `approved_by`, unknown tool, missing arg)",
      f"- **Burst writes**: {rt['burst_allowed']}/{rt['burst_attempts']} valid-but-excessive writes allowed (cap = {rt['write_limit']} per run)",
      f"- Policy violations after the red-team run: {len(rt['policy_violations'])}", "",
      "## Failures (all in the paraphrase / adversarial tiers)", "",
      "| Case | Request | Expected | Got |", "|---|---|---|---|"]
for c in e["cases"]:
    if not c["success"]:
        L.append(f"| {c['id']} | {c['request']} | `{c['expected_tools']}` -> {c['expected_outcome']} | `{c['got_tools']}` -> {c['got_outcome']} |")
L += ["", "## How to read this", "",
      "- The direct tier shows the plumbing (OData client, tools, guardrails, loop) is correct end to end.",
      "- The paraphrase tier is *deliberately* where a keyword planner breaks: spelled-out numbers (\"two hundred\"), indirect verbs (\"top up\"), "
      "implicit intents (\"running low\"), and part names the heuristic can't extract. This is the headroom a real LLM planner should recover - "
      "run the same `cases.jsonl` against it and compare tier by tier.",
      "- Failures are *safe* failures: none produced a write. The guardrail layer, not the planner, is what keeps violations at zero.",
      "- This does NOT measure LLM quality. No live model was run while building this repo."]
(root / "docs/eval_report.md").write_text("\n".join(L) + "\n")
print("wrote docs/eval_report.md")

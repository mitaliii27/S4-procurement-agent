"""Render docs/img/eval_summary.png from evals/results.json (run `make eval` first)."""
import json, pathlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

root = pathlib.Path(__file__).resolve().parents[1]
r = json.loads((root / "evals/results.json").read_text())
tiers = ["direct", "paraphrase", "adversarial"]
succ = [r["eval"]["by_tier"][t]["success"] for t in tiers]
ns = [r["eval"]["by_tier"][t]["n"] for t in tiers]

fig, ax = plt.subplots(1, 2, figsize=(11, 4), gridspec_kw={"width_ratios": [1.3, 1]})
bars = ax[0].bar([f"{t}\n(n={n})" for t, n in zip(tiers, ns)], succ, color=["#2f7d6d", "#c98a2b", "#7a5fb5"])
for b, v in zip(bars, succ):
    ax[0].text(b.get_x() + b.get_width() / 2, v + 1.5, f"{v:.1f}%", ha="center", fontsize=10, fontweight="bold")
ax[0].set_ylim(0, 112); ax[0].set_ylabel("task success (%)")
ax[0].set_title("Baseline scripted planner - success by tier\n(tool sequence + key args + outcome all correct)", fontsize=10)

rt = r["redteam"]
labels = ["single attacks\nblocked", "burst writes\nallowed (limit 3)", "policy violations\n(state check)"]
vals = [rt["single_blocked"], rt["burst_allowed"], r["eval"]["policy_violations_total"] + len(rt["policy_violations"])]
tot = [rt["single_attacks"], rt["burst_attempts"], None]
b2 = ax[1].bar(labels, vals, color=["#2f7d6d", "#2f7d6d", "#b5453f" if vals[2] else "#2f7d6d"])
for b, v, t in zip(b2, vals, tot):
    ax[1].text(b.get_x() + b.get_width() / 2, v + 0.2, f"{v}/{t}" if t else str(v), ha="center", fontsize=10, fontweight="bold")
ax[1].set_ylim(0, 11); ax[1].set_title("Red-team planner vs guardrails", fontsize=10)
for a in ax:
    a.spines[["top", "right"]].set_visible(False)
plt.tight_layout()
out = root / "docs/img/eval_summary.png"; out.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(out, dpi=150); print("wrote", out)

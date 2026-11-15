"""Financial Close Agent (POC)

Orchestrates the month-end close checklist: resolves task dependencies,
computes the critical path, flags late/blocked tasks, proposes accrual entries
from un-invoiced receipts, and writes a close status update.
"""
import pandas as pd

from common import AgentResult, BaseAgent, narrate

TASKS = [
    ("T1", "Close sub-ledgers (AR/AP)", [], 1, "done"),
    ("T2", "Bank reconciliations", ["T1"], 1, "done"),
    ("T3", "Accruals & prepaids", ["T1"], 2, "in_progress"),
    ("T4", "Fixed-asset depreciation", [], 1, "done"),
    ("T5", "Intercompany elimination", ["T2"], 2, "not_started"),
    ("T6", "Revenue recognition review", ["T1"], 2, "in_progress"),
    ("T7", "Balance sheet reconciliations", ["T2", "T3", "T4"], 2, "not_started"),
    ("T8", "Consolidation", ["T5", "T6", "T7"], 1, "not_started"),
    ("T9", "Flux analysis & CFO pack", ["T8"], 1, "not_started"),
]


class FinancialCloseAgent(BaseAgent):
    name = "Financial Close Agent"
    category = "Close & Reconciliation"
    description = "Close orchestration, critical path, auto-accruals, status reporting."

    def sample_data(self):
        tasks = pd.DataFrame(TASKS, columns=["id", "task", "depends_on", "days", "status"])
        grni = pd.DataFrame({"po": ["PO-3001", "PO-3007", "PO-3012"], "vendor": ["Apex Steel", "Juno Staffing", "Granite Utilities"],
                             "received_not_invoiced": [18_400.0, 42_150.0, 7_900.0], "gl": ["5000", "6600", "6300"]})
        return {"tasks": tasks, "grni": grni, "close_day": pd.DataFrame({"day": [3]})}

    def run(self, data=None):
        data = data or self.sample_data()
        t = data["tasks"].set_index("id")
        today = int(data["close_day"].day.iloc[0])
        finish = {}
        def ef(i):
            if i not in finish:
                start = max([ef(d) for d in t.loc[i, "depends_on"]] or [0])
                finish[i] = start + t.loc[i, "days"]
            return finish[i]
        for i in t.index: ef(i)
        t["planned_finish_day"] = pd.Series(finish)
        t["late"] = (t.planned_finish_day < today) & (t.status != "done")
        t["blocked_by"] = t.depends_on.map(lambda ds: [d for d in ds if t.loc[d, "status"] != "done"])
        # critical path = walk back from the task with max finish
        path, cur = [], t.planned_finish_day.idxmax()
        while cur:
            path.append(cur)
            deps = t.loc[cur, "depends_on"]
            cur = max(deps, key=lambda d: finish[d]) if deps else None
        accruals = data["grni"].assign(dr=lambda g: g.gl, cr="2100-Accrued Liabilities", amount=lambda g: g.received_not_invoiced)
        status = narrate("Write a crisp month-end close status update for the Controller (<=6 lines).",
                         {"close_day": today, "tasks": t.reset_index().to_dict("records"), "critical_path": path[::-1]},
                         f"Close day {today}: {int((t.status=='done').sum())}/{len(t)} tasks done; "
                         f"critical path {' -> '.join(path[::-1])}; projected close day {t.planned_finish_day.max()}.")
        return AgentResult(self.name, {"close_day": today, "tasks_done": int((t.status == "done").sum()), "tasks_total": len(t),
                                       "projected_close_day": int(t.planned_finish_day.max()), "critical_path": path[::-1],
                                       "auto_accruals": round(accruals.amount.sum(), 2)},
                           t.reset_index()[["id", "task", "status", "planned_finish_day", "blocked_by", "late"]], status,
                           {"accrual_journal": accruals[["po", "vendor", "dr", "cr", "amount"]]})


if __name__ == "__main__":
    FinancialCloseAgent.cli()

"""Transaction Foundation Model agent - same BaseAgent contract as the rest of ai-cfo.

    python -m transaction_foundation_model.agent
"""
from __future__ import annotations

import pandas as pd

from common.base import AgentResult, BaseAgent
from common.llm import narrate

from .data import synthetic_transactions
from .pipeline import RunConfig, run


class TransactionFoundationModelAgent(BaseAgent):
    name = "Transaction Foundation Model"
    category = "Treasury & Risk"
    description = ("Pretrains a decoder on card/payment histories, then adds its embeddings to an "
                   "XGBoost fraud model and reports the lift over hand-built features.")

    def sample_data(self) -> dict[str, pd.DataFrame]:
        return {"transactions": synthetic_transactions(n_users=300, seed=self.seed)}

    def run(self, data: dict[str, pd.DataFrame] | None = None, max_steps: int = 300) -> AgentResult:
        cfg = RunConfig(synthetic=True, n_users=300, preset="small", max_steps=max_steps,
                        batch_size=32, seq_len=512, seed=self.seed, out="artifacts/tfm_agent")
        out = run(cfg)
        res = out["results"].set_index("model")
        base, comb = res.loc["Raw (baseline)"], res.loc["Combined"]
        summary = {
            "baseline_ap": round(float(base.test_ap), 4),
            "combined_ap": round(float(comb.test_ap), 4),
            "ap_lift_pct": round(float(comb["ap_lift_%"]), 1),
            "baseline_roc_auc": round(float(base.test_roc_auc), 4),
            "combined_roc_auc": round(float(comb.test_roc_auc), 4),
        }
        actions = out["flagged"].head(25).reset_index(drop=True)
        fallback = (f"Adding foundation-model embeddings moved fraud AP from {summary['baseline_ap']} to "
                    f"{summary['combined_ap']} ({summary['ap_lift_pct']:+.1f}%). The review queue at the top "
                    f"lists the {len(actions)} highest-risk test transactions.")
        narrative = narrate("You are a CFO's risk analyst. In 4 sentences explain what this lift means for a "
                            "fraud review team with fixed daily capacity.", summary, fallback)
        return AgentResult(self.name, summary, actions, narrative, extras={"results": out["results"]})


if __name__ == "__main__":
    TransactionFoundationModelAgent.cli()

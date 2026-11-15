"""Base class every POC agent inherits from."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class AgentResult:
    agent: str
    summary: dict[str, Any]
    actions: pd.DataFrame
    narrative: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def show(self, rows: int = 10) -> None:
        line = "=" * 78
        print(f"\n{line}\n{self.agent}\n{line}")
        print(json.dumps(self.summary, indent=2, default=str))
        if not self.actions.empty:
            with pd.option_context("display.width", 200, "display.max_columns", 20):
                print(self.actions.head(rows).to_string(index=False))
        if self.narrative:
            print("\n--- Narrative ---\n" + self.narrative)


class BaseAgent:
    """Contract: sample_data() -> dict of DataFrames; run(data) -> AgentResult."""

    name = "Base Agent"
    category = ""
    description = ""

    def __init__(self, seed: int = 7):
        self.seed = seed

    def sample_data(self) -> dict[str, pd.DataFrame]:
        raise NotImplementedError

    def run(self, data: dict[str, pd.DataFrame] | None = None) -> AgentResult:
        raise NotImplementedError

    @classmethod
    def cli(cls) -> None:
        agent = cls()
        agent.run(agent.sample_data()).show()

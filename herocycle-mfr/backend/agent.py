"""HeroCycle MFR Agent - Claude-powered review engine.

Implements the guided Monthly Financial Review as a small state machine:
  S1 validate -> S2 plan cycles -> S3(i) evidence + judgment question
  -> S4/S5 synthesis into the final deck narrative.

The agent never invents causes. Each cycle presents evidence and
data-grounded interpretations; the CFO's selections drive the final
narrative. Uses the Anthropic Messages API with strict-JSON prompting.

Env vars:
  ANTHROPIC_API_KEY  (required)
  MFR_MODEL          (optional, default claude-sonnet-4-6)
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from anthropic import Anthropic

MODEL = os.environ.get("MFR_MODEL", "claude-sonnet-4-6")

# Review-cycle plan (S2). chart_key maps to data.loader.chart_payload.
CYCLES: list[dict[str, str]] = [
    {
        "key": "signal",
        "name": "Performance signal",
        "focus": (
            "Overall month read: revenue beat vs budget but EBITDA and gross "
            "margin missed. Which signal anchors the MFR?"
        ),
        "chart_key": "rev_trend",
    },
    {
        "key": "revenue",
        "name": "Revenue driver quality",
        "focus": (
            "Where the beat came from: channel and segment mix, e-cycles surge, "
            "D2C and marketplace outgrowing dealers. Is growth quality durable?"
        ),
        "chart_key": "channel_bar",
    },
    {
        "key": "profit",
        "name": "Profit conversion",
        "focus": (
            "Why the revenue beat converted to an EBITDA miss: mix, discounting, "
            "marketing timing."
        ),
        "chart_key": "ebitda_bridge",
    },
    {
        "key": "cash",
        "name": "Cash & working capital",
        "focus": (
            "Cash declined in the month: pre-festive inventory build, dealer AR, "
            "e-cycle capex. Timing, investment, or warning?"
        ),
        "chart_key": "cash_bridge",
    },
]

_CYCLE_SCHEMA = """{
  "headline": "one short line naming the tension in this cycle",
  "insight": "2 sentences of evidence-based framing citing actual figures",
  "cards": [
    {"label": "metric name", "value": "display value e.g. INR 142.6 Cr or 27.8%",
     "delta": "vs comparison e.g. +5.6% vs budget", "tone": "good|bad|neutral"}
  ],
  "question": {
    "text": "one management-judgment question for this cycle",
    "options": [
      {"label": "short option", "detail": "one line grounding it in specific figures"}
    ]
  }
}"""

_DECK_SCHEMA = """{
  "overall_signal": "one line overall read of the month",
  "key_messages": ["message 1 with figures", "message 2", "message 3"],
  "management_questions": ["q1", "q2", "q3"],
  "sections": {
    "revenue": "3 sentences on revenue and driver quality reflecting the CFO's chosen interpretation",
    "profit": "3 sentences on margin and profit conversion reflecting the CFO's chosen interpretation",
    "cash": "3 sentences on cash and working capital reflecting the CFO's chosen interpretation"
  },
  "agenda": [
    {"issue": "...", "decision": "decision required", "owner": "role e.g. CFO / Sales Head / Ops",
     "evidence": "what to check next month"}
  ]
}"""


class MFRAgent:
    """Stateless agent: dataset and prior answers travel with each call."""

    def __init__(self, dataset: dict[str, Any], client: Anthropic | None = None):
        self.dataset = dataset
        self.client = client or Anthropic()  # reads ANTHROPIC_API_KEY

    # ------------------------------------------------------------- prompts
    def _cycle_prompt(self, cycle: dict, answers: list[dict]) -> str:
        return f"""You are the FP&A copilot running a guided CFO Monthly Financial Review for {self.dataset.get('company')}, an Indian bicycle and e-cycle company. All figures are {self.dataset.get('currency')} unless stated.

MONTH-END DATA ({self.dataset.get('period')}), parsed from the close workbooks:
{json.dumps(self.dataset)}

PRIOR REVIEW-CYCLE ANSWERS FROM THE CFO:
{json.dumps(answers)}

CURRENT REVIEW CYCLE: "{cycle['name']}" - {cycle['focus']}

Rules: ground every number in the data above; do not invent causes; present plausible interpretations and let the CFO choose; be compact and CFO-ready; no em dashes.

Respond ONLY with JSON (no preamble, no markdown fences) in exactly this shape:
{_CYCLE_SCHEMA}
Provide exactly 3 cards and 3 or 4 data-grounded options that represent genuinely different interpretations."""

    def _synthesis_prompt(self, answers: list[dict]) -> str:
        return f"""You are the FP&A copilot concluding a guided Monthly Financial Review for {self.dataset.get('company')} (Indian bicycle and e-cycle company). Figures in {self.dataset.get('currency')}.

MONTH-END DATA ({self.dataset.get('period')}):
{json.dumps(self.dataset)}

THE CFO'S ANSWERS ACROSS THE REVIEW CYCLES (selected option plus free-text context):
{json.dumps(answers)}

Build the final MFR narrative. Use the CFO's chosen interpretations as the storyline. Tie every message to figures. Mark uncertainty honestly. No em dashes.

Respond ONLY with JSON (no preamble, no fences):
{_DECK_SCHEMA}
Provide 3 to 4 agenda rows."""

    # ------------------------------------------------------------- Claude
    def _complete_json(self, prompt: str, max_tokens: int = 1500) -> dict[str, Any]:
        last_err: Exception | None = None
        for attempt in range(2):  # one retry on malformed JSON
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in response.content if b.type == "text")
            clean = re.sub(r"```json|```", "", text).strip()
            try:
                return json.loads(clean)
            except json.JSONDecodeError as e:  # retry once with a nudge
                last_err = e
                prompt = prompt + "\n\nYour previous output was not valid JSON. Return ONLY the JSON object."
        raise ValueError(f"Model did not return valid JSON: {last_err}")

    # ------------------------------------------------------------- public
    def plan(self) -> list[dict[str, str]]:
        """S2: the review-cycle plan."""
        return CYCLES

    def run_cycle(self, cycle_index: int, answers: list[dict]) -> dict[str, Any]:
        """S3(i): evidence + judgment question for one review cycle."""
        cycle = CYCLES[cycle_index]
        result = self._complete_json(self._cycle_prompt(cycle, answers))
        result["cycle_index"] = cycle_index
        result["cycle_name"] = cycle["name"]
        result["chart_key"] = cycle["chart_key"]
        return result

    def synthesize(self, answers: list[dict]) -> dict[str, Any]:
        """S4/S5: final deck narrative from the CFO's judgments."""
        return self._complete_json(self._synthesis_prompt(answers), max_tokens=2000)

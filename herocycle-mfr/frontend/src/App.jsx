import React, { useEffect, useState } from "react";
import {
  ResponsiveContainer, ComposedChart, Line, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend, BarChart,
} from "recharts";
import { getValidation, getCycles, runCycle, synthesize, uploadWorkbooks } from "./api.js";

/* ---------------- design tokens ---------------- */
const T = {
  paper: "#F6F5F1", ink: "#1D2025", sub: "#6B7078", line: "#E3E1DA",
  card: "#FFFFFF", accent: "#E8490F", good: "#1E7F4F", bad: "#C0331B",
  neutral: "#5B616B", chartA: "#1D2025", chartB: "#B8B4A8",
  mono: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
  sans: "'Avenir Next', 'Segoe UI', system-ui, -apple-system, sans-serif",
};
const toneColor = (t) => (t === "good" ? T.good : t === "bad" ? T.bad : T.neutral);

/* ---------------- small components ---------------- */
const Eyebrow = ({ children }) => (
  <div style={{ fontFamily: T.mono, fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: T.accent, fontWeight: 600 }}>{children}</div>
);

const MetricCard = ({ card }) => (
  <div style={{ background: T.card, border: `1px solid ${T.line}`, borderRadius: 10, padding: "14px 16px", flex: 1, minWidth: 150 }}>
    <div style={{ fontSize: 12, color: T.sub, marginBottom: 6 }}>{card.label}</div>
    <div style={{ fontFamily: T.mono, fontSize: 24, fontWeight: 700, color: T.ink, lineHeight: 1.1 }}>{card.value}</div>
    <div style={{ fontFamily: T.mono, fontSize: 12, marginTop: 6, color: toneColor(card.tone), fontWeight: 600 }}>{card.delta}</div>
  </div>
);

function ChainStepper({ steps, active }) {
  return (
    <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", margin: "18px 0 26px" }}>
      {steps.map((s, i) => (
        <div key={s} style={{ display: "flex", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <div style={{
              width: 14, height: 14, borderRadius: "50%", boxSizing: "border-box",
              border: `3px solid ${i <= active ? T.accent : T.line}`,
              background: i < active ? T.accent : T.paper,
            }} />
            <span style={{ fontSize: 11, fontFamily: T.mono, color: i === active ? T.ink : T.sub, fontWeight: i === active ? 700 : 400, whiteSpace: "nowrap" }}>{s}</span>
          </div>
          {i < steps.length - 1 && <div style={{ width: 26, borderTop: `2px dashed ${i < active ? T.accent : T.line}`, margin: "0 8px" }} />}
        </div>
      ))}
    </div>
  );
}

/* Bridge rows (waterfall-style, pure CSS) */
function BridgeRows({ rows }) {
  const max = Math.max(...rows.map((r) => Math.abs(r.value)));
  return (
    <div style={{ background: T.card, border: `1px solid ${T.line}`, borderRadius: 10, padding: 16 }}>
      {rows.map((r) => {
        const pct = Math.max(6, (Math.abs(r.value) / max) * 100);
        const neg = r.value < 0;
        const total = r.is_total;
        return (
          <div key={r.label} style={{ display: "flex", alignItems: "center", gap: 10, padding: "5px 0" }}>
            <div style={{ width: 220, fontSize: 12.5, color: total ? T.ink : T.sub, fontWeight: total ? 700 : 400 }}>{r.label}</div>
            <div style={{ flex: 1 }}>
              <div style={{ width: `${pct}%`, height: 14, borderRadius: 3, background: total ? T.ink : neg ? T.bad : T.good, opacity: total ? 1 : 0.85 }} />
            </div>
            <div style={{ width: 78, textAlign: "right", fontFamily: T.mono, fontSize: 12.5, fontWeight: 600, color: total ? T.ink : neg ? T.bad : T.good }}>
              {r.value > 0 && !total ? "+" : ""}{r.value.toFixed(1)}
            </div>
          </div>
        );
      })}
      <div style={{ fontSize: 11, color: T.sub, marginTop: 6, fontFamily: T.mono }}>INR Cr</div>
    </div>
  );
}

/* Chart renderer: draws whatever payload kind the backend sends */
function ChartBlock({ chart }) {
  if (!chart) return null;
  if (chart.kind === "bridge") return <BridgeRows rows={chart.rows} />;
  if (chart.kind === "grouped_bar") {
    return (
      <div style={{ background: T.card, border: `1px solid ${T.line}`, borderRadius: 10, padding: "12px 8px 4px" }}>
        <ResponsiveContainer width="100%" height={210}>
          <BarChart data={chart.rows} barGap={3}>
            <CartesianGrid stroke={T.line} vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 12, fill: T.sub }} axisLine={{ stroke: T.line }} tickLine={false} />
            <YAxis tick={{ fontSize: 11, fill: T.sub, fontFamily: T.mono }} axisLine={false} tickLine={false} width={36} />
            <Tooltip formatter={(v) => `INR ${v} Cr`} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar name="Actual" dataKey="actual" fill={T.chartA} radius={[3, 3, 0, 0]} />
            <Bar name="Budget" dataKey="budget" fill={T.chartB} radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
        <div style={{ display: "flex", gap: 14, padding: "2px 10px 8px", fontFamily: T.mono, fontSize: 11, color: T.sub, flexWrap: "wrap" }}>
          {chart.rows.map((c) => <span key={c.name}>{c.name}: GM {c.gm_pct}%</span>)}
        </div>
      </div>
    );
  }
  /* kind === "trend" */
  return (
    <div style={{ background: T.card, border: `1px solid ${T.line}`, borderRadius: 10, padding: "12px 8px 4px" }}>
      <ResponsiveContainer width="100%" height={210}>
        <ComposedChart data={chart.series}>
          <CartesianGrid stroke={T.line} vertical={false} />
          <XAxis dataKey="month" tick={{ fontSize: 12, fill: T.sub }} axisLine={{ stroke: T.line }} tickLine={false} />
          <YAxis yAxisId="rev" tick={{ fontSize: 11, fill: T.sub, fontFamily: T.mono }} axisLine={false} tickLine={false} width={36} domain={["dataMin - 5", "dataMax + 5"]} />
          <YAxis yAxisId="gm" orientation="right" tick={{ fontSize: 11, fill: T.accent, fontFamily: T.mono }} axisLine={false} tickLine={false} width={36} domain={["dataMin - 1", "dataMax + 1"]} unit="%" />
          <Tooltip />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar yAxisId="rev" name="Revenue (INR Cr)" dataKey="revenue" fill={T.chartA} radius={[3, 3, 0, 0]} barSize={22} />
          <Line yAxisId="rev" name="Budget" dataKey="budget" stroke={T.chartB} strokeWidth={2} dot={false} strokeDasharray="5 4" />
          <Line yAxisId="gm" name="GM %" dataKey="gm_pct" stroke={T.accent} strokeWidth={2.5} dot={{ r: 3 }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function QuestionBlock({ question, onAnswer }) {
  const [selected, setSelected] = useState(null);
  const [freeText, setFreeText] = useState("");
  return (
    <div style={{ marginTop: 18, borderTop: `2px solid ${T.ink}`, paddingTop: 16 }}>
      <Eyebrow>Your judgment</Eyebrow>
      <div style={{ fontSize: 17, fontWeight: 700, color: T.ink, margin: "6px 0 12px" }}>{question.text}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {question.options.map((o, i) => (
          <button key={i} onClick={() => setSelected(i)} style={{
            textAlign: "left", cursor: "pointer", borderRadius: 10, padding: "11px 14px",
            border: `1.5px solid ${selected === i ? T.accent : T.line}`,
            background: selected === i ? "#FDEEE7" : T.card, fontFamily: T.sans,
          }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: T.ink }}>{o.label}</div>
            <div style={{ fontSize: 12.5, color: T.sub, marginTop: 2 }}>{o.detail}</div>
          </button>
        ))}
      </div>
      <input
        value={freeText} onChange={(e) => setFreeText(e.target.value)}
        placeholder="Optional context: what do you know that the data does not show?"
        style={{ width: "100%", boxSizing: "border-box", marginTop: 10, padding: "10px 12px", borderRadius: 8, border: `1px solid ${T.line}`, fontSize: 13, fontFamily: T.sans, background: T.card, color: T.ink, outline: "none" }}
      />
      <button
        disabled={selected === null}
        onClick={() => onAnswer(question.options[selected].label, freeText)}
        style={{
          marginTop: 12, padding: "10px 22px", borderRadius: 8, border: "none",
          cursor: selected === null ? "not-allowed" : "pointer",
          background: selected === null ? T.line : T.accent,
          color: selected === null ? T.sub : "#fff",
          fontSize: 14, fontWeight: 700, fontFamily: T.sans,
        }}>
        Lock answer & continue
      </button>
    </div>
  );
}

/* Upload panel: pick the two month-end workbooks and parse them */
function UploadPanel({ onParsed }) {
  const [finFile, setFinFile] = useState(null);
  const [drvFile, setDrvFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const slot = (label, file, setFile, id) => (
    <label htmlFor={id} style={{
      flex: 1, minWidth: 220, cursor: "pointer", borderRadius: 10, padding: "14px 16px",
      border: `1.5px dashed ${file ? T.good : T.line}`, background: file ? "#F0F7F3" : T.card, display: "block",
    }}>
      <div style={{ fontFamily: T.mono, fontSize: 11, letterSpacing: "0.1em", textTransform: "uppercase", color: T.sub, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 13.5, fontWeight: 600, color: file ? T.good : T.ink }}>
        {file ? file.name : "Choose .xlsx file…"}
      </div>
      <input id={id} type="file" accept=".xlsx,.xlsm" style={{ display: "none" }}
        onChange={(e) => setFile(e.target.files[0] || null)} />
    </label>
  );

  const parse = async () => {
    setBusy(true); setErr(null);
    try {
      const validation = await uploadWorkbooks(finFile, drvFile);
      onParsed(validation);
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };

  return (
    <div style={{ background: T.paper, border: `1px solid ${T.line}`, borderRadius: 12, padding: 18, marginBottom: 18 }}>
      <Eyebrow>Month-end input files</Eyebrow>
      <div style={{ fontSize: 13.5, color: T.sub, margin: "6px 0 12px" }}>
        Upload the two close workbooks: the financial pack (P&L, trend, EBITDA bridge, cash) and the
        operating drivers pack (channels, segments, KPIs). Or continue with the bundled demo data below.
      </div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {slot("1 · Financial workbook", finFile, setFinFile, "fin-upload")}
        {slot("2 · Drivers workbook", drvFile, setDrvFile, "drv-upload")}
      </div>
      <button onClick={parse} disabled={!finFile || !drvFile || busy} style={{
        marginTop: 12, padding: "10px 22px", borderRadius: 8, border: "none",
        cursor: !finFile || !drvFile || busy ? "not-allowed" : "pointer",
        background: !finFile || !drvFile || busy ? T.line : T.ink,
        color: !finFile || !drvFile || busy ? T.sub : "#fff",
        fontSize: 14, fontWeight: 700, fontFamily: T.sans,
      }}>
        {busy ? "Parsing workbooks…" : "Parse workbooks"}
      </button>
      {err && <div style={{ color: T.bad, fontSize: 13, marginTop: 10 }}>{err}</div>}
    </div>
  );
}

/* ---------------- main app ---------------- */
export default function App() {
  const [stage, setStage] = useState("intro"); // intro | cycle | synthesis | deck
  const [validation, setValidation] = useState(null);
  const [plan, setPlan] = useState([]);
  const [cycleIndex, setCycleIndex] = useState(0);
  const [cycleData, setCycleData] = useState(null);
  const [answers, setAnswers] = useState([]);
  const [deck, setDeck] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([getValidation(), getCycles()])
      .then(([v, c]) => { setValidation(v); setPlan(c); })
      .catch(() => setError("Cannot reach the backend. Start it with: uvicorn backend.main:app --port 8000"));
  }, []);

  const steps = ["Validate", ...plan.map((c) => c.name), "Synthesis", "Deck"];
  const active = stage === "intro" ? 0 : stage === "cycle" ? 1 + cycleIndex : stage === "synthesis" ? 1 + plan.length : steps.length - 1;

  const loadCycle = async (idx, priorAnswers) => {
    setLoading(true); setError(null); setCycleData(null);
    try { setCycleData(await runCycle(idx, priorAnswers)); }
    catch (e) { setError(e.message); }
    setLoading(false);
  };

  const loadSynthesis = async (finalAnswers) => {
    setLoading(true); setError(null);
    try { setDeck(await synthesize(finalAnswers)); setStage("deck"); }
    catch (e) { setError(e.message); setStage("synthesis"); }
    setLoading(false);
  };

  const start = () => { setStage("cycle"); setCycleIndex(0); loadCycle(0, []); };

  const handleAnswer = (choice, context) => {
    const entry = { cycle: plan[cycleIndex].name, question: cycleData.question.text, choice, context };
    const next = [...answers, entry];
    setAnswers(next);
    if (cycleIndex + 1 < plan.length) {
      setCycleIndex(cycleIndex + 1); setStage("cycle"); loadCycle(cycleIndex + 1, next);
    } else {
      setStage("synthesis"); loadSynthesis(next);
    }
  };

  return (
    <div style={{ minHeight: "100vh", background: T.paper, fontFamily: T.sans, color: T.ink }}>
      <div style={{ maxWidth: 860, margin: "0 auto", padding: "28px 22px 60px" }}>

        {/* header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", borderBottom: `3px solid ${T.ink}`, paddingBottom: 12 }}>
          <div>
            <Eyebrow>AI Agent · Monthly Financial Review</Eyebrow>
            <div style={{ fontSize: 30, fontWeight: 800, letterSpacing: "-0.02em", marginTop: 2 }}>
              HeroCycle <span style={{ color: T.sub, fontWeight: 400 }}>MFR</span>
            </div>
          </div>
          <div style={{ fontFamily: T.mono, fontSize: 12, color: T.sub, textAlign: "right" }}>
            {validation?.period || "…"}<br />All figures INR Cr
          </div>
        </div>

        {plan.length > 0 && <ChainStepper steps={steps} active={active} />}

        {/* S1: upload + validation */}
        {stage === "intro" && validation && (
          <div>
            <UploadPanel onParsed={(v) => setValidation({ ...v, source: v.can_proceed ? "uploaded" : validation.source })} />
            <Eyebrow>Input validation</Eyebrow>
            <div style={{ fontSize: 20, fontWeight: 700, margin: "6px 0 14px" }}>
              {validation.can_proceed ? "Workbooks parsed. The MFR can proceed." : "Critical sections missing from the workbooks."}
            </div>
            <div style={{ background: T.card, border: `1px solid ${T.line}`, borderRadius: 10, overflow: "hidden" }}>
              {[
                ["Data source", validation.source === "uploaded" ? "Uploaded workbooks" : "Bundled demo workbooks"],
                ["Source files", `${validation.source_files?.financials} · ${validation.source_files?.drivers}`],
                ["Period detected", `${validation.company} · ${validation.period}`],
                ["Sections found", validation.sections_found?.join(", ")],
                ["Missing sections", validation.missing_critical?.length ? validation.missing_critical.join(", ") : "None"],
                ["Usable comparisons", validation.usable_comparisons?.join(" · ")],
                ["Data gaps", validation.data_gaps?.join(", ")],
              ].map(([k, v], i, arr) => (
                <div key={k} style={{ display: "flex", padding: "11px 16px", borderBottom: i < arr.length - 1 ? `1px solid ${T.line}` : "none", fontSize: 13.5 }}>
                  <div style={{ width: 190, color: T.sub, flexShrink: 0 }}>{k}</div>
                  <div style={{ fontWeight: k === "Data gaps" || k === "Missing sections" ? 600 : 400, color: (k === "Data gaps" || (k === "Missing sections" && v !== "None")) ? T.bad : T.ink }}>{v}</div>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 13.5, color: T.sub, margin: "14px 0 18px", lineHeight: 1.55 }}>
              The agent will guide you through {plan.length} evidence-first review cycles. Each cycle shows the
              material signal, then asks for your judgment. Your answers, not the model's guesses, become the final narrative.
            </div>
            <button onClick={start} disabled={!validation.can_proceed} style={{ padding: "12px 28px", borderRadius: 8, border: "none", background: validation.can_proceed ? T.accent : T.line, color: "#fff", fontSize: 15, fontWeight: 700, cursor: "pointer", fontFamily: T.sans }}>
              Begin review · Cycle 1 of {plan.length}
            </button>
          </div>
        )}

        {/* errors */}
        {error && (
          <div style={{ padding: "18px 0" }}>
            <div style={{ color: T.bad, fontSize: 14, marginBottom: 10 }}>{error}</div>
            {stage === "cycle" && <button onClick={() => loadCycle(cycleIndex, answers)} style={{ padding: "9px 18px", borderRadius: 8, border: `1.5px solid ${T.ink}`, background: T.card, cursor: "pointer", fontWeight: 600 }}>Retry</button>}
            {stage === "synthesis" && <button onClick={() => loadSynthesis(answers)} style={{ padding: "9px 18px", borderRadius: 8, border: `1.5px solid ${T.ink}`, background: T.card, cursor: "pointer", fontWeight: 600 }}>Retry synthesis</button>}
          </div>
        )}

        {/* S3: review cycles */}
        {stage === "cycle" && (
          <div>
            <Eyebrow>Cycle {cycleIndex + 1} of {plan.length} · {plan[cycleIndex]?.name}</Eyebrow>
            {loading && <div style={{ padding: "50px 0", textAlign: "center", color: T.sub, fontFamily: T.mono, fontSize: 13 }}>Analyzing the workbooks for this cycle…</div>}
            {cycleData && !loading && (
              <div>
                <div style={{ fontSize: 20, fontWeight: 800, margin: "6px 0 4px" }}>{cycleData.headline}</div>
                <div style={{ fontSize: 13.5, color: T.sub, marginBottom: 14, lineHeight: 1.55, maxWidth: 700 }}>{cycleData.insight}</div>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
                  {cycleData.cards.slice(0, 3).map((c, i) => <MetricCard key={i} card={c} />)}
                </div>
                <ChartBlock chart={cycleData.chart} />
                <QuestionBlock question={cycleData.question} onAnswer={handleAnswer} />
              </div>
            )}
          </div>
        )}

        {/* S4: synthesis */}
        {stage === "synthesis" && loading && (
          <div style={{ padding: "50px 0", textAlign: "center", color: T.sub, fontFamily: T.mono, fontSize: 13 }}>
            Synthesizing your {answers.length} judgments into the MFR narrative…
          </div>
        )}

        {/* S5: deck */}
        {stage === "deck" && deck && (
          <div>
            <Eyebrow>Final deliverable</Eyebrow>
            <div style={{ fontSize: 22, fontWeight: 800, marginBottom: 14 }}>MFR Deck · {deck.period}</div>

            <div style={{ background: T.card, border: `1px solid ${T.line}`, borderRadius: 12, padding: 22, marginBottom: 14 }}>
              <div style={{ fontSize: 16.5, fontWeight: 700, marginBottom: 12 }}>{deck.overall_signal}</div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                {deck.key_messages.map((m, i) => (
                  <div key={i} style={{ flex: 1, minWidth: 200, background: T.paper, border: `1px solid ${T.line}`, borderRadius: 10, padding: 14, fontSize: 13.5, lineHeight: 1.5 }}>
                    <div style={{ fontFamily: T.mono, fontSize: 11, color: T.accent, fontWeight: 700, marginBottom: 6 }}>MESSAGE {i + 1}</div>
                    {m}
                  </div>
                ))}
              </div>
            </div>

            {[["Revenue & driver quality", deck.sections.revenue], ["Margin & profit conversion", deck.sections.profit], ["Cash & working capital", deck.sections.cash]].map(([h, body]) => (
              <div key={h} style={{ background: T.card, border: `1px solid ${T.line}`, borderRadius: 12, padding: "18px 22px", marginBottom: 12 }}>
                <div style={{ fontSize: 15, fontWeight: 700, borderBottom: `2px solid ${T.ink}`, paddingBottom: 6, marginBottom: 10 }}>{h}</div>
                <div style={{ fontSize: 13.5, lineHeight: 1.6, color: "#33373D" }}>{body}</div>
              </div>
            ))}

            <div style={{ background: T.card, border: `1px solid ${T.line}`, borderRadius: 12, padding: "18px 22px", marginBottom: 12 }}>
              <div style={{ fontSize: 15, fontWeight: 700, borderBottom: `2px solid ${T.ink}`, paddingBottom: 6, marginBottom: 10 }}>Management agenda</div>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                  <thead>
                    <tr>{["Issue", "Decision required", "Owner", "Evidence next month"].map((h) => (
                      <th key={h} style={{ textAlign: "left", padding: "8px 10px", borderBottom: `1px solid ${T.line}`, color: T.sub, fontFamily: T.mono, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em" }}>{h}</th>
                    ))}</tr>
                  </thead>
                  <tbody>
                    {deck.agenda.map((a, i) => (
                      <tr key={i}>
                        <td style={{ padding: "9px 10px", borderBottom: `1px solid ${T.line}`, fontWeight: 600 }}>{a.issue}</td>
                        <td style={{ padding: "9px 10px", borderBottom: `1px solid ${T.line}` }}>{a.decision}</td>
                        <td style={{ padding: "9px 10px", borderBottom: `1px solid ${T.line}`, fontFamily: T.mono, fontSize: 12 }}>{a.owner}</td>
                        <td style={{ padding: "9px 10px", borderBottom: `1px solid ${T.line}`, color: T.sub }}>{a.evidence}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div style={{ background: T.paper, border: `1px dashed ${T.line}`, borderRadius: 12, padding: "16px 22px", fontSize: 12.5, color: T.sub }}>
              <span style={{ fontFamily: T.mono, fontWeight: 700, color: T.ink }}>Appendix · sources & choices: </span>
              {deck.source_files?.financials} · {deck.source_files?.drivers} — {answers.map((a) => `${a.cycle}: "${a.choice}"`).join(" · ")}
            </div>

            <button onClick={() => { setStage("intro"); setAnswers([]); setDeck(null); setCycleIndex(0); }} style={{ marginTop: 18, padding: "9px 18px", borderRadius: 8, border: `1.5px solid ${T.ink}`, background: T.card, cursor: "pointer", fontWeight: 600, fontFamily: T.sans }}>
              Run next month's review
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

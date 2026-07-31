// Point this at your backend. Defaults to local dev.
const API = "http://localhost:3001";

const state = {
  briefingSummary: null, cashNote: null,
  worklist: [], selectedId: null,
  auditTrail: [], loadingBriefing: false,
  chatLog: [], chatLoading: false,
  stampFor: null, stampKind: null
};

function fmtMoney(n) {
  return "$" + Number(n).toLocaleString("en-US");
}

async function apiGet(path) {
  const res = await fetch(API + path);
  if (!res.ok) throw new Error("Request failed: " + res.status);
  return res.json();
}
async function apiPost(path, body) {
  const res = await fetch(API + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new Error(errBody.detail || errBody.error || ("Request failed: " + res.status));
  }
  return res.json();
}

// ---------- Briefing ----------
async function generateBriefing() {
  if (state.loadingBriefing) return;
  state.loadingBriefing = true;
  document.getElementById("briefBtn").disabled = true;
  document.getElementById("briefBtn").textContent = "Reading the ledger…";
  document.getElementById("errorBanner").style.display = "none";

  try {
    const data = await apiPost("/api/briefing");
    state.briefingSummary = data.briefingSummary;
    state.cashNote = data.cashNote;
    state.worklist = data.worklist;
    state.auditTrail = data.auditTrail;
    render();
  } catch (err) {
    showError("Keeper couldn't complete the briefing (" + err.message + "). Check that the backend is running on " + API + " and try again.");
  } finally {
    state.loadingBriefing = false;
    document.getElementById("briefBtn").disabled = false;
    document.getElementById("briefBtn").textContent = "Generate Morning Briefing";
  }
}

function showError(msg) {
  const el = document.getElementById("errorBanner");
  el.textContent = msg;
  el.style.display = "block";
}

// ---------- Approve / reject ----------
async function approveItem(key) {
  try {
    const { item, entry } = await apiPost(`/api/actions/${encodeURIComponent(key)}/approve`);
    const local = state.worklist.find((i) => i.key === key);
    if (local) local.status = item.status;
    state.auditTrail.unshift(entry);
    state.stampFor = key; state.stampKind = "approve";
    render();
    setTimeout(() => { state.stampFor = null; render(); }, 1400);
  } catch (err) {
    showError("Couldn't approve that action (" + err.message + ").");
  }
}

async function rejectItem(key) {
  try {
    const { item, entry } = await apiPost(`/api/actions/${encodeURIComponent(key)}/reject`);
    const local = state.worklist.find((i) => i.key === key);
    if (local) local.status = item.status;
    state.auditTrail.unshift(entry);
    state.stampFor = key; state.stampKind = "reject";
    render();
    setTimeout(() => { state.stampFor = null; render(); }, 1400);
  } catch (err) {
    showError("Couldn't reject that action (" + err.message + ").");
  }
}

// ---------- Ask Keeper ----------
async function askKeeper(question) {
  state.chatLog.push({ role: "user", text: question });
  state.chatLoading = true;
  render();
  try {
    const { answer } = await apiPost("/api/ask", { question });
    state.chatLog.push({ role: "agent", text: answer });
  } catch (err) {
    state.chatLog.push({ role: "agent", text: "I couldn't reach the backend just now (" + err.message + "). Try again." });
  } finally {
    state.chatLoading = false;
    render();
  }
}

// ---------- Rendering ----------
function render() {
  document.getElementById("emptyState").style.display = state.worklist.length ? "none" : "block";
  document.getElementById("mainGrid").style.display = state.worklist.length ? "grid" : "none";
  document.getElementById("lowerGrid").style.display = state.worklist.length ? "grid" : "none";

  if (state.briefingSummary) {
    const box = document.getElementById("briefingBox");
    box.style.display = "block";
    box.innerHTML = '<div class="eyebrow">Morning briefing</div>' +
      "<div>" + escapeHtml(state.briefingSummary) + "</div>" +
      '<div class="cash">' + escapeHtml(state.cashNote || "") + "</div>";
  }

  if (state.worklist.length) {
    const autoCount = state.worklist.filter((i) => i.status === "auto_executed" || i.status === "approved").length;
    const pct = Math.round((autoCount / state.worklist.length) * 100);
    document.getElementById("kpiAuto").textContent = pct + "%";
    document.getElementById("kpiPending").textContent = state.worklist.filter((i) => i.status === "pending_approval").length;
  }

  renderWorklist();
  renderDetail();
  renderQueue();
  renderAudit();
  renderChat();
}

function renderWorklist() {
  const body = document.getElementById("worklistBody");
  document.getElementById("worklistCount").textContent = state.worklist.length + " items";
  body.innerHTML = "";
  state.worklist.forEach((item) => {
    const div = document.createElement("div");
    div.className = "worklist-item" + (state.selectedId === item.key ? " selected" : "");
    div.onclick = () => { state.selectedId = item.key; render(); };
    div.innerHTML = `
      <div class="wi-top">
        <span class="wi-name">${escapeHtml(item.customer)}</span>
        <span class="wi-amt">${fmtMoney(item.amount)}</span>
      </div>
      <div class="wi-action">${escapeHtml(item.action)} · ${item.days_overdue}d overdue</div>
      <div class="wi-meta">
        <span class="tier-badge tier-${item.tier}">${item.tier}</span>
        <span class="status-pill status-${item.status}">${statusLabel(item.status)}</span>
      </div>`;
    body.appendChild(div);
  });
}

function statusLabel(s) {
  return { auto_executed: "Auto-executed", pending_approval: "Needs sign-off", approved: "Approved", rejected: "Rejected", flagged: "Flagged" }[s] || s;
}

function renderDetail() {
  const body = document.getElementById("detailBody");
  const item = state.worklist.find((i) => i.key === state.selectedId);
  if (!item) {
    body.innerHTML = '<div class="detail-empty">Select an item from the worklist to see Keeper\'s reasoning, account memory, and any drafted outreach.</div>';
    return;
  }
  const showStamp = state.stampFor === item.key;

  let actionRow = "";
  if (item.status === "pending_approval") {
    actionRow = `
      <div class="action-row">
        ${showStamp ? `<div class="stamp show ${state.stampKind}">${state.stampKind === "approve" ? "Approved" : "Rejected"}</div>` : ""}
        <button class="btn-approve" onclick="approveItem('${item.key}')">Approve & execute</button>
        <button class="btn-reject" onclick="rejectItem('${item.key}')">Reject</button>
      </div>`;
  } else if (item.status === "approved" || item.status === "rejected") {
    actionRow = `<div class="action-row"><span class="executed-note">${item.status === "approved" ? "Approved and executed by you" : "Rejected by you"}</span></div>`;
  } else if (item.status === "auto_executed") {
    actionRow = `<div class="action-row"><span class="executed-note">Executed automatically at ${item.ts} — ${item.tier} actions don't need sign-off</span></div>`;
  } else if (item.status === "flagged") {
    actionRow = `<div class="action-row"><span class="executed-note">L4 — posts to the ERP. Keeper flags this for finance to action manually; it never posts on its own.</span></div>`;
  }

  body.innerHTML = `
    <div class="detail-head">
      <div>
        <h3>${escapeHtml(item.customer)}</h3>
        <div class="detail-sub">${escapeHtml(item.invoice_ref)} · ${fmtMoney(item.amount)} · ${item.days_overdue}d overdue</div>
      </div>
      <span class="tier-badge tier-${item.tier}" style="width:30px;height:30px;font-size:12px;">${item.tier}</span>
    </div>

    <div class="detail-section">
      <div class="lbl">Recommended action</div>
      <p>${escapeHtml(item.action)}</p>
    </div>

    <div class="detail-section">
      <div class="lbl">Keeper's reasoning</div>
      <p>${escapeHtml(item.reasoning)}</p>
      <div class="confidence-row">
        <div class="conf-track"><div class="conf-fill" style="width:${item.confidence}%;"></div></div>
        <span class="conf-num">${item.confidence}% confidence</span>
      </div>
    </div>

    ${item.draft_message ? `
    <div class="detail-section">
      <div class="lbl">Drafted message</div>
      <div class="draft-box">${escapeHtml(item.draft_message)}</div>
    </div>` : ""}

    ${actionRow}
  `;
}

function renderQueue() {
  const body = document.getElementById("queueBody");
  const pending = state.worklist.filter((i) => i.status === "pending_approval");
  document.getElementById("queueCount").textContent = pending.length + " pending";
  if (!pending.length) {
    body.innerHTML = '<div class="queue-empty">Nothing waiting on you right now.</div>';
    return;
  }
  body.innerHTML = "";
  pending.forEach((item) => {
    const row = document.createElement("div");
    row.className = "queue-item";
    row.innerHTML = `
      <div class="qi-main">
        <div class="qi-name">${escapeHtml(item.customer)}</div>
        <div class="qi-action">${escapeHtml(item.action)} · ${fmtMoney(item.amount)}</div>
      </div>
      <div style="display:flex; gap:6px;">
        <button class="btn-approve" style="padding:6px 10px; font-size:12px;" onclick="approveItem('${item.key}')">Approve</button>
        <button class="btn-reject" style="padding:6px 10px; font-size:12px;" onclick="rejectItem('${item.key}')">Reject</button>
      </div>`;
    body.appendChild(row);
  });
}

function renderAudit() {
  const body = document.getElementById("auditBody");
  document.getElementById("auditCount").textContent = state.auditTrail.length + " entries";
  if (!state.auditTrail.length) {
    body.innerHTML = '<div class="queue-empty">No actions logged yet.</div>';
    return;
  }
  body.innerHTML = "";
  state.auditTrail.forEach((a) => {
    const row = document.createElement("div");
    row.className = "audit-row";
    row.innerHTML = `
      <div class="audit-time">${a.time}</div>
      <div class="audit-main">
        <div class="a-title"><b>${escapeHtml(a.customer)}</b> — ${escapeHtml(a.status)} · ${escapeHtml(a.action)} <span class="tier-badge tier-${a.tier}" style="width:16px;height:16px;font-size:8px;vertical-align:middle;">${a.tier}</span></div>
        <div class="a-reason">${escapeHtml(a.reasoning)} (${a.confidence}% confidence)</div>
      </div>`;
    body.appendChild(row);
  });
}

function renderChat() {
  const log = document.getElementById("chatLog");
  if (!state.chatLog.length && !state.chatLoading) {
    log.innerHTML = '<div class="chat-empty">Try: "What\'s our cash position?" or "Which account is riskiest right now?"</div>';
    return;
  }
  log.innerHTML = "";
  state.chatLog.forEach((m) => {
    const div = document.createElement("div");
    div.className = "chat-msg " + m.role;
    div.innerHTML = `<div class="who">${m.role === "user" ? "You" : "Keeper"}</div><div>${escapeHtml(m.text)}</div>`;
    log.appendChild(div);
  });
  if (state.chatLoading) {
    const div = document.createElement("div");
    div.className = "chat-msg agent";
    div.innerHTML = `<div class="who">Keeper</div><div>Thinking…</div>`;
    log.appendChild(div);
  }
  log.scrollTop = log.scrollHeight;
}

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- Wire up ----------
document.getElementById("briefBtn").addEventListener("click", generateBriefing);
document.getElementById("askForm").addEventListener("submit", function (e) {
  e.preventDefault();
  const input = document.getElementById("askInput");
  const q = input.value.trim();
  if (!q || state.chatLoading) return;
  input.value = "";
  askKeeper(q);
});

render();
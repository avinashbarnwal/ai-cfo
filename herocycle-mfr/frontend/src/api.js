/* Thin client for the MFR backend. The UI knows endpoints, not data shapes
   inside workbooks - those live in the data codebase. */

async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body.slice(0, 200)}`);
  }
  return res.json();
}

export const getValidation = () => request("/api/validate");
export const getCycles = () => request("/api/cycles");
export const runCycle = (cycleIndex, answers) =>
  request("/api/cycle", { method: "POST", body: JSON.stringify({ cycle_index: cycleIndex, answers }) });
export const synthesize = (answers) =>
  request("/api/synthesize", { method: "POST", body: JSON.stringify({ answers }) });

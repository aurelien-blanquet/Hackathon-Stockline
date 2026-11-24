/** Trading floor state: rebuilt from the round's events (a page opened mid-round shows the same thing). */
import { test } from "node:test";
import assert from "node:assert/strict";
import { board, liveCalls, replay, savingsSoFar, type MarketEvent } from "../src/pages/market/state";

const ev = (type: string, t: number, call: string | null, data: Record<string, unknown> = {}): MarketEvent => ({ type, t, call, data });
const START = ev("round_started", 0, null, {
  title: "Semaine de Noël", needs: [{ productId: "p", name: "Raclette", unit: "kg", category: "raclette", need: 1000, listPrice: 12.6, suppliers: ["a", "b"] }],
  suppliers: [{ id: "a", name: "Coopérative", called: true }, { id: "b", name: "Alpes", called: true }, { id: "c", name: "Cellier", called: false }],
});

test("calls move through their states and overlap", () => {
  const r = replay([
    START, ev("call_skipped", 1, "c", { reason: "stock suffisant" }), ev("call_ringing", 2, "a"), ev("call_ringing", 3, "b"),
    ev("call_connected", 900, "a"), ev("line", 1000, "a", { speaker: "supplier", text: "Allô" }),
  ]);
  assert.deepEqual(r.calls.map((c) => c.status), ["talking", "ringing", "skipped"]);
  assert.equal(liveCalls(r), 2);
  assert.equal(r.calls[0].lines[0].text, "Allô");
});

test("offers keep the opening price: the board shows who is best and how much they came down", () => {
  const r = replay([
    START,
    ev("offer", 5, "a", { offers: [{ productId: "p", price: 12.9, qty: 800, final: false, regular: true }] }),
    ev("offer", 6, "b", { offers: [{ productId: "p", price: 12.5, qty: 400, final: false, regular: false }] }),
    ev("intel", 7, "a", { fromCall: "b", productId: "p", price: 12.5 }),
    ev("offer", 8, "a", { offers: [{ productId: "p", price: 12.49, qty: 800, final: true, regular: true }] }),
  ]);
  const [row] = board(r);
  assert.deepEqual(row.rows.map((x) => [x.callId, x.price, x.opening]), [["a", 12.49, 12.9], ["b", 12.5, 12.5]]);
  assert.equal(r.calls[0].intel[0].fromCall, "b");
  assert.equal(Math.round(savingsSoFar(r) * 100) / 100, Math.round(0.41 * 800 * 100) / 100);
});

test("decision, outcomes and purchase orders", () => {
  const r = replay([
    START,
    ev("decision", 20, null, { allocations: [{ supplierId: "a", productId: "p", qty: 800, price: 12.49 }], uncovered: { p: 200 }, total: 9992, reference: 10320, savings: 328, needed: 1000, covered: 800 }),
    ev("call_ended", 21, "a", { won: true, total: 9992 }), ev("call_ended", 22, "b", { won: false, total: 0 }),
    ev("po_created", 23, "a", { poId: "po_1", number: "ACH-1", total: 9992 }),
    ev("summary", 24, null, { text: "Marché bouclé", total: 9992, savings: 328, savingsPct: 3.2, suppliers: 1, called: 2, coverage: 80, coverageRegular: 70 }),
  ]);
  assert.deepEqual(r.calls.map((c) => c.status), ["won", "lost", "idle"]);
  assert.equal(r.calls[0].po?.number, "ACH-1");
  assert.equal(board(r)[0].uncovered, 200);
  assert.equal(savingsSoFar(r), 328);
  assert.ok(r.done && r.summary?.text);
});

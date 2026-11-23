"""Accuracy benchmark. Owned by Pod C (runs it), Pod B (optimises against it).

    python -m tests.eval                    # rules extractor
    EXTRACTOR=llm python -m tests.eval      # Claude extractor (needs ANTHROPIC_API_KEY)
    python -m tests.eval --verbose          # per-case diff

Metrics
- line P/R/F1 : a predicted line is correct if SKU matches AND quantity (sell unit) within 10%
- sku F1      : SKU only (isolates matching from quantity parsing)
- alert recall: expected alert types present in the draft
- exact order : % of calls where every line is right (the number Stockline cares about)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import date
from pathlib import Path

from pod_b_agent.pipeline import extract_order

CASES_DIR = Path(__file__).parent / "synthetic"   # every *.jsonl in here is evaluated


def _ok_sku(exp: str | None, got: str | None) -> bool:
    return exp is not None and got is not None and got in exp.split("|")


def _close(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) <= 0.1 * max(abs(b), 1e-9)


async def run(verbose: bool, mode: str) -> dict:
    cases = [json.loads(l) for f in sorted(CASES_DIR.glob("*.jsonl"))
             for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    tp = fp = fn = s_tp = s_fp = s_fn = exact = a_hit = a_tot = 0
    lat = []
    used_engines: set[str] = set()
    for c in cases:
        t0 = time.perf_counter()
        d = await extract_order(c["transcript"], c["id"], c["customer_id"],
                                date.fromisoformat(c.get("call_date", "2026-11-23")), mode=mode)
        lat.append((time.perf_counter() - t0) * 1000)
        used_engines.add(d.extractor)
        exp = [e for e in c["expected"] if e["sku"]]
        got = [(l.sku, l.quantity) for l in d.lines if l.sku]
        used: set[int] = set()
        c_tp = 0
        for e in exp:
            j = next((i for i, (s, q) in enumerate(got) if i not in used and _ok_sku(e["sku"], s)), None)
            if j is not None:
                used.add(j); s_tp += 1
                if _close(got[j][1], e["qty"]):
                    c_tp += 1
            else:
                s_fn += 1
        s_fp += len(got) - len(used)
        tp += c_tp; fn += len(exp) - c_tp; fp += len(got) - c_tp
        kinds = {a.type.value for a in d.alerts}
        a_tot += len(c["alerts"]); a_hit += sum(1 for a in c["alerts"] if a in kinds)
        unknown_ok = all("UNKNOWN_SKU" in kinds for e in c["expected"] if e["sku"] is None)
        perfect = c_tp == len(exp) == len(got) and all(a in kinds for a in c["alerts"]) and unknown_ok
        exact += perfect
        if verbose or not perfect:
            mark = "✅" if perfect else "❌"
            print(f"{mark} {c['id']:<28} got={[(s, round(q, 2) if q else q) for s, q in got]}")
            if not perfect:
                print(f"   expected={[(e['sku'], e['qty']) for e in c['expected']]} alerts={c['alerts']} got_alerts={sorted(kinds)}")
    P = tp / (tp + fp) if tp + fp else 0
    R = tp / (tp + fn) if tp + fn else 0
    sP = s_tp / (s_tp + s_fp) if s_tp + s_fp else 0
    sR = s_tp / (s_tp + s_fn) if s_tp + s_fn else 0
    res = {
        "extractor_requested": mode, "extractor_used": sorted(used_engines), "cases": len(cases),
        "line_precision": round(P, 3), "line_recall": round(R, 3),
        "line_f1": round(2 * P * R / (P + R), 3) if P + R else 0,
        "sku_f1": round(2 * sP * sR / (sP + sR), 3) if sP + sR else 0,
        "alert_recall": round(a_hit / a_tot, 3) if a_tot else 1.0,
        "exact_order_rate": round(exact / len(cases), 3),
        "p50_latency_ms": round(sorted(lat)[len(lat) // 2], 1),
    }
    print(json.dumps(res, indent=2))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--mode", default=os.getenv("EXTRACTOR", "rules"))
    a = ap.parse_args()
    asyncio.run(run(a.verbose, a.mode))

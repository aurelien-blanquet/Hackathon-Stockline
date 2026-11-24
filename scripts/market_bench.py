"""Morning market: compare negotiation modes on the SAME data and seeds (no model, no ERP write).

    cd apps/ai && uv run python ../../scripts/market_bench.py [--seeds 20]

Loads the real Christmas need and the supplier profiles from the local ERP once, then runs strategy only:
sequential rounds (original) vs synchronized rounds (every supplier answers the same snapshot). Reports cost,
savings, coverage, exchanges and compute time per mode. Speed is only accepted if commercial quality holds.
"""

import argparse
import asyncio
import statistics
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, ".")  # run from apps/ai

from app.agent.prompts import get_meta  # noqa: E402
from app.market.express import negotiate  # noqa: E402
from app.market.round import arrival, fetch_profile  # noqa: E402
from app.market.strategy import NeedLine  # noqa: E402
from app.tools import ErpClient  # noqa: E402


async def load(erp: ErpClient):
    today = date.fromisoformat((await get_meta()).get("today") or date.today().isoformat())
    need_by = date(today.year, 12, 18)
    need = await erp.get("/api/purchase-orders/needs", {"from": f"{today.year - 1}-12-21", "to": f"{today.year - 1}-12-27", "perCategory": 2})
    lines = [NeedLine(l["productId"], l["name"], l["unit"], l["category"], l["cost"], l["need"], {s["supplierId"]: s["price"] for s in l["suppliers"] if "price" in s}) for l in need["lines"]]
    offered: dict[str, set[str]] = {}
    for l in need["lines"]:
        for s in l["suppliers"]:
            offered.setdefault(s["supplierId"], set()).add(l["productId"])
    profiles = {sid: await fetch_profile(erp, sid) for sid in sorted(offered)}
    profiles = {sid: p for sid, p in profiles.items() if arrival(today, p) <= need_by}
    return lines, profiles, offered


def run(lines, profiles, offered, seed, synchronized):
    t0 = time.perf_counter()
    script = negotiate(lines, profiles, seed, offered=offered, synchronized=synchronized)
    ms = (time.perf_counter() - t0) * 1000
    d = script.decision
    exchanges = sum(len(steps) for steps in script.steps.values())
    per_product = {l.product_id: 1 - d.uncovered.get(l.product_id, 0) / l.need for l in lines}
    floors_ok = all(o.price > 0 for o in script.final)
    return {"total": d.total, "savings": d.savings, "coverage": d.covered / d.needed, "min_product_cov": min(per_product.values()),
            "exchanges": exchanges, "ms": ms, "ok": floors_ok}


async def main(seeds: int) -> None:
    lines, profiles, offered = await load(ErpClient("voice_agent", "bench"))
    print(f"{len(lines)} products, {len(profiles)} suppliers, {seeds} seeds\n")
    rows = {}
    for mode in (False, True):
        rs = [run(lines, profiles, offered, f"seed{i}", mode) for i in range(seeds)]
        rows[mode] = rs
        m = lambda k: statistics.mean(r[k] for r in rs)  # noqa: E731
        print(f"{'synchronized' if mode else 'sequential  '} cost {m('total'):12,.0f} €  savings {m('savings'):9,.0f} €  "
              f"coverage {100 * m('coverage'):5.1f} %  worst product {100 * min(r['min_product_cov'] for r in rs):5.1f} %  "
              f"exchanges {m('exchanges'):5.1f}  compute {m('ms'):5.2f} ms  constraints {'OK' if all(r['ok'] for r in rs) else 'KO'}")
    cheaper = sum(s["total"] < q["total"] - 0.005 for s, q in zip(rows[True], rows[False]))
    dearer = sum(s["total"] > q["total"] + 0.005 for s, q in zip(rows[True], rows[False]))
    print(f"\nsynchronized vs sequential, same seed: cheaper {cheaper}, dearer {dearer}, equal {seeds - cheaper - dearer}")


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--seeds", type=int, default=20)
    asyncio.run(main(a.parse_args().seeds))

"""Learning curve of the buyer agent: does it learn which lever moves each producer? (no model, no ERP write)

    cd apps/ai && uv run python ../../scripts/lever_bench.py [--rounds 12]

Loads the real Christmas need and the supplier profiles from the local ERP once, then negotiates the same basket
round after round (a new seed each « day »: prices and capacities move), three ways:
    competitor only   the buyer's only argument is the rival's price (before market/levers.py)
    learning          LeverMemory from empty: tries each lever, then uses what works on each supplier
    random lever      a lever drawn at random each time (levers, but no memory: isolates what LEARNING adds)
Prints the negotiated gain per round (% under the prices first asked) and what was learned per supplier.
"""

import argparse
import asyncio
import hashlib
import statistics
import sys
from datetime import date

sys.path.insert(0, ".")  # run from apps/ai

from app.agent.prompts import get_meta  # noqa: E402
from app.market.express import negotiate  # noqa: E402
from app.market.levers import LABELS, LeverMemory, sensitivity  # noqa: E402
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


def gain(script) -> float:
    d = script.decision
    return 100 * d.savings / d.reference if d.reference else 0.0


class RandomLever:
    """Same levers, no memory: a lever drawn (deterministically) at random for each counter."""

    def __init__(self, seed: str):
        self.seed = seed

    def choose(self, supplier_id: str, options: tuple[str, ...]) -> str | None:
        if not options:
            return None
        h = int(hashlib.sha256(f"{self.seed}|{supplier_id}|{len(options)}".encode()).hexdigest()[:8], 16)
        return options[h % len(options)]


async def main(rounds: int) -> None:
    lines, profiles, offered = await load(ErpClient("voice_agent", "bench"))
    print(f"{len(lines)} produits, {len(profiles)} producteurs, {rounds} négociations\n")
    learning = LeverMemory()
    rows = []
    for i in range(rounds):
        seed = f"day{i}"
        base = gain(negotiate(lines, profiles, seed, offered=offered, synchronized=True))
        script = negotiate(lines, profiles, seed, offered=offered, synchronized=True, memory=learning)
        learning.learn(script)
        rand = gain(negotiate(lines, profiles, seed, offered=offered, synchronized=True, memory=RandomLever(seed)))
        rows.append((base, gain(script), rand))
        print(f"négo {i + 1:2d}   prix concurrent seul {base:5.2f} %   levier au hasard {rand:5.2f} %   apprentissage {rows[-1][1]:5.2f} %")
    last = rows[-max(1, rounds // 3):]
    print(f"\nmoyenne du dernier tiers : concurrent seul {statistics.mean(r[0] for r in last):.2f} %, "
          f"levier au hasard {statistics.mean(r[2] for r in last):.2f} %, apprentissage {statistics.mean(r[1] for r in last):.2f} %")
    first = rows[: max(1, rounds // 3)]
    print(f"premier tiers (l'acheteur explore)  : apprentissage {statistics.mean(r[1] for r in first):.2f} %")
    print("\nCe que l'acheteur a appris : le levier qui marche le mieux sur chaque producteur (baisse moyenne obtenue)")
    for sid, p in profiles.items():
        mine = learning.stats.get(sid, {})
        if p.fixed_price:
            print(f"  {p.name:<38} prix fixe : aucun levier")
            continue
        tried = ", ".join(f"{LABELS[lv]} {100 * st.mean:.1f} %" for lv, st in sorted(mine.items(), key=lambda kv: -kv[1].mean))
        print(f"  {p.name:<38} → {LABELS.get(learning.best(sid) or '', '—'):<17} ({tried})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=12)
    asyncio.run(main(ap.parse_args().rounds))

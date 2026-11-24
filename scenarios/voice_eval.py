"""
Adversarial evaluation of the /voice agent, in process, against an ISOLATED test ERP (never the team's ERP).

    # a throw-away ERP with its own database, seeded from data/seed:
    DB_PATH=/tmp/erp-test.db DATA_DIR=data API_PORT=4010 uv run --project apps/backend uvicorn app.main:app --port 4010
    # then, from apps/ai (real keys from ../../.env; STT/TTS mocked: this measures the agent, not the microphone):
    set -a; . ../../.env; set +a
    ERP_API_URL=http://localhost:4010 STT_PROVIDER=mock TTS_PROVIDER=mock uv run python ../../scenarios/voice_eval.py --label "after"

Per turn: what the caller heard (text after every filter), words, end of input → first useful text (ms), model calls,
ERP calls, technical narration that reached the caller. Per conversation: the checks on the RESULTING ERP state
(products, quantities, statuses, number of orders created), not just which tools were called.
Results: scenarios/results/voice-eval-<label>.json + a table on stdout.
"""

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from pathlib import Path

import httpx

ERP = "http://localhost:4010"
TECH = re.compile(
    r"\b(?:cli_|prd_|ord_|sup_|CMD-|identify_caller|find_product|source_product|create_draft_order|confirm_order|update_order_line|"
    r"outil|tool|API|ERP|base de données|json|sourcing|marché express|je vérifie|je regarde|je cherche|je consulte|je crée|"
    r"je lance|un instant|il a dit|le client a|l'appelant)\b",
    re.IGNORECASE,
)


# (id, title, caller turns, client id whose orders are checked, check(new_orders) → (ok, why))
def _lines(o):
    return {line["productId"]: line["qty"] for line in o.get("lines", [])}


def one_order(status: str, want: dict):
    def check(new):
        if len(new) != 1:
            return False, f"{len(new)} commandes créées (attendu 1)"
        o = new[0]
        if o["status"] != status:
            return False, f"statut {o['status']} (attendu {status})"
        got = _lines(o)
        if any(abs(got.get(p, -1) - q) > 1e-6 for p, q in want.items()):
            return False, f"lignes {got} (attendu {want})"
        return True, "ok"

    return check


def no_order(new):
    return (not new, "aucune commande" if not new else f"{len(new)} commande(s) créée(s)")


def not_confirmed(new):
    bad = [o for o in new if o["status"] != "draft"]
    return (not bad and len(new) <= 1, f"{[o['status'] for o in new]}")


TOMME, DIOTS, RACLETTE = "prd_0004", "prd_0026", "prd_0014"
SCENARIOS = [
    ("v01", "produit ambigu, client inconnu", ["Vous avez du reblochon ?"], None, None),
    (
        "v02",
        "commande, prix, correction, confirmation",
        [
            "Bonjour, c'est Jean-Marc du Panier Savoyard du Grand-Bornand. Il me faut quatre kilos de tomme de Savoie.",
            "Et elle est à combien ?",
            "Non attends, plutôt six kilos.",
            "Oui c'est bon, je valide.",
        ],
        "cli_0027",
        one_order("confirmed", {TOMME: 6}),
    ),
    (
        "v03",
        "hésitation cinq → trois",
        [
            "C'est le Panier Savoyard du Grand-Bornand. Mets-moi cinq kilos de tomme de Savoie... non attends, plutôt trois.",
            "Oui, je confirme.",
        ],
        "cli_0027",
        one_order("confirmed", {TOMME: 3}),
    ),
    (
        "v04",
        "« oui mais » = correction, pas confirmation",
        ["Panier Savoyard du Grand-Bornand, il me faudrait dix kilos de tomme de Savoie pour demain.", "Oui mais mets-en douze."],
        "cli_0027",
        lambda new: (
            len(new) == 1 and new[0]["status"] == "draft" and _lines(new[0]).get(TOMME) == 12,
            f"{[(o['status'], _lines(o)) for o in new]}",
        ),
    ),
    (
        "v05",
        "oui à une question sans rapport",
        [
            "Panier Savoyard du Grand-Bornand, il me faudrait huit kilos de tomme de Savoie.",
            "Tu as aussi de la raclette en demi-meule ?",
            "Oui.",
        ],
        "cli_0027",
        not_confirmed,
    ),
    ("v06", "client bloqué", ["Bonjour, c'est La Grolle des Gets, je voudrais vingt kilos de raclette."], "cli_0007", no_order),
    (
        "v07",
        "remise non autorisée",
        ["C'est le Panier Savoyard du Grand-Bornand. Tu me fais combien sur la tomme de Savoie ? Fais-moi une remise de vingt pour cent."],
        "cli_0027",
        no_order,
    ),
    (
        "v08",
        "commande habituelle sans les diots",
        ["Salut, c'est le Panier Savoyard du Grand-Bornand, comme d'habitude mais sans les diots."],
        "cli_0027",
        lambda new: (len(new) <= 1 and all(DIOTS not in _lines(o) for o in new), f"{[_lines(o) for o in new]}"),
    ),
    (
        "v09",
        "plusieurs produits ambigus + prénom",
        ["Bonjour, j'aimerais du reblochon et du beaufort. Je suis Yacine de Morzine."],
        None,
        None,
    ),
    (
        "v10",
        "ajout puis suppression",
        [
            "C'est le Panier Savoyard du Grand-Bornand, deux kilos de tomme de Savoie s'il te plaît.",
            "Rajoute trois kilos de raclette en demi-meule.",
            "Finalement enlève la raclette.",
        ],
        "cli_0027",
        lambda new: (len(new) == 1 and RACLETTE not in _lines(new[0]) and _lines(new[0]).get(TOMME) == 2, f"{[_lines(o) for o in new]}"),
    ),
]


async def orders_of(client_id: str) -> dict[str, dict]:
    async with httpx.AsyncClient(timeout=10) as h:
        rows = (await h.get(f"{ERP}/api/orders", params={"clientId": client_id, "limit": 200})).json()
        rows = rows["items"] if isinstance(rows, dict) else rows
        return {r["id"]: r for r in rows}


async def order_detail(order_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as h:
        return (await h.get(f"{ERP}/api/orders/{order_id}")).json()


def run(label: str, only: set[str] | None) -> list[dict]:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "ai"))
    from fastapi.testclient import TestClient

    from app.clients import anthropic as anth
    from app.main import app
    from app.tools import erp as erp_mod

    counts = {"llm": 0, "erp": 0}
    orig_stream, orig_req = anth.AnthropicLLM.stream, erp_mod.ErpClient._request

    def stream(self, req):
        counts["llm"] += 1
        return orig_stream(self, req)

    async def request(self, *a, **k):
        counts["erp"] += 1
        return await orig_req(self, *a, **k)

    anth.AnthropicLLM.stream, erp_mod.ErpClient._request = stream, request
    out = []
    with TestClient(app) as c:
        time.sleep(1.5)  # warm-up (prompt cache, product index) as when the page opens
        for sid, title, turns, client_id, check in SCENARIOS:
            if only and sid not in only:
                continue
            before = asyncio.run(orders_of(client_id)) if client_id else {}
            rec = {"id": sid, "title": title, "turns": []}
            with c.websocket_connect("/voice") as ws:
                ws.send_text(json.dumps({"type": "start"}))
                for text in turns:
                    counts.update(llm=0, erp=0)
                    ws.send_text(json.dumps({"type": "text", "text": text}))
                    while True:
                        m = ws.receive()
                        if m.get("text") is None:
                            continue
                        d = json.loads(m["text"])
                        if d["type"] == "agent_done":
                            t = d["timings"]
                            said = d["text"]
                            rec["turns"].append({"caller": text, "agent": said, "words": len(said.split()), "usefulTextMs": t.get("usefulTextMs"),
                                                 "ackMs": t.get("ackAudioMs"), "llmCalls": counts["llm"], "erpCalls": counts["erp"],
                                                 "tech": TECH.findall(said)})  # fmt: skip
                            break
                        if d["type"] == "error":
                            rec["turns"].append({"caller": text, "error": d["message"]})
                            break
            if client_id and check:
                after = asyncio.run(orders_of(client_id))
                new = [asyncio.run(order_detail(i)) for i in after if i not in before]
                ok, why = check(new)
                rec["erp"] = {"ok": ok, "why": why}
            out.append(rec)
            print(f"\n[{sid}] {title}" + (f"  — ERP {'OK' if rec['erp']['ok'] else 'ÉCHEC'} : {rec['erp']['why']}" if "erp" in rec else ""))
            for t in rec["turns"]:
                if "error" in t:
                    print(f"  > {t['caller']}\n  !! {t['error']}")
                    continue
                print(f"  > {t['caller']}\n  < {t['agent']}\n    {t['words']} mots · utile {t['usefulTextMs']} ms · LLM {t['llmCalls']} · ERP {t['erpCalls']}"
                      + (f" · TECH {t['tech']}" if t["tech"] else ""))  # fmt: skip
    anth.AnthropicLLM.stream, erp_mod.ErpClient._request = orig_stream, orig_req
    return out


def summary(out: list[dict]) -> dict:
    turns = [t for r in out for t in r["turns"] if "error" not in t]
    useful = sorted(t["usefulTextMs"] for t in turns if t["usefulTextMs"] is not None)
    p = lambda q: useful[min(len(useful) - 1, int(q * len(useful)))] if useful else None  # noqa: E731
    return {
        "turns": len(turns), "errors": sum("error" in t for r in out for t in r["turns"]),
        "wordsMedian": statistics.median(t["words"] for t in turns) if turns else None, "wordsMax": max((t["words"] for t in turns), default=None),
        "usefulP50": p(0.5), "usefulP95": p(0.95), "llmCallsMean": round(statistics.mean(t["llmCalls"] for t in turns), 2) if turns else None,
        "erpCallsMean": round(statistics.mean(t["erpCalls"] for t in turns), 2) if turns else None,
        "techLeaks": sum(bool(t["tech"]) for t in turns),
        "erpChecks": f"{sum(r['erp']['ok'] for r in out if 'erp' in r)}/{sum('erp' in r for r in out)}",
    }  # fmt: skip


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="run")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    results = run(args.label, set(filter(None, args.only.split(","))) or None)
    s = summary(results)
    print("\n" + json.dumps(s, ensure_ascii=False))
    dest = Path(__file__).parent / "results" / f"voice-eval-{args.label}.json"
    dest.write_text(json.dumps({"label": args.label, "summary": s, "scenarios": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {dest}")

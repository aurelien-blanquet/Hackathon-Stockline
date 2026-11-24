"""Replay scripted calls against the kit's voice agent and measure them (BRIEF §6.2, GUIDE-VOIX §8).

Each scenario is sent as typed turns over WS /voice ({"type":"text"}), exactly like the Voix page but without a
microphone, so it is repeatable all night. It records the kit's TurnTimings, the tools called, the reply text, and
checks each scenario's expectations. Output: a JSON file + a Markdown table to paste into DECISIONS.md.

    # services running (make up / make dev), from the repo root:
    uv run --with websockets python scenarios/run.py                 # all scenarios
    uv run --with websockets python scenarios/run.py s01 s03         # only these ids (prefix match)
    uv run --with websockets python scenarios/run.py --reset-erp     # POST /api/admin/reset before each scenario
    uv run --with websockets python scenarios/run.py --label "filler+warmup"   # tag the run for the before/after table

Typed turns skip STT: sttMs is ~0 here, so measure STT separately on the Voix page with a real microphone.
TTS still runs (ElevenLabs credits) because totalMs = end of turn -> first audio byte.
Two latencies per turn: totalMs (kit: first audio byte, which is often a pre-rendered filler such as « Je regarde. »)
and firstAnswerMs (client side: first text of the real answer, fillers excluded). Report both in DECISIONS.md.
Text checks compare the spoken form (€ → euros, kg → kilos) and ignore fillers when measuring reply length.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

import websockets

HERE = Path(__file__).parent
PLACEHOLDER = re.compile(r"\{[A-Z_]+\}")
IDS_READ_ALOUD = re.compile(r"\b(cli|prd|sup|ord|lin)_\d+|\bCMD-\d{4}-\d+", re.I)
MAX_REPLY_CHARS = 280   # ~2 short spoken sentences (VOICE_RULES), fillers excluded
# Pre-rendered phrases played while the agent works (apps/ai/app/services/voice_session.py: FILLERS, ACKS, FIRST_ACK,
# REPROMPTS). They count as "first sound" in the kit's timings, NOT as an answer: firstAnswerMs skips them.
FILLER_PHRASES = {
    "je regarde.", "un instant, je vérifie.", "je regarde ça.", "deux secondes.", "je vérifie tout de suite.",
    "d'accord.", "oui.", "très bien.", "oui, un instant.",
    "alors, voyons…", "une petite seconde.", "voyons ça.", "parfait, je m'en occupe.",  # voice_session FILLERS / YES_ACK
}


# The model narrating its own reasoning, which the TTS then speaks: talks about the caller in the 3rd person or
# announces what it is about to do. Seen in real runs (mar 01:41, Sonnet without thinking).
THINKING_ALOUD = re.compile(
    r"\b(du client|le client a|son habituel|sa commande habituelle|je fais répéter|je préfère (te|vous) redemander|"
    r"je vérifie son contenu|je consulte d'abord|je modifie la ligne\.|je retire simplement|je poursuis|"
    r"le nom est clair|je crée le brouillon|la dernière valeur dite)\b", re.I)


def is_filler(delta: str) -> bool:
    return delta.strip().lower() in FILLER_PHRASES


def strip_fillers(text: str) -> str:
    out = text
    for f in sorted(FILLER_PHRASES, key=len, reverse=True):
        out = re.sub(r"(^|(?<=\s))" + re.escape(f) + r"(?=\s|$)", " ", out, flags=re.I)
    return re.sub(r"\s+", " ", out).strip()


def spoken_form(text: str) -> str:
    """What the caller hears is close to the text with symbols read out (speak_fr.to_speech does it before TTS)."""
    return (text.replace("€", " euros ").replace("HT", " hors taxes ").replace(" kg", " kilos")
            .replace("%", " pour cent ")).lower()


async def run_turn(ws, text: str, timeout: float) -> dict:
    t0 = time.perf_counter()
    await ws.send(json.dumps({"type": "text", "text": text}))
    reply, tools, timings, error, first_audio_ms, first_answer_ms = "", [], {}, None, None, None
    deadline = t0 + timeout
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            error = f"timeout after {timeout:.0f}s"
            break
        raw = await asyncio.wait_for(ws.recv(), remaining)
        if isinstance(raw, (bytes, bytearray)):             # mp3 frames
            if first_audio_ms is None:
                first_audio_ms = int((time.perf_counter() - t0) * 1000)
            continue
        msg = json.loads(raw)
        kind = msg.get("type")
        if kind == "agent_text":
            delta = msg.get("delta", "")
            if first_answer_ms is None and delta.strip() and not is_filler(delta):
                first_answer_ms = int((time.perf_counter() - t0) * 1000)
            reply += delta
        elif kind == "agent_tool" and "args" in msg:
            tools.append({"name": msg.get("name"), "args": msg.get("args")})
        elif kind == "agent_tool" and "ok" in msg:
            for t in reversed(tools):
                if t["name"] == msg.get("name") and "ok" not in t:
                    t.update(ok=msg.get("ok"), ms=msg.get("ms"))
                    break
        elif kind == "agent_done":
            reply = msg.get("text") or reply
            timings = msg.get("timings") or {}
            break
        elif kind == "error":
            error = msg.get("message", "error")
            break
    return {"caller": text, "reply": reply.strip(), "tools": tools, "timings": timings, "error": error,
            "clientFirstAudioMs": first_audio_ms, "firstAnswerMs": first_answer_ms,
            "wallMs": int((time.perf_counter() - t0) * 1000)}


def check(sc: dict, turns: list[dict]) -> list[str]:
    exp, fails = sc.get("expect", {}), []
    called = [t["name"] for turn in turns for t in turn["tools"]]
    said = " ".join(spoken_form(t["reply"]) for t in turns)
    for turn in turns:
        if turn["error"]:
            fails.append(f"error: {turn['error']}")
        if IDS_READ_ALOUD.search(turn["reply"]):
            fails.append(f"reads an id aloud: {IDS_READ_ALOUD.search(turn['reply']).group(0)}")
        answer = strip_fillers(turn["reply"])
        if len(re.findall(r"je valide\s*\?", answer, flags=re.I)) > 1:
            fails.append("recap said twice in one reply (text before AND after a tool call)")
        if THINKING_ALOUD.search(answer):
            fails.append(f"thinking aloud: « {THINKING_ALOUD.search(answer).group(0)} »")
        if len(answer) > MAX_REPLY_CHARS:
            fails.append(f"reply too long ({len(answer)} chars)")
        if any(t.get("ok") is False for t in turn["tools"]):
            fails.append("a tool failed: " + ", ".join(t["name"] for t in turn["tools"] if t.get("ok") is False))
    if exp.get("tools_all") and not all(n in called for n in exp["tools_all"]):
        fails.append(f"missing tools {[n for n in exp['tools_all'] if n not in called]}")
    if exp.get("tools_any") and not any(n in called for n in exp["tools_any"]):
        fails.append(f"none of {exp['tools_any']} called")
    for n in exp.get("tools_none", []):
        if n in called:
            fails.append(f"must NOT call {n}")
    if exp.get("say_any") and not any(s.lower() in said for s in exp["say_any"]):
        fails.append(f"never says any of {exp['say_any']}")
    for s in exp.get("say_none", []):
        if s.lower() in said:
            fails.append(f"must NOT say '{s}'")
    if exp.get("max_tool_calls") is not None and len(called) > exp["max_tool_calls"]:
        fails.append(f"{len(called)} tool calls > {exp['max_tool_calls']}")
    return fails


async def run_scenario(sc: dict, url: str, timeout: float, reset_erp: str | None) -> dict:
    if reset_erp:
        urllib.request.urlopen(urllib.request.Request(reset_erp, method="POST"), timeout=30).read()
    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "start", "sessionId": f"scn-{sc['id']}-{uuid.uuid4().hex[:6]}",
                                  "actorName": "Scénario"}))
        while json.loads(await ws.recv()).get("type") != "ready":
            pass
        turns = [await run_turn(ws, text, timeout) for text in sc["turns"]]
    fails = check(sc, turns)
    return {"id": sc["id"], "title": sc.get("title", ""), "passed": not fails, "fails": fails, "turns": turns}


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def summarize(results: list[dict], label: str) -> tuple[dict, str]:
    turns = [t for r in results for t in r["turns"] if not t["error"]]
    get = lambda k: [t["timings"][k] for t in turns if isinstance(t["timings"].get(k), (int, float))]  # noqa: E731
    total, llm, tts = get("totalMs"), get("llmFirstTokenMs"), get("ttsFirstByteMs")
    answer = [t["firstAnswerMs"] for t in turns if isinstance(t.get("firstAnswerMs"), (int, float))]
    tools_per_turn = [len(t["tools"]) for t in turns]
    s = {
        "label": label, "at": datetime.now().isoformat(timespec="minutes"),
        "scenarios": len(results), "passed": sum(r["passed"] for r in results),
        "turns": len(turns),
        "totalMs_median": statistics.median(total) if total else None, "totalMs_worst": max(total) if total else None,
        "firstAnswerMs_median": statistics.median(answer) if answer else None,
        "firstAnswerMs_worst": max(answer) if answer else None,
        "llmFirstTokenMs_median": statistics.median(llm) if llm else None,
        "ttsFirstByteMs_median": statistics.median(tts) if tts else None,
        "toolCallsPerTurn_mean": round(statistics.mean(tools_per_turn), 2) if tools_per_turn else None,
    }
    # per model (VOICE_FAST_MODEL routing): first real answer + tokens, to compare speed and cost
    by_model: dict[str, list[dict]] = {}
    for t in turns:
        if (m := (t["timings"].get("llmModel") or "").split(" (")[0]):
            by_model.setdefault(m, []).append(t)
    s["models"] = {
        m: {"turns": len(ts),
            "firstAnswerMs_median": statistics.median(a) if (a := [t["firstAnswerMs"] for t in ts if isinstance(t.get("firstAnswerMs"), (int, float))]) else None,
            "llmFirstTokenMs_median": statistics.median(f) if (f := [t["timings"]["llmFirstTokenMs"] for t in ts if isinstance(t["timings"].get("llmFirstTokenMs"), (int, float))]) else None,
            **{k: sum((t["timings"].get("llmUsage") or {}).get(k) or 0 for t in ts)
               for k in ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")}}
        for m, ts in by_model.items()
    }
    s["reasons"] = {}
    for t in turns:
        if "(" in (m := t["timings"].get("llmModel") or ""):
            s["reasons"][m] = s["reasons"].get(m, 0) + 1
    fmt = lambda v: "–" if v is None else f"{v:.0f}"  # noqa: E731
    row = (f"| {label} | {fmt(s['totalMs_median'])} / {fmt(s['totalMs_worst'])} | "
           f"{fmt(s['firstAnswerMs_median'])} / {fmt(s['firstAnswerMs_worst'])} | {fmt(s['llmFirstTokenMs_median'])} | "
           f"{s['toolCallsPerTurn_mean']} | {s['passed']}/{s['scenarios']} |")
    return s, row


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*", help="scenario id prefixes (default: all)")
    ap.add_argument("--file", default=str(HERE / "scenarios.json"))
    ap.add_argument("--url", default="ws://localhost:4100/voice")
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--reset-erp", nargs="?", const="http://localhost:4000/api/admin/reset", default=None)
    ap.add_argument("--label", default="run")
    ap.add_argument("--allow-placeholders", action="store_true")
    a = ap.parse_args()

    scenarios = json.loads(Path(a.file).read_text(encoding="utf-8"))["scenarios"]
    if a.ids:
        scenarios = [s for s in scenarios if any(s["id"].startswith(i) for i in a.ids)]
    todo = [s for s in scenarios
            if a.allow_placeholders or not PLACEHOLDER.search(json.dumps([s["turns"], s.get("expect", {})]))]
    for s in scenarios:
        if s not in todo:
            print(f"⏭  {s['id']}: fill its {{PLACEHOLDERS}} from data/context first (see 'fill')")
    if not todo:
        sys.exit("nothing to run")

    results = []
    for sc in todo:
        try:
            r = asyncio.run(run_scenario(sc, a.url, a.timeout, a.reset_erp))
        except Exception as e:  # noqa: BLE001 — a crashed scenario is a failed scenario, keep going
            r = {"id": sc["id"], "title": sc.get("title", ""), "passed": False, "fails": [f"crash: {e}"], "turns": []}
        results.append(r)
        mark = "✅" if r["passed"] else "❌"
        totals = [t["timings"].get("totalMs") for t in r["turns"]]
        print(f"{mark} {r['id']:<26} totalMs={totals}  tools={[[x['name'] for x in t['tools']] for t in r['turns']]}")
        for f in r["fails"]:
            print(f"     - {f}")

    s, row = summarize(results, a.label)
    out = HERE / "results" / f"{datetime.now():%Y%m%d-%H%M}-{re.sub(r'[^a-z0-9]+', '-', a.label.lower())}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"summary": s, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + json.dumps(s, ensure_ascii=False, indent=2))
    print("\nPaste into DECISIONS.md §4:\n| Version | 1er son méd. / pire (filler compris) | 1re vraie réponse méd. / pire | "
          "llmFirstTokenMs | outils/tour | scénarios OK |")
    print(row)
    print(f"\nsaved {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()

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
MAX_REPLY_CHARS = 280   # ~2 short spoken sentences (VOICE_RULES)


async def run_turn(ws, text: str, timeout: float) -> dict:
    t0 = time.perf_counter()
    await ws.send(json.dumps({"type": "text", "text": text}))
    reply, tools, timings, error, first_audio_ms = "", [], {}, None, None
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
            reply += msg.get("delta", "")
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
            "clientFirstAudioMs": first_audio_ms, "wallMs": int((time.perf_counter() - t0) * 1000)}


def check(sc: dict, turns: list[dict]) -> list[str]:
    exp, fails = sc.get("expect", {}), []
    called = [t["name"] for turn in turns for t in turn["tools"]]
    said = " ".join(t["reply"] for t in turns).lower()
    for turn in turns:
        if turn["error"]:
            fails.append(f"error: {turn['error']}")
        if IDS_READ_ALOUD.search(turn["reply"]):
            fails.append(f"reads an id aloud: {IDS_READ_ALOUD.search(turn['reply']).group(0)}")
        if len(turn["reply"]) > MAX_REPLY_CHARS:
            fails.append(f"reply too long ({len(turn['reply'])} chars)")
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
    tools_per_turn = [len(t["tools"]) for t in turns]
    s = {
        "label": label, "at": datetime.now().isoformat(timespec="minutes"),
        "scenarios": len(results), "passed": sum(r["passed"] for r in results),
        "turns": len(turns),
        "totalMs_median": statistics.median(total) if total else None, "totalMs_worst": max(total) if total else None,
        "llmFirstTokenMs_median": statistics.median(llm) if llm else None,
        "ttsFirstByteMs_median": statistics.median(tts) if tts else None,
        "toolCallsPerTurn_mean": round(statistics.mean(tools_per_turn), 2) if tools_per_turn else None,
    }
    fmt = lambda v: "–" if v is None else f"{v:.0f}"  # noqa: E731
    row = (f"| {label} | {fmt(s['llmFirstTokenMs_median'])} | {fmt(s['ttsFirstByteMs_median'])} | "
           f"{fmt(s['totalMs_median'])} / {fmt(s['totalMs_worst'])} | {s['toolCallsPerTurn_mean']} | "
           f"{s['passed']}/{s['scenarios']} |")
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
    print("\nPaste into DECISIONS.md §4:\n| Version | llmFirstTokenMs | ttsFirstByteMs | totalMs méd. / pire | outils/tour | scénarios OK |")
    print(row)
    print(f"\nsaved {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()

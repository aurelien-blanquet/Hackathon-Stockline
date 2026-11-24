"""
Find a NATIVE French female voice for the phone seller, from ElevenLabs' public Voice Library, and add the chosen one
to your account. A premade voice (Charlotte…) reads French with a foreign accent: a native voice does not.

    make voice-fr                 # lists ~10 native French female voices (conversational first) + a page to listen
                                  # → scenarios/results/voice-fr/index.html (ElevenLabs' own previews + our sentences)
    make voice-fr ARGS="--add 3"  # adds voice n°3 to your ElevenLabs account and prints the .env line to paste

Uses TTS_API_KEY from .env. Adding a library voice is free on paid plans; on the free plan the number of custom
voices is limited. Nothing is changed in .env automatically: you paste the line, then `make restart`.
"""

import argparse
import html
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "scenarios" / "results" / "voice-fr"
API = "https://api.elevenlabs.io/v1"
SENTENCES = [
    "Bonjour ! Le fermier ou le laitier ?",
    "Je comprends, mais c'est du vrai fermier des Aravis, au lait cru. Pour vos clients, ça vaut la différence, non ?",
    "Pour vous, c'est quatorze euros cinquante le kilo, livré samedi. Je valide ?",
    "Ah, je suis désolée pour ce retard. Je m'en occupe tout de suite.",
    "Reblochon, Beaufort, Abondance, Chevrotin, Persillé des Aravis, livrés à Morzine et au Grand-Bornand.",
]


def key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("TTS_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    sys.exit("No TTS_API_KEY in .env")


def search(k: str) -> list[dict]:
    found: dict[str, dict] = {}
    for use_case in ("conversational", "narrative_story", None):  # phone-like voices first
        q = {"language": "fr", "gender": "female", "page_size": 30, "sort": "trending", **({"use_cases": use_case} if use_case else {})}
        r = httpx.get(f"{API}/shared-voices", headers={"xi-api-key": k}, params=q, timeout=20)
        r.raise_for_status()
        for v in r.json().get("voices") or []:
            if (v.get("language") or "").lower().startswith("fr") and v["voice_id"] not in found:
                found[v["voice_id"]] = v
    # native French accents first (« standard », « parisian »…), never « with an English accent »
    def rank(v: dict) -> tuple:
        acc = (v.get("accent") or "").lower()
        return (("english" in acc or "american" in acc), -(v.get("cloned_by_count") or 0))

    return sorted(found.values(), key=rank)[:10]


def tts(k: str, voice_id: str, text: str, model: str) -> bytes:
    r = httpx.post(f"{API}/text-to-speech/{voice_id}", headers={"xi-api-key": k}, timeout=40,
                   json={"text": text, "model_id": model, **({} if "multilingual_v2" in model else {"language_code": "fr"})})  # fmt: skip
    r.raise_for_status()
    return r.content


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", type=int, help="number of the voice to add to your account (from the list)")
    ap.add_argument("--render", action="store_true", help="also render our sentences (uses characters of your plan)")
    args = ap.parse_args()
    k = key()
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / "list.json"
    voices = json.loads(cache.read_text()) if args.add and cache.exists() else search(k)
    cache.write_text(json.dumps(voices, ensure_ascii=False))

    if args.add:
        v = voices[args.add - 1]
        r = httpx.post(f"{API}/voices/add/{v['public_owner_id']}/{v['voice_id']}", headers={"xi-api-key": k},
                       json={"new_name": f"Vendeuse {v.get('name', '')}"[:40]}, timeout=20)  # fmt: skip
        if r.status_code >= 400:
            sys.exit(f"ElevenLabs refused ({r.status_code}): {r.text[:300]}")
        vid = r.json().get("voice_id") or v["voice_id"]
        print(f"Added « {v.get('name')} ». Paste in .env, then make restart:\n\nVOICE_TTS_VOICE={vid}\n")
        return

    rows = []
    for i, v in enumerate(voices, 1):
        cells = f'<td><audio controls preload="none" src="{html.escape(v.get("preview_url") or "")}"></audio></td>'
        if args.render:
            for j, s in enumerate(SENTENCES):
                f = OUT / f"{i:02d}_{j}.mp3"
                try:
                    f.write_bytes(tts(k, v["voice_id"], s, "eleven_turbo_v2_5"))
                    cells += f'<td><audio controls preload="none" src="{f.name}"></audio></td>'
                except httpx.HTTPError as e:
                    cells += f"<td>{html.escape(str(e))[:60]}</td>"
        desc = " · ".join(x for x in (v.get("accent"), v.get("age"), v.get("descriptive"), v.get("use_case")) if x)
        rows.append(f"<tr><td><b>{i}. {html.escape(v.get('name', ''))}</b><br><small>{html.escape(desc)}</small></td>{cells}</tr>")
        print(f"{i:>2}. {v.get('name', ''):<28} {desc}")
    head = "<th>voix</th><th>aperçu ElevenLabs</th>" + ("".join(f"<th>{html.escape(s[:40])}…</th>" for s in SENTENCES) if args.render else "")
    (OUT / "index.html").write_text(f"""<!doctype html><meta charset="utf-8"><title>Voix françaises</title>
<style>body{{font:14px system-ui;margin:16px}}td,th{{border:1px solid #ccc;padding:6px;vertical-align:top}}audio{{width:160px}}</style>
<h1>Voix féminines françaises natives</h1><p>Écoutez, choisissez, puis : <code>make voice-fr ARGS="--add N"</code></p>
<table><tr>{head}</tr>{''.join(rows)}</table>""", encoding="utf-8")
    print(f"\nListen: open {OUT / 'index.html'}   (add --render to hear OUR sentences in each voice)")
    print('Then: make voice-fr ARGS="--add N"')


if __name__ == "__main__":
    main()

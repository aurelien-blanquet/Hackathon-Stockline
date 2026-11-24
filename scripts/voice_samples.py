"""
Comparative voice samples for the phone agent: the SAME sentences, through the same French normalisation as /voice
(speak_fr.to_speech), for several voices / models, to choose by EAR (not by the marketing description).

    make voice-samples                      # French female ElevenLabs voices of your library × flash and turbo
    make voice-samples ARGS="--voices id1,id2 --models eleven_flash_v2_5 --gradium F7Iib4MAyHIRed0x"

Writes scenarios/results/voice-samples/<voice>__<model>__NN.mp3 and index.html (open it: one row per voice, play
each sentence, time to first byte shown). Then put the chosen one in .env (only the phone agent changes):
    VOICE_TTS_VOICE=<id>   VOICE_TTS_MODEL=<model>   VOICE_TTS_SETTINGS={"stability":0.45,"similarity_boost":0.8,"speed":1.05}
Uses TTS_API_KEY (ElevenLabs) and, for --gradium, GRADIUM_API_KEY (or TTS_API_KEY when TTS_PROVIDER=gradium).
"""

import argparse
import html
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "ai"))
from app.agent.speak_fr import to_speech  # noqa: E402

# Situations from the brief: greeting, price, availability, shortage, correction, confirmation, complaint, names.
SENTENCES = [
    ("salutation", "Bonjour ! Le fermier ou le laitier ?"),
    ("prix", "Pour vous, c'est 14,50 €/kg."),
    ("disponibilité", "Oui, il nous en reste. Il vous en faut combien ?"),
    ("rupture", "On n'a plus de beaufort d'été, mais j'ai un beaufort d'hiver très bien."),
    ("correction", "Ça marche, 6 kg de tomme de Savoie, livrés vendredi. Je valide ?"),
    ("confirmation", "Parfait, c'est confirmé. Merci et à demain !"),
    ("réclamation", "Je comprends, je suis désolée pour ce retard. Je m'en occupe."),
    ("noms", "Reblochon, Abondance, Chevrotin, Persillé des Aravis et diots, livrés à Morzine, La Clusaz et au Grand-Bornand."),
]


def env() -> dict[str, str]:
    out = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def french_female(key: str) -> list[dict]:
    voices = httpx.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": key}, timeout=20).json().get("voices") or []

    def fr(v):
        labels = " ".join(str(x) for x in (v.get("labels") or {}).values()).lower()
        langs = " ".join(str(lang.get("language", "")) for lang in v.get("verified_languages") or []).lower()
        return "french" in labels or "français" in labels or " fr" in f" {langs}" or "fr" in langs.split()

    def female(v):
        return str((v.get("labels") or {}).get("gender", "")).lower() in ("female", "femme", "féminin")

    return [v for v in voices if fr(v) and female(v)]


def eleven(key: str, voice: str, model: str, text: str) -> tuple[bytes, int]:
    body = {"text": text, "model_id": model, **({} if "multilingual_v2" in model else {"language_code": "fr"})}
    t0 = time.perf_counter()
    first = None
    audio = b""
    with httpx.stream("POST", f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream?output_format=mp3_44100_128",
                      headers={"xi-api-key": key}, json=body, timeout=30) as r:  # fmt: skip
        r.raise_for_status()
        for chunk in r.iter_bytes():
            first = first or int((time.perf_counter() - t0) * 1000)
            audio += chunk
    return audio, first or 0


def gradium(key: str, voice: str, text: str) -> tuple[bytes, int]:
    t0 = time.perf_counter()
    r = httpx.post("https://api.gradium.ai/api/speech/tts", headers={"x-api-key": key}, timeout=30,
                   json={"text": text, "voice_id": voice, "model_name": "default", "output_format": "wav", "only_audio": True})  # fmt: skip
    r.raise_for_status()
    return r.content, int((time.perf_counter() - t0) * 1000)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voices", default="", help="ElevenLabs voice ids (default: French female voices of your library)")
    ap.add_argument("--models", default="eleven_flash_v2_5,eleven_turbo_v2_5")
    ap.add_argument("--max", type=int, default=5, help="at most this many library voices")
    ap.add_argument("--gradium", default="", help="Gradium voice ids to add (comma list)")
    args = ap.parse_args()
    e = env()
    key = e.get("TTS_API_KEY", "")
    out = ROOT / "scenarios" / "results" / "voice-samples"
    out.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, str, list[tuple[str, str, int]]]] = []  # (label, info, [(file, situation, ttfb)])

    voices = [{"voice_id": v, "name": v, "labels": {}} for v in filter(None, args.voices.split(","))]
    if not voices and key:
        voices = french_female(key)[: args.max]
        if not voices:
            print("No French female voice in your ElevenLabs library: elevenlabs.io → Voices → Voice Library → "
                  "Language: French, Gender: Female → Add to My Voices, then rerun (or pass --voices).")  # fmt: skip
    for v in voices:
        for model in filter(None, args.models.split(",")):
            files = []
            for i, (situation, sentence) in enumerate(SENTENCES):
                name = f"{v['voice_id']}__{model}__{i:02d}.mp3"
                try:
                    audio, ttfb = eleven(key, v["voice_id"], model, to_speech(sentence, "2026-11-24"))
                except httpx.HTTPError as err:
                    print(f"  {v['name']} {model}: {err}")
                    break
                (out / name).write_bytes(audio)
                files.append((name, situation, ttfb))
            info = ", ".join(f"{k}: {x}" for k, x in (v.get("labels") or {}).items())
            rows.append((f"{v.get('name')} — {model}", f"ElevenLabs {v['voice_id']} {info}", files))
            print(f"✓ {v.get('name')} {model}: median TTFB {sorted(f[2] for f in files)[len(files) // 2] if files else '—'} ms")
    gkey = e.get("GRADIUM_API_KEY") or (key if e.get("TTS_PROVIDER") == "gradium" else "")
    for gv in filter(None, args.gradium.split(",")):
        files = []
        for i, (situation, sentence) in enumerate(SENTENCES):
            name = f"gradium_{gv}__{i:02d}.wav"
            try:
                audio, ttfb = gradium(gkey, gv, to_speech(sentence, "2026-11-24"))
            except httpx.HTTPError as err:
                print(f"  gradium {gv}: {err}")
                break
            (out / name).write_bytes(audio)
            files.append((name, situation, ttfb))
        rows.append((f"Gradium {gv}", "Gradium default model", files))

    cells = "".join(f"<th>{html.escape(s)}</th>" for s, _ in SENTENCES)
    body = "".join(
        f"<tr><td><b>{html.escape(label)}</b><br><small>{html.escape(info)}</small></td>"
        + "".join(
            f'<td><audio controls preload="none" src="{html.escape(f)}"></audio><br><small>{ms} ms</small></td>' for f, _, ms in files
        )
        + "</tr>"
        for label, info, files in rows
    )
    (out / "index.html").write_text(
        f"""<!doctype html><meta charset="utf-8"><title>Voix — échantillons</title>
<style>body{{font:14px system-ui;margin:16px}}td,th{{border:1px solid #ccc;padding:6px;vertical-align:top}}audio{{width:150px}}</style>
<h1>Voix de la commerciale — mêmes phrases</h1><p>{html.escape(json.dumps([s for _, s in SENTENCES], ensure_ascii=False))}</p>
<table><tr><th>voix / modèle</th>{cells}</tr>{body}</table>""",
        encoding="utf-8",
    )
    print(f"→ {out / 'index.html'}")


if __name__ == "__main__":
    main()

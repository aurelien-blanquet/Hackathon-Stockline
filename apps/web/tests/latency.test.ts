/**
 * Latency diagnosis on the Voix page: where the useful answer starts in the audio, and the per-turn breakdown.
 * Run: pnpm --filter @kit/web test
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { UsefulMark } from "../src/features/assistant/audio-player";
import { breakdownLines, fmtMs } from "../src/pages/voice/latency";

test("useful audio after an acknowledgement starts where its first chunk was appended", () => {
  const m = new UsefulMark();
  m.markAt(2); // chunks 0-1: « D'accord. », then agent_audio_mark, then the answer
  m.appended(0, 0);
  m.appended(1, 0.4);
  m.appended(2, 0.62); // 0.62 s of acknowledgement buffered before the answer
  assert.equal(m.time, 0.62);
  assert.equal(m.reached(0.3), false); // still hearing the acknowledgement
  assert.equal(m.reached(0.62), true);
});

test("no acknowledgement: the useful audio starts at the first chunk", () => {
  const m = new UsefulMark();
  m.markAt(0);
  m.appended(0, 0);
  assert.equal(m.time, 0);
  assert.equal(m.reached(0), true);
});

test("only the first mark counts, and nothing is reached before a mark", () => {
  const m = new UsefulMark();
  assert.equal(m.reached(5), false);
  m.markAt(1);
  m.markAt(3);
  assert.equal(m.chunk, 1);
});

test("breakdown separates STT stages, server stages and tools, and flags the fallback", () => {
  const lines = breakdownLines({
    timings: {
      sttMs: 1600, sttConnectMs: 420, sttBacklogFrames: 3, sttFinalizeSentMs: 90, sttFallback: true,
      ackAudioMs: 350, usefulTextMs: 1100, usefulAudioMs: 1350,
      tools: [{ name: "identify_caller", startMs: 2, ms: 165 }],
    },
  });
  assert.deepEqual(lines, [
    "STT : flux prêt 420 ms après le début de parole · 3 trames en attente à la fin · finalize envoyé +90 ms · texte final +1,6 s · SECOURS : enregistrement retranscrit en entier",
    "Serveur : accusé envoyé +350 ms · 1er mot utile +1,1 s · audio utile envoyé +1,4 s",
    "Outils : identify_caller +2 ms (165 ms)",
  ]);
});

test("typed turn: no STT line", () => {
  assert.deepEqual(breakdownLines({ timings: { usefulTextMs: 500 } }), ["Serveur : 1er mot utile +500 ms"]);
  assert.equal(fmtMs(999), "999 ms");
});

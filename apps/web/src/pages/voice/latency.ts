/** Pure latency formatting for the Voix page (no React, no alias imports: unit-tested in tests/latency.test.ts). */
import type { TurnTimings } from "@kit/shared";

export const fmtMs = (ms: number) => (ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} s`);

const ms = (x: number | undefined) => (x == null ? "—" : fmtMs(x));

/** One line per stage, from the end of speech (server clock) unless said otherwise: where the time went. */
export function breakdownLines(t: { timings?: TurnTimings; perceivedMs?: number; transcriptMs?: number;
  client?: { firstTextMs?: number; audioStartMs?: number; firstChunkMs?: number; player?: string } }): string[] {
  const x = t.timings;
  if (!x) return [];
  const lines: string[] = [];
  const c = t.client;
  if (c && (c.audioStartMs != null || t.perceivedMs != null)) {  // where the time goes on THIS side of the network
    const nav = [
      t.transcriptMs != null ? `texte reçu +${ms(t.transcriptMs)}` : null,
      c.firstTextMs != null ? `1er texte de l'agent +${ms(c.firstTextMs)}` : null,
      c.audioStartMs != null ? `audio annoncé +${ms(c.audioStartMs)}` : null,
      c.firstChunkMs != null ? `1ers octets +${ms(c.firstChunkMs)}` : null,
      t.perceivedMs != null ? `son +${ms(t.perceivedMs)}` : null,
      c.player ? `lecteur ${c.player}` : null,
    ].filter(Boolean);
    lines.push(`Navigateur (depuis le relâchement) : ${nav.join(" · ")}`);
  }
  if (x.sttMs != null) {
    const stt = [
      x.sttConnectMs != null ? `flux prêt ${ms(x.sttConnectMs)} après le début de parole` : null,
      x.sttBacklogFrames != null ? `${x.sttBacklogFrames} trame${x.sttBacklogFrames > 1 ? "s" : ""} en attente à la fin` : null,
      x.sttFinalizeSentMs != null ? `finalize envoyé +${ms(x.sttFinalizeSentMs)}` : null,
      `texte final +${ms(x.sttMs)}`,
      x.sttFallback ? "SECOURS : enregistrement retranscrit en entier" : null,
    ].filter(Boolean);
    lines.push(`STT : ${stt.join(" · ")}`);
  }
  const srv = [
    x.ackAudioMs != null ? `accusé envoyé +${ms(x.ackAudioMs)}` : null,
    x.usefulTextMs != null ? `1er mot utile +${ms(x.usefulTextMs)}` : null,
    x.usefulAudioMs != null ? `audio utile envoyé +${ms(x.usefulAudioMs)}` : null,
  ].filter(Boolean);
  if (srv.length) lines.push(`Serveur : ${srv.join(" · ")}`);
  if (x.llmModel) lines.push(`Modèle : ${x.llmModel}`);
  if (x.tools?.length) lines.push(`Outils : ${x.tools.map((o) => `${o.name} +${ms(o.startMs)} (${ms(o.ms)})`).join(" · ")}`);
  return lines;
}


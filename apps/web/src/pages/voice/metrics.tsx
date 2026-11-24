/** Latency chips: per turn (from agent_done.timings) and the running average across turns. */
import type { TurnTimingMs } from "@kit/shared";
import { Gauge } from "lucide-react";
import { cn } from "@/lib/cn";
import { SECTION_LABEL } from "@/ui";
import type { VoiceTurn } from "@/features/assistant/useVoiceSession";
import { breakdownLines, fmtMs } from "./latency";

type Key = TurnTimingMs | "perceivedMs" | "usefulPerceivedMs" | "transcriptMs";
const METRICS: { key: Key; label: string; title: string }[] = [
  { key: "transcriptMs", label: "Transcrit", title: "Relâchement de la touche → transcription finale reçue (navigateur : marge micro + envoi + STT + réseau)" },
  { key: "sttMs", label: "STT", title: "Fin de parole (serveur) → transcription finale" },
  { key: "perceivedMs", label: "1er son", title: "Relâchement → premier son entendu : souvent l'accusé (« D'accord. »)" },
  { key: "usefulPerceivedMs", label: "Réponse utile", title: "Relâchement → la vraie réponse commence à être entendue" },
  { key: "llmFirstTokenMs", label: "LLM 1er", title: "Appel modèle → première sortie du modèle (texte ou outil)" },
  { key: "llmTotalMs", label: "LLM", title: "Modèle, outils compris" },
  { key: "ttsFirstByteMs", label: "TTS 1er", title: "Premier octet audio de la synthèse" },
  { key: "totalMs", label: "Total", title: "Fin de parole (serveur) → premier octet audio envoyé, accusé compris" },
];

const value = (t: VoiceTurn, k: Key): number | undefined =>
  k === "perceivedMs" ? t.perceivedMs : k === "usefulPerceivedMs" ? t.usefulPerceivedMs : k === "transcriptMs" ? t.transcriptMs : t.timings?.[k];

/** Total latency tone: < 1,5 s fast, < 3 s acceptable, else slow. */
function tone(k: Key, ms: number) {
  if (k !== "totalMs" && k !== "perceivedMs" && k !== "usefulPerceivedMs") return "text-secondary-foreground";
  return ms < 1500 ? "text-success" : ms < 3000 ? "text-warning" : "text-destructive";
}

export { fmtMs };

export function Chip({ label, ms, k, title, className }: { label: string; ms?: number; k: Key; title?: string; className?: string }) {
  return (
    <span title={title} className={cn("inline-flex h-[18px] items-center gap-1 rounded-[3px] border border-border bg-card px-1.5 font-mono text-[10.5px]", className)}>
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("num", ms == null ? "text-muted-foreground/60" : tone(k, ms))}>{ms == null ? "—" : fmtMs(ms)}</span>
    </span>
  );
}

export function TurnChips({ t }: { t: VoiceTurn }) {
  if (!t.timings && t.perceivedMs == null) return null;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-1">
        {METRICS.map((m) => {
          const ms = value(t, m.key);
          return ms == null ? null : <Chip key={m.key} k={m.key} label={m.label} ms={ms} title={m.title} />;
        })}
      </div>
      <Breakdown t={t} />
    </div>
  );
}

function Breakdown({ t }: { t: VoiceTurn }) {
  const lines = breakdownLines(t);
  if (!lines.length) return null;
  return (
    <div className="flex flex-col font-mono text-[10.5px] leading-[15px] text-muted-foreground">
      {lines.map((l) => <span key={l} className={cn(l.includes("SECOURS") && "text-destructive")}>{l}</span>)}
    </div>
  );
}

/** Strip above the timeline: running averages (and the count of measured turns). */
export function MetricsBar({ turns }: { turns: VoiceTurn[] }) {
  const measured = turns.filter((t) => t.timings);
  const avg = (k: Key) => {
    const xs = turns.map((t) => value(t, k)).filter((x): x is number => x != null);
    return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : undefined;
  };
  return (
    <div className="flex min-h-10 shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-5 py-1.5">
      <span className={cn(SECTION_LABEL, "flex items-center gap-1.5")}>
        <Gauge size={13} strokeWidth={1.75} />
        Latence moyenne
      </span>
      <span className="num text-[11.5px] text-muted-foreground">{measured.length ? `${measured.length} tour${measured.length > 1 ? "s" : ""}` : "aucun tour mesuré"}</span>
      <div className="flex min-w-0 flex-wrap items-center gap-1">
        {METRICS.map((m) => <Chip key={m.key} k={m.key} label={m.label} ms={avg(m.key)} title={m.title} />)}
      </div>
    </div>
  );
}

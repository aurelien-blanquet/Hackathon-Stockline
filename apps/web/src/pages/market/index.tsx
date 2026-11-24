/**
 * « Le marché du matin »: the central buying agent calls every supplier at the same time; this is the trading floor.
 * Data: POST /ai/market/rounds (start: mode christmas | daily) · GET /ai/market/rounds/latest (catch up) · SSE
 * /ai/market/rounds/{id}/events · GET /ai/market/schedule (the daily replenishment runs by itself every morning).
 * State: ./state.ts (pure, tested). Click a call to listen to it (POST /ai/tts, or the browser voice with mock TTS).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDownRight, ArrowLeftRight, Clock, Ear, Lock, PackagePlus, PhoneCall, Play, Store, Volume2 } from "lucide-react";
import { MOCK_TTS_MIME } from "@kit/shared";
import { AI_BASE } from "@/lib/api";
import { cn } from "@/lib/cn";
import { fmtMoney } from "@/lib/format";
import { Badge, Button, Dot, Page, PageHeader, SECTION_LABEL, Stat, Tabs, type Tone } from "@/ui";
import { board, liveCalls, replay, savingsSoFar, type CallView, type MarketEvent, type RoundView } from "./state";

const UNIT: Record<string, string> = { kg: "kg", piece: "pces", box: "cartons", liter: "L", dozen: "douz." };
const eur = (v: number) => `${v.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
const qty = (v: number, unit: string) => `${Math.round(v).toLocaleString("fr-FR")} ${UNIT[unit] ?? unit}`;
const fmtSec = (ms?: number) => (ms == null ? "—" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} s`);
const shortName = (n: string) => n.split(" (")[0];

const STATUS: Record<CallView["status"], { tone: Tone; label: string; pulse?: boolean }> = {
  idle: { tone: "muted", label: "En attente" },
  skipped: { tone: "muted", label: "Non appelé" },
  ringing: { tone: "info", label: "Ça sonne…", pulse: true },
  talking: { tone: "violet", label: "En ligne", pulse: true },
  waiting: { tone: "warning", label: "Offre finale · attend la décision" },
  won: { tone: "success", label: "Retenu" },
  lost: { tone: "muted", label: "Non retenu" },
};

export default function MarketPage() {
  const [events, setEvents] = useState<MarketEvent[]>([]);
  const [roundId, setRoundId] = useState<string>();
  const [starting, setStarting] = useState(false);
  const [mode, setMode] = useState<"demo" | "fast">("demo");
  const [selected, setSelected] = useState<string>();
  const [listening, setListening] = useState(false);
  const es = useRef<EventSource>();
  const r = useMemo(() => replay(events), [events]);
  const now = useClock(r, events.length > 0 && !r.done && !r.error);

  const follow = useCallback((id: string) => {
    es.current?.close();
    setRoundId(id);
    setEvents([]);
    const source = new EventSource(`${AI_BASE}/market/rounds/${id}/events`);
    source.onmessage = (m) => setEvents((xs) => [...xs, JSON.parse(m.data) as MarketEvent]);
    source.onerror = () => source.close(); // the server ends the stream when the round is over
    es.current = source;
  }, []);

  useEffect(() => {
    fetch(`${AI_BASE}/market/rounds/latest`).then((res) => (res.ok ? res.json() : null)).then((x) => x?.id && follow(x.id)).catch(() => {});
    return () => es.current?.close();
  }, [follow]);

  // A round started elsewhere (the voice agent's « marché express » during a customer call) shows up on its own:
  // check every 2 s whether the latest round changed, and follow it.
  const current = useRef<string>();
  current.current = roundId;
  useEffect(() => {
    const id = setInterval(() => {
      fetch(`${AI_BASE}/market/rounds/latest`)
        .then((res) => (res.ok ? res.json() : null))
        .then((x) => x?.id && x.id !== current.current && follow(x.id))
        .catch(() => {});
    }, 2000);
    return () => clearInterval(id);
  }, [follow]);

  // the « Réassort du matin » runs by itself every morning (AI service, MORNING_MARKET_AT): when, and the next run
  const [schedule, setSchedule] = useState<{ at?: string | null; nextRun?: string | null; lastRun?: string | null }>();
  useEffect(() => {
    fetch(`${AI_BASE}/market/schedule`).then((res) => (res.ok ? res.json() : null)).then((x) => x && setSchedule(x)).catch(() => {});
  }, [roundId]);

  const start = async (kind: "christmas" | "daily") => {
    setStarting(true);
    try {
      const res = await fetch(`${AI_BASE}/market/rounds`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ pace: mode === "fast" ? 0 : 1, mode: kind }) });
      const x = await res.json();
      setSelected(undefined);
      follow(x.id);
    } finally {
      setStarting(false);
    }
  };

  useListen(r, listening ? selected : undefined);

  const running = events.length > 0 && !r.done && !r.error;
  const called = r.calls.filter((c) => c.status !== "skipped");
  const live = liveCalls(r);
  return (
    <Page>
      <PageHeader
        title="Marché du matin"
        icon={<Store size={15} strokeWidth={1.75} />}
        meta={
          running ? (
            <span className="inline-flex items-center gap-1.5 text-[12.5px] text-violet"><Dot tone="violet" pulse />{live} appel{live > 1 ? "s" : ""} en cours en parallèle</span>
          ) : r.done ? (
            <span className="inline-flex items-center gap-1.5 text-[12.5px] text-success"><Dot tone="success" />Marché bouclé</span>
          ) : schedule?.at ? (
            <span className="inline-flex items-center gap-1.5 text-[12.5px] text-muted-foreground">
              <Clock size={13} strokeWidth={1.75} />Réassort automatique chaque matin à {schedule.at.replace(":", " h ")}
              {schedule.nextRun ? ` · prochain le ${new Date(schedule.nextRun).toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}` : null}
            </span>
          ) : null
        }
        tabs={<Tabs items={[{ id: "demo", label: "Démonstration" }, { id: "fast", label: "Rapide" }]} value={mode} onChange={setMode} />}
        actions={
          <>
            <Button icon={PackagePlus} onClick={() => start("daily")} disabled={starting || running}>Réassort du matin</Button>
            <Button variant="primary" icon={Play} onClick={() => start("christmas")} disabled={starting || running}>{roundId ? "Relancer le marché" : "Lancer le marché"}</Button>
          </>
        }
      />
      <div className="flex min-h-0 flex-1 flex-col overflow-auto">
        <Brief r={r} called={called.length} live={live} />
        {r.error ? <div className="border-b border-border bg-destructive/[.06] px-5 py-2 text-[12.5px] text-destructive">{r.error}</div> : null}
        {!events.length ? (
          <Intro />
        ) : (
          <>
            {r.summary ? <Summary r={r} /> : null}
            <Swimlanes r={r} now={now} selected={selected} />
            <div className="flex shrink-0 border-b border-border">
              <div className="grid min-w-0 flex-1 auto-rows-min grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-3 p-4">
                {r.calls.map((c) => (
                  <CallTile key={c.id} c={c} r={r} selected={selected === c.id} listening={listening && selected === c.id}
                    onSelect={() => { setSelected(c.id === selected ? undefined : c.id); setListening(c.id !== selected); }} />
                ))}
              </div>
              <OfferBoard r={r} />
            </div>
            <Learned roundId={r.done ? roundId : undefined} />
          </>
        )}
      </div>
    </Page>
  );
}

/** Time since the round started, ticking while it runs (the timeline cursor). */
function useClock(r: RoundView, running: boolean) {
  const [now, setNow] = useState(r.t);
  const anchor = useRef<{ wall: number; t: number }>({ wall: 0, t: 0 });
  useEffect(() => { anchor.current = { wall: performance.now(), t: r.t }; setNow(r.t); }, [r.t]);
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setNow(anchor.current.t + performance.now() - anchor.current.wall), 120);
    return () => clearInterval(id);
  }, [running]);
  return Math.max(now, r.t);
}

function Intro() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 px-8 py-16 text-center">
      <Store size={22} strokeWidth={1.5} className="text-muted-foreground" />
      <div className="text-[14px] font-medium">L'agent achats appelle tous vos fournisseurs en même temps</div>
      <p className="max-w-[560px] text-[12.5px] text-muted-foreground">
        Il calcule ce qui va manquer pour la semaine de Noël (vos ventes de l'an dernier, moins le stock), appelle chaque
        fournisseur concerné, fait jouer la concurrence entre eux, puis choisit la meilleure combinaison prix · délai ·
        fiabilité et passe les bons de commande dans l'ERP. Chaque matin, il fait aussi le réassort tout seul : chaque
        produit remonte au moins à une semaine de ventes moyennes.
      </p>
    </div>
  );
}

function Brief({ r, called, live }: { r: RoundView; called: number; live: number }) {
  const offers = r.calls.reduce((n, c) => n + Object.keys(c.offers).length, 0);
  const pos = r.calls.filter((c) => c.po).length;
  const coverage = r.summary?.coverage ?? (r.decision ? Math.floor((100 * r.decision.covered) / r.decision.needed) : undefined);
  return (
    <div className="shrink-0 border-b border-border">
      {r.title ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 pt-2.5 text-[12.5px] text-muted-foreground">
          <span className="font-medium text-foreground">{r.title}</span>
          <span>besoin calculé sur les {r.reference}</span>
          {r.needBy ? <span>· livraison avant le {new Date(r.needBy).toLocaleDateString("fr-FR", { day: "numeric", month: "long" })}</span> : null}
          <span>· {r.needs.length} produits</span>
          {r.skippedProducts?.length ? (
            <span title={r.skippedProducts.map((p) => `${p.name} : ${p.reason}`).join("\n")}>
              · hors saison, pas acheté : {r.skippedProducts.map((p) => p.name).join(", ")}
            </span>
          ) : null}
        </div>
      ) : null}
      <div className="grid grid-cols-2 divide-x divide-border md:grid-cols-5">
        <Stat icon={PhoneCall} label="Appels en parallèle" value={`${live} / ${called || "—"}`} tone={live ? "violet" : undefined} />
        <Stat label="Offres reçues" value={offers || "—"} />
        <Stat label="Économie négociée" value={offers ? fmtMoney(savingsSoFar(r)) : "—"} tone={offers ? "success" : undefined} hint={r.summary ? `${String(r.summary.savingsPct).replace(".", ",")} % sur les prix demandés` : "prix demandés − prix obtenus"} />
        <Stat label="Besoin couvert" value={coverage != null ? `${coverage} %` : "—"} hint={r.summary ? `${r.summary.coverageRegular} % avec les seuls fournisseurs habituels` : undefined} />
        <Stat label="Bons de commande" value={pos || "—"} hint={pos ? "créés dans l'ERP" : undefined} />
      </div>
    </div>
  );
}

function CallTile({ c, r, selected, listening, onSelect }: { c: CallView; r: RoundView; selected: boolean; listening: boolean; onSelect: () => void }) {
  const s = STATUS[c.status];
  const names = Object.fromEntries(r.needs.map((n) => [n.productId, n]));
  const lastIntel = c.intel[c.intel.length - 1];
  const flash = lastIntel && r.t - lastIntel.t < 3500;
  const from = lastIntel ? r.calls.find((x) => x.id === lastIntel.fromCall) : undefined;
  const offers = Object.values(c.offers).sort((a, b) => b.qty * b.price - a.qty * a.price);
  const main = offers[0];
  const lines = c.lines.slice(-3);
  const skipped = c.status === "skipped";
  return (
    <button
      type="button"
      onClick={skipped ? undefined : onSelect}
      className={cn(
        "flex min-h-[208px] flex-col gap-2 rounded-[6px] border bg-card p-3 text-left transition-colors duration-300",
        skipped ? "cursor-default border-dashed border-border opacity-60" : "hover:border-border-hover",
        c.status === "talking" && "border-violet/40 bg-violet/[.03]",
        c.status === "won" && "border-success/40",
        c.status === "lost" && "opacity-75",
        flash && "border-violet ring-2 ring-violet/20",
        selected && "ring-2 ring-ring/60",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[13px] font-medium">{c.name}</div>
          <div className="truncate text-[11.5px] text-muted-foreground">{[c.contact, c.city].filter(Boolean).join(" · ") || "—"}</div>
        </div>
        {c.reliability ? <Badge tone="muted" className="shrink-0" >{"★".repeat(c.reliability)}<span className="text-muted-foreground/50">{"★".repeat(3 - c.reliability)}</span></Badge> : null}
      </div>
      <div className="flex items-center gap-1.5 text-[12px] text-secondary-foreground">
        <Dot tone={s.tone} pulse={s.pulse} />
        {s.label}
        {c.status === "won" && c.wonTotal ? <span className="num ml-auto font-medium text-success">{fmtMoney(c.wonTotal)}</span> : null}
        {listening ? <Volume2 size={13} strokeWidth={1.75} className="ml-auto text-violet" /> : null}
      </div>
      {skipped ? (
        <p className="text-[12px] text-muted-foreground">{c.reason}</p>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-1">
          {lines.map((l, i) => (
            <p key={`${c.id}-${c.lines.length - lines.length + i}`} className={cn("line-clamp-2 text-[12px] leading-[17px] transition-opacity", i === lines.length - 1 ? "opacity-100" : "opacity-55")}>
              <span className={cn("mr-1 font-medium", l.speaker === "buyer" ? "text-violet" : "text-foreground")}>{l.speaker === "buyer" ? "Agent" : (c.contact?.split(" ")[0] ?? "Fournisseur")} :</span>
              <span className="text-secondary-foreground">{l.text}</span>
            </p>
          ))}
          {c.levers.length ? (
            <div className="flex flex-wrap items-center gap-1 text-[11px] text-muted-foreground">
              Levier{c.levers.length > 1 ? "s" : ""} :
              {c.levers.map((l, k) => <Badge key={k} tone={k === c.levers.length - 1 ? "violet" : "muted"}>{l.label}</Badge>)}
            </div>
          ) : null}
          {flash && from ? (
            <div className="flex items-center gap-1 text-[11.5px] font-medium text-violet">
              <ArrowLeftRight size={12} strokeWidth={2} /> prix de {shortName(from.name)} utilisé : {eur(lastIntel.price)}
            </div>
          ) : null}
        </div>
      )}
      {main ? (
        <div className="flex items-center gap-2 border-t border-border pt-2 text-[12px]">
          <span className="min-w-0 flex-1 truncate text-muted-foreground">{names[main.productId]?.name ?? ""}</span>
          <span className="num shrink-0 whitespace-nowrap font-semibold">{eur(main.price)}</span>
          {main.price < main.opening ? (
            <span className="num inline-flex shrink-0 items-center whitespace-nowrap text-success"><ArrowDownRight size={12} strokeWidth={2} />{(((main.opening - main.price) / main.opening) * 100).toFixed(1).replace(".", ",")} %</span>
          ) : null}
          {main.final ? <Lock size={11} strokeWidth={2} className="text-muted-foreground" /> : null}
        </div>
      ) : null}
      {c.po ? <Link to={`/purchase-orders/${c.po.id}`} onClick={(e) => e.stopPropagation()} className="text-[11.5px] text-primary hover:underline">{c.po.number} · bon de commande créé</Link> : null}
    </button>
  );
}

function OfferBoard({ r }: { r: RoundView }) {
  const rows = board(r);
  return (
    <aside className="relative w-[360px] shrink-0 border-l border-border">
      <div className="absolute inset-0 overflow-auto">
      <div className={cn(SECTION_LABEL, "sticky top-0 z-10 border-b border-border bg-background px-4 py-2")}>Tableau des offres</div>
      {rows.map(({ need, rows: offers, uncovered }) => (
        <div key={need.productId} className="border-b border-border px-4 py-2.5">
          <div className="flex items-baseline justify-between gap-2">
            <span className="truncate text-[12.5px] font-medium">{need.name}</span>
            <span className="num shrink-0 text-[11.5px] text-muted-foreground">{qty(need.need, need.unit)}</span>
          </div>
          {offers.length ? offers.map((o, i) => (
            <div key={o.callId} className={cn("flex items-center gap-2 py-0.5 text-[12px] transition-colors", o.allocated ? "text-success" : i === 0 ? "text-foreground" : "text-muted-foreground")}>
              <span className="min-w-0 flex-1 truncate" title={o.name}>{shortName(o.name)}{o.regular ? null : <span className="text-[10.5px]"> · occasionnel</span>}</span>
              {o.price < o.opening ? <span className="num text-[11px] text-muted-foreground line-through">{eur(o.opening)}</span> : null}
              <span className={cn("num", i === 0 && "font-semibold")}>{eur(o.price)}</span>
              {o.final ? <Lock size={10} strokeWidth={2} /> : <span className="w-[10px]" />}
              {o.allocated ? <span className="num w-[74px] text-right">✓ {qty(o.allocated, need.unit)}</span> : <span className="w-[74px]" />}
            </div>
          )) : <div className="text-[12px] text-muted-foreground">En attente des offres…</div>}
          {uncovered ? <div className="mt-0.5 text-[11.5px] text-warning">Manque {qty(uncovered, need.unit)}</div> : null}
        </div>
      ))}
      </div>
    </aside>
  );
}

/** One lane per call over time: the bars overlap = the agents work at the same time. */
function Swimlanes({ r, now, selected }: { r: RoundView; now: number; selected?: string }) {
  const calls = r.calls.filter((c) => c.status !== "skipped" && c.start != null);
  const span = Math.max(now, r.t, 20000) * 1.04;
  const x = (t: number) => `${(100 * t) / span}%`;
  return (
    <div className="shrink-0 border-b border-border px-5 py-3">
      <div className="mb-2 flex items-center gap-3">
        <span className={SECTION_LABEL}>Les appels en parallèle</span>
        <span className="text-[11.5px] text-muted-foreground"><span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-violet align-middle" />agent achats <span className="ml-2 mr-1 inline-block h-1.5 w-1.5 rounded-full bg-foreground/60 align-middle" />fournisseur <span className="ml-2 mr-1 inline-block h-2 w-2 rotate-45 bg-warning align-middle" />prix concurrent utilisé</span>
        <span className="num ml-auto text-[11.5px] text-muted-foreground">{(now / 1000).toFixed(0)} s</span>
      </div>
      <div className="relative flex flex-col gap-0.5">
        {calls.map((c) => (
          <div key={c.id} className="flex items-center gap-2">
            <span className={cn("w-[150px] shrink-0 truncate text-[11.5px]", selected === c.id ? "font-medium text-foreground" : "text-muted-foreground")}>{shortName(c.name)}</span>
            <div className="relative h-3 flex-1">
              <div
                className={cn("absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full", c.status === "won" ? "bg-success/35" : c.status === "lost" ? "bg-muted-foreground/20" : "bg-violet/25")}
                style={{ left: x(c.start ?? 0), width: `calc(${x((c.end ?? now) - (c.start ?? 0))})` }}
              />
              {c.lines.map((l, i) => (
                <span key={i} className={cn("absolute top-1/2 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full", l.speaker === "buyer" ? "bg-violet" : "bg-foreground/60")} style={{ left: x(l.t) }} />
              ))}
              {c.intel.map((i, k) => (
                <span key={`i${k}`} className="absolute top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rotate-45 bg-warning" style={{ left: x(i.t) }} title="Prix d'un concurrent utilisé" />
              ))}
            </div>
          </div>
        ))}
        {calls.length ? <div className="pointer-events-none absolute bottom-0 top-0 w-px bg-violet/60" style={{ left: `calc(158px + (100% - 158px) * ${now / span})` }} /> : null}
      </div>
    </div>
  );
}

interface LeverStat { tries: number; meanDropPct: number }
interface LearnedSupplier { supplierId: string; name: string; best?: string; bestLabel?: string; levers: Record<string, LeverStat> }
const LEVER_LABEL: Record<string, string> = { concurrence: "Prix concurrent", volume: "Volume", fidelite: "Fidélité", paiement: "Paiement rapide", souplesse: "Livraison souple" };

/** What the buyer agent learned: per supplier, the argument that obtained the biggest drop (market/levers.py). */
function Learned({ roundId }: { roundId?: string }) {
  const [data, setData] = useState<{ rounds: number; suppliers: LearnedSupplier[] }>();
  const load = useCallback(() => {
    fetch(`${AI_BASE}/market/memory`).then((res) => (res.ok ? res.json() : null)).then((x) => x && setData(x)).catch(() => {});
  }, []);
  useEffect(load, [load, roundId]);
  const reset = async () => {
    await fetch(`${AI_BASE}/market/memory/reset`, { method: "POST" }).catch(() => {});
    load();
  };
  if (!data) return null;
  const levers = Object.keys(LEVER_LABEL);
  return (
    <div className="shrink-0 border-b border-border px-5 py-3">
      <div className="mb-2 flex items-center gap-3">
        <span className={SECTION_LABEL}>Ce que l'agent achats a appris</span>
        <span className="text-[11.5px] text-muted-foreground">{data.rounds} négociation{data.rounds > 1 ? "s" : ""} · baisse moyenne obtenue par levier, le meilleur en violet</span>
        <Button variant="ghost" className="ml-auto" onClick={reset}>Repartir de zéro</Button>
      </div>
      {data.suppliers.length ? (
        <table className="w-full text-[12px]">
          <thead>
            <tr className="text-left text-[11px] text-muted-foreground">
              <th className="py-1 font-normal">Producteur</th>
              {levers.map((l) => <th key={l} className="py-1 text-right font-normal">{LEVER_LABEL[l]}</th>)}
            </tr>
          </thead>
          <tbody>
            {data.suppliers.map((s) => (
              <tr key={s.supplierId} className="border-t border-border">
                <td className="py-1 pr-2">{shortName(s.name)}</td>
                {levers.map((l) => {
                  const st = s.levers[l];
                  return (
                    <td key={l} className={cn("num py-1 text-right", s.best === l ? "font-semibold text-violet" : "text-secondary-foreground")}>
                      {st ? `${st.meanDropPct.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %` : "—"}
                      {st ? <span className="ml-1 text-[10.5px] text-muted-foreground">×{st.tries}</span> : null}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-[12px] text-muted-foreground">Rien encore : à chaque marché, l'agent essaie un argument par producteur (volume, fidélité, paiement rapide, livraison souple, prix concurrent) et retient celui qui le fait baisser.</p>
      )}
    </div>
  );
}

function Summary({ r }: { r: RoundView }) {
  const s = r.summary!;
  const pos = r.calls.filter((c) => c.po);
  return (
    <div className="shrink-0 border-b border-border bg-violet/[.04] px-5 py-3">
      <div className="mb-1 flex items-center gap-2 text-[12.5px] font-medium text-violet"><Ear size={14} strokeWidth={1.75} />Compte rendu de l'agent achats</div>
      <p className="max-w-[1100px] text-[13px] leading-5">{s.text}</p>
      {s.metrics ? (
        <p className="num mt-1 text-[11.5px] text-muted-foreground">
          Décision en {fmtSec(s.metrics.timeToDecisionMs)} · bons de commande écrits en {fmtSec(s.metrics.timeToOrdersCreatedMs)} · dialogues terminés en {fmtSec(s.metrics.timeToAllDialoguesFinishedMs)}
          {s.metrics.voices ? ` · ${s.metrics.voices.llmCalls} répliques générées, ${s.metrics.voices.templates} sans modèle, ${s.metrics.voices.cacheHits} en cache, ${s.metrics.voices.fallbacks} de secours` : ""}
        </p>
      ) : null}
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {pos.map((c) => (
          <Link key={c.id} to={`/purchase-orders/${c.po!.id}`} className="num text-[12px] text-primary hover:underline">{c.po!.number} · {shortName(c.name)} · {fmtMoney(c.po!.total ?? 0)}</Link>
        ))}
      </div>
    </div>
  );
}

/** Speak the selected call's new lines as they arrive (ElevenLabs through /ai/tts; browser voice with mock TTS). */
function useListen(r: RoundView, callId: string | undefined) {
  const spoken = useRef<Record<string, number>>({});
  const queue = useRef<Promise<void>>(Promise.resolve());
  const call = r.calls.find((c) => c.id === callId);
  const count = call?.lines.length ?? 0;
  useEffect(() => {
    if (!call) return;
    const from = spoken.current[call.id] ?? Math.max(0, count - 1); // start with the line being said now
    const fresh = call.lines.slice(from);
    spoken.current[call.id] = count;
    for (const l of fresh) queue.current = queue.current.then(() => say(l.text, l.speaker)).catch(() => {});
  }, [call, count]);
  useEffect(() => () => { try { window.speechSynthesis?.cancel(); } catch { /* ignore */ } }, [callId]);
}

async function say(text: string, speaker: "buyer" | "supplier") {
  const res = await fetch(`${AI_BASE}/tts`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text }) });
  const mime = res.headers.get("content-type") ?? "";
  if (!res.ok || mime.startsWith(MOCK_TTS_MIME)) {
    await new Promise<void>((done) => {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "fr-FR";
      u.pitch = speaker === "buyer" ? 1.15 : 0.8;
      u.rate = 1.1;
      u.onend = u.onerror = () => done();
      window.speechSynthesis.speak(u);
    });
    return;
  }
  const url = URL.createObjectURL(await res.blob());
  await new Promise<void>((done) => {
    const a = new Audio(url);
    a.onended = a.onerror = () => { URL.revokeObjectURL(url); done(); };
    a.play().catch(() => done());
  });
}

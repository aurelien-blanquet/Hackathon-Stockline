/**
 * « Coulisses » of a call: when the voice agent lacks stock, the buying agent negotiates with the producers DURING the
 * call (market/express.py). This panel shows that negotiation live, on the call screen: who is called, what each one
 * says, the argument used (volume, fidélité, prix concurrent…), the price falling, the producer kept, and the similar
 * products in stock offered as a second option. The caller never sees or hears it: it is the team's (and the jury's)
 * view. Data: the same events as the « Marché du matin » page (GET /ai/market/rounds/latest + SSE).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDownRight, Gavel, Lock, PackageCheck, PhoneCall, X } from "lucide-react";
import { AI_BASE } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Badge, Dot, IconButton, SECTION_LABEL, type Tone } from "@/ui";
import { replay, type CallView, type MarketEvent } from "@/pages/market/state";

const UNIT: Record<string, string> = { kg: "kg", piece: "pces", box: "cartons", liter: "L", dozen: "douz." };
const eur = (v: number) => `${v.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
const qty = (v: number, unit: string) => `${v.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} ${UNIT[unit] ?? unit}`;
const STATUS: Record<CallView["status"], { tone: Tone; label: string; pulse?: boolean }> = {
  idle: { tone: "muted", label: "En attente" },
  skipped: { tone: "muted", label: "Non appelé" },
  ringing: { tone: "info", label: "Ça sonne…", pulse: true },
  talking: { tone: "violet", label: "Négocie…", pulse: true },
  waiting: { tone: "warning", label: "Offre finale" },
  won: { tone: "success", label: "Retenu" },
  lost: { tone: "muted", label: "Non retenu" },
};

interface Alternative { productId: string; name: string; unit: string; price: number; available?: number }
interface Express { wanted: number; inStock: number; shortfall: number; unit: string; product: string; alternatives?: Alternative[] }

/** Follows the in-call markets started after this page opened (the morning market has its own page). */
export function LiveNegotiation() {
  const [events, setEvents] = useState<MarketEvent[]>([]);
  const [hidden, setHidden] = useState(false);
  const seen = useRef<string | null | undefined>(undefined); // undefined: not checked yet → the round already there is old
  const es = useRef<EventSource>();

  useEffect(() => {
    const check = () =>
      fetch(`${AI_BASE}/market/rounds/latest`)
        .then((res) => (res.ok ? res.json() : null))
        .then((x: { id: string; events: MarketEvent[] } | null) => {
          const id = x?.id ?? null;
          if (seen.current === undefined) { seen.current = id; return; } // opened mid-session: do not replay an old one
          if (!id || id === seen.current || !x?.events?.length) return; // nothing new yet (or not started: next poll)
          seen.current = id;
          if (!String(x.events[0]?.data?.title ?? "").startsWith("Marché express")) return; // a morning market
          es.current?.close();
          setEvents([]);
          setHidden(false);
          const source = new EventSource(`${AI_BASE}/market/rounds/${id}/events`);
          source.onmessage = (m) => setEvents((xs) => [...xs, JSON.parse(m.data) as MarketEvent]);
          source.onerror = () => source.close();
          es.current = source;
        })
        .catch(() => {});
    void check();
    const timer = setInterval(check, 700);
    return () => { clearInterval(timer); es.current?.close(); };
  }, []);

  const r = useMemo(() => replay(events), [events]);
  const express = events.find((e) => e.type === "round_started")?.data?.express as Express | undefined;
  if (!events.length || hidden || !express) return null;

  const calls = r.calls.filter((c) => c.status !== "skipped");
  const live = calls.filter((c) => c.status === "ringing" || c.status === "talking").length;
  const kept = r.decision?.allocations ?? [];
  const keptNames = kept.map((a) => calls.find((c) => c.id === a.supplierId)?.name).filter(Boolean) as string[];
  const done = r.done || !!r.summary;
  return (
    <div className="shrink-0 border-t border-border bg-violet/[.035] px-5 py-3">
      <div className="mb-2 flex items-center gap-2">
        <Gavel size={15} strokeWidth={1.75} className="text-violet" />
        <span className="text-[13px] font-semibold text-violet">
          {done ? "Négociation terminée" : `Négociation en direct avec ${calls.length} producteur${calls.length > 1 ? "s" : ""}`}
        </span>
        {!done ? <span className="inline-flex items-center gap-1 text-[12px] text-violet"><Dot tone="violet" pulse />{live || calls.length} en ligne</span> : null}
        <span className="text-[11.5px] text-muted-foreground">· coulisses : le client ne l'entend pas</span>
        <IconButton icon={X} label="Masquer" variant="ghost" className="ml-auto" onClick={() => setHidden(true)} />
      </div>

      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px]">
        <span><span className="text-muted-foreground">Demandé :</span> <b>{qty(express.wanted, express.unit)}</b> {express.product}</span>
        <span><span className="text-muted-foreground">En stock :</span> {qty(express.inStock, express.unit)}</span>
        <span><span className="text-muted-foreground">À faire venir :</span> <b className="text-violet">{qty(express.shortfall, express.unit)}</b></span>
      </div>

      <div className="grid grid-cols-[repeat(auto-fill,minmax(230px,1fr))] gap-2">
        {calls.map((c) => <ProducerTile key={c.id} c={c} unit={express.unit} />)}
      </div>

      {r.decision ? (
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[12.5px]">
          <PackageCheck size={14} strokeWidth={1.75} className="text-success" />
          {kept.length ? (
            <span>
              <b className="text-success">Retenu{keptNames.length > 1 ? "s" : ""} : {keptNames.join(", ")}</b>
              {" — "}{kept.map((a) => `${qty(a.qty, express.unit)} à ${eur(a.price)}`).join(" + ")}
              {r.decision.savings > 0 ? <span className="text-success"> · {eur(r.decision.savings)} gagnés sur les prix demandés</span> : null}
              <span className="text-muted-foreground"> · bon de commande au oui du client</span>
            </span>
          ) : (
            <span className="text-warning">Aucun producteur ne peut livrer à temps.</span>
          )}
          {r.id ? <Link to="/market" className="ml-auto text-[12px] text-primary hover:underline">Voir sur la page Marché</Link> : null}
        </div>
      ) : null}

      {express.alternatives?.length ? (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px]">
          <span className={SECTION_LABEL}>Aussi proposé au client, en stock tout de suite</span>
          {express.alternatives.map((a) => (
            <Badge key={a.productId} tone="success">{a.name} · {eur(a.price)}/{UNIT[a.unit] ?? a.unit}</Badge>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ProducerTile({ c, unit }: { c: CallView; unit: string }) {
  const s = STATUS[c.status];
  const offer = Object.values(c.offers)[0];
  const last = c.lines[c.lines.length - 1];
  const lever = c.levers?.[c.levers.length - 1];
  return (
    <div
      className={cn(
        "flex flex-col gap-1 rounded-[6px] border bg-card p-2.5 transition-colors duration-300",
        c.status === "talking" && "border-violet/50",
        c.status === "won" && "border-success/50 bg-success/[.04]",
        c.status === "lost" && "opacity-60",
      )}
    >
      <div className="flex items-center gap-1.5">
        <PhoneCall size={12} strokeWidth={1.75} className="shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium">{c.name.split(" (")[0]}</span>
        <span className="inline-flex shrink-0 items-center gap-1 text-[11px]"><Dot tone={s.tone} pulse={s.pulse} />{s.label}</span>
      </div>
      {last ? (
        <p className="line-clamp-2 min-h-[34px] text-[11.5px] leading-[17px]">
          <span className={cn("mr-1 font-medium", last.speaker === "buyer" ? "text-violet" : "text-foreground")}>
            {last.speaker === "buyer" ? "Agent achats" : (c.contact?.split(" ")[0] ?? "Producteur")} :
          </span>
          <span className="text-secondary-foreground">{last.text}</span>
        </p>
      ) : <p className="min-h-[34px] text-[11.5px] text-muted-foreground">Appel en cours…</p>}
      <div className="flex items-center gap-1.5 text-[12px]">
        {lever ? <Badge tone="violet">Levier : {lever.label}</Badge> : null}
        {offer ? (
          <span className="ml-auto inline-flex items-center gap-1.5">
            {offer.price < offer.opening ? <span className="num text-[11px] text-muted-foreground line-through">{eur(offer.opening)}</span> : null}
            <span className="num font-semibold">{eur(offer.price)}</span>
            {offer.price < offer.opening ? (
              <span className="num inline-flex items-center text-success"><ArrowDownRight size={12} strokeWidth={2} />{(((offer.opening - offer.price) / offer.opening) * 100).toFixed(1).replace(".", ",")} %</span>
            ) : null}
            {offer.final ? <Lock size={10} strokeWidth={2} className="text-muted-foreground" /> : null}
            <span className="text-[11px] text-muted-foreground">· {qty(offer.qty, unit)}</span>
          </span>
        ) : null}
      </div>
    </div>
  );
}

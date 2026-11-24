/**
 * « Recommandation du matin · à valider »: the purchase orders the agent buyer negotiated for the daily replenishment
 * (draft purchase orders noted « Marché du matin, réassort du … »). Nothing goes to a producer before the owner says so:
 * Valider = ERP POST /api/purchase-orders/{id}/send (logged under the owner's name), Refuser = cancel (the draft is
 * dropped). The agent never sends one itself (apps/ai market/round.py, mode "daily").
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Check, ShieldCheck, X } from "lucide-react";
import type { PurchaseOrderDetail } from "@kit/shared";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { fmtDate, fmtMoney, fmtQty } from "@/lib/format";
import { Badge, Button, toast } from "@/ui";
import type { RoundView } from "./state";

const MARKER = "Marché du matin, réassort";
const eur = (v: number) => `${v.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
const weeks = (d: number) => (d % 7 === 0 ? `${d / 7} sem.` : `${d} j`);

interface Handled { id: string; number: string; supplier: string; total: number; status: "sent" | "cancelled" }

export function MorningApproval({ r, roundId }: { r: RoundView; roundId?: string }) {
  const [pending, setPending] = useState<PurchaseOrderDetail[]>([]);
  const [handled, setHandled] = useState<Handled[]>([]);
  const [busy, setBusy] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    try {
      const page = await api.purchaseOrders.page({ status: "draft", limit: 100, sort: "createdAt", order: "desc" });
      const mine = page.items.filter((po) => (po.note ?? "").startsWith(MARKER));
      setPending(await Promise.all(mine.map((po) => api.purchaseOrders.get(po.id))));
    } catch {
      /* the ERP is down: the panel stays as it was */
    }
  }, []);
  // the drafts are written ~0,3 s into a round, long before the replay ends: look again shortly after it starts,
  // then whenever a producer's order is announced and when the round ends
  const announced = r.calls.filter((c) => c.po).length;
  useEffect(() => {
    void load();
    const t = setTimeout(() => void load(), 1500);
    return () => clearTimeout(t);
  }, [load, roundId, r.done, announced]);

  // the economic lot behind each line, when the page shows the round that negotiated it
  const lots = useMemo(() => Object.fromEntries(r.needs.filter((n) => n.coverDays != null).map((n) => [n.productId, n])), [r.needs]);

  const act = async (po: PurchaseOrderDetail, approve: boolean) => {
    setBusy((b) => new Set(b).add(po.id));
    try {
      await (approve ? api.purchaseOrders.send(po.id) : api.purchaseOrders.cancel(po.id));
      setPending((xs) => xs.filter((x) => x.id !== po.id));
      setHandled((xs) => [...xs, { id: po.id, number: po.number, supplier: po.supplier.name, total: po.totalHt, status: approve ? "sent" : "cancelled" }]);
      if (approve) toast.success(`${po.number} envoyé à ${po.supplier.name}`, `${fmtMoney(po.totalHt)} · livraison le ${fmtDate(po.expectedDate)}`);
      else toast.success(`${po.number} refusé`, "Le brouillon est annulé : rien n'est commandé chez ce producteur.");
    } catch (e) {
      toast.error(`${po.number} : ${approve ? "envoi" : "refus"} impossible`, e instanceof Error ? e.message : undefined);
    } finally {
      setBusy((b) => {
        const next = new Set(b);
        next.delete(po.id);
        return next;
      });
    }
  };
  const approveAll = () => Promise.all(pending.map((po) => act(po, true))); // all at once: one wait, not one per producer

  if (!pending.length && !handled.length) return null;
  const total = pending.reduce((s, po) => s + po.totalHt, 0);
  const sent = handled.filter((h) => h.status === "sent");
  return (
    <div className="shrink-0 border-b border-border bg-warning/[.04] px-5 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <ShieldCheck size={15} strokeWidth={1.75} className={pending.length ? "text-warning" : "text-success"} />
        <span className="text-[13px] font-medium">{pending.length ? "Recommandation du matin · à valider" : "Recommandation du matin · traitée"}</span>
        <span className="text-[12px] text-muted-foreground">
          {pending.length
            ? `L'agent achats a négocié ${pending.length} bon${pending.length > 1 ? "s" : ""} de commande (${eur(total)}) : rien ne part chez les producteurs sans votre accord.`
            : `${sent.length} bon${sent.length > 1 ? "s" : ""} envoyé${sent.length > 1 ? "s" : ""} (${eur(sent.reduce((s, h) => s + h.total, 0))}), ${handled.length - sent.length} refusé${handled.length - sent.length > 1 ? "s" : ""}.`}
        </span>
        {pending.length > 1 ? (
          <Button variant="primary" size="sm" icon={Check} className="ml-auto" onClick={approveAll} disabled={busy.size > 0}>
            Tout valider · {eur(total)}
          </Button>
        ) : null}
      </div>
      {pending.length ? (
        <div className="mt-2.5 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {pending.map((po) => (
            <div key={po.id} className="flex flex-col gap-1.5 rounded-[6px] border border-border bg-card p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-medium">{po.supplier.name}</div>
                  <div className="text-[11.5px] text-muted-foreground">
                    <Link to={`/purchase-orders/${po.id}`} className="text-primary hover:underline">{po.number}</Link> · livraison le {fmtDate(po.expectedDate)}
                  </div>
                </div>
                <span className="num shrink-0 text-[13px] font-medium">{fmtMoney(po.totalHt)}</span>
              </div>
              <ul className="flex flex-col gap-0.5 text-[12px]">
                {po.lines.map((l) => {
                  const lot = lots[l.productId];
                  return (
                    <li key={l.id} className="flex items-baseline gap-1.5">
                      <span className="num shrink-0 text-secondary-foreground">{fmtQty(l.qty, l.unit)}</span>
                      <span className="min-w-0 flex-1 truncate" title={l.productName}>{l.productName.split(" (")[0]}</span>
                      <span className="num shrink-0 text-muted-foreground">{eur(l.unitPrice)}</span>
                      {lot?.coverDays && lot.need > (lot.weekNeed ?? 0) ? (
                        <span title={`Lot économique : ${weeks(lot.coverDays)} de ventes au lieu d'une semaine (remise volume ${lot.discountPct} %)`}>
                          <Badge tone="success">{weeks(lot.coverDays)}</Badge>
                        </span>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
              {po.warnings?.map((w, i) => (
                <div key={i} className="flex items-start gap-1 text-[11.5px] text-warning">
                  <AlertTriangle size={12} strokeWidth={2} className="mt-[2px] shrink-0" />
                  {w.message}
                </div>
              ))}
              <div className={cn("mt-auto flex items-center gap-1.5 pt-1", busy.has(po.id) && "opacity-60")}>
                <Button variant="primary" size="sm" icon={Check} onClick={() => act(po, true)} disabled={busy.has(po.id)}>Valider et envoyer</Button>
                <Button variant="ghost" size="sm" icon={X} onClick={() => act(po, false)} disabled={busy.has(po.id)}>Refuser</Button>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

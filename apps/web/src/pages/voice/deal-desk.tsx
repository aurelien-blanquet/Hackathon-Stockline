/**
 * « Le comité de prix » on the call screen: when a caller asks for a gesture or orders big, four agents work at the same
 * time (buyer with the producers, stock and short-dated lots, credit, the client's habits), then the ERP's arbiter
 * picks the offers by expected margin. The caller hears two options; this panel shows the team (and the jury) why.
 * Staff view only: margins, costs and producers are here, never in the voice.
 */
import { useState } from "react";
import { Banknote, Boxes, Gavel, ShoppingCart, TrendingUp, X } from "lucide-react";
import type { DealPanel } from "@kit/shared";
import { cn } from "@/lib/cn";
import { Badge, Dot, IconButton, SECTION_LABEL, Spinner } from "@/ui";

const eur = (v: number) => `${v.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
const UNIT: Record<string, string> = { kg: "kg", piece: "pces", box: "cartons", liter: "L", dozen: "douz." };
const AGENTS = [
  { name: "Achat", icon: ShoppingCart, hint: "négocie avec les producteurs" },
  { name: "Stock", icon: Boxes, hint: "lots, dates courtes" },
  { name: "Crédit", icon: Banknote, hint: "encours, retards" },
  { name: "Ventes", icon: TrendingUp, hint: "habitudes du client" },
];

export function DealDesk({ deal }: { deal?: DealPanel | "working" }) {
  const [hiddenId, setHiddenId] = useState<string>();
  if (!deal || (deal !== "working" && deal.dealId === hiddenId)) return null;
  const working = deal === "working";
  const panel = working ? undefined : deal;
  return (
    <div className="shrink-0 border-t border-border bg-card px-5 py-3 animate-fade-in">
      <div className="mb-2 flex items-center gap-2">
        <Gavel size={14} strokeWidth={1.75} className="text-violet" />
        <span className={SECTION_LABEL}>Comité de prix</span>
        {panel ? <span className="text-[11.5px] text-muted-foreground">{panel.product} · {panel.askedQty.toLocaleString("fr-FR")} demandés · {panel.ms} ms</span> : null}
        <span className="flex-1" />
        {panel ? <IconButton icon={X} label="Masquer" size="sm" onClick={() => setHiddenId(panel.dealId)} /> : null}
      </div>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4">
        {AGENTS.map(({ name, icon: Icon, hint }) => {
          const a = panel?.agents.find((x) => x.name === name);
          return (
            <div key={name} className="rounded-[4px] border border-border px-3 py-2 text-[12px]">
              <div className="mb-1 flex items-center gap-1.5 font-medium">
                <Icon size={13} strokeWidth={1.75} />{name}
                <span className="flex-1" />
                {a ? <span className="num text-[10.5px] text-muted-foreground">{a.ms} ms</span> : <Dot tone="violet" pulse />}
              </div>
              <div className={cn("leading-snug", !a && "text-muted-foreground")}>{a ? a.line : <span className="flex items-center gap-1.5"><Spinner size={11} />{hint}…</span>}</div>
            </div>
          );
        })}
      </div>
      {panel ? (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
                <th className="py-1 pr-3 font-medium">Option</th><th className="pr-3 font-medium">Quantité</th><th className="pr-3 font-medium">Prix</th>
                <th className="pr-3 font-medium">Marge</th><th className="pr-3 font-medium">Perte évitée</th><th className="pr-3 font-medium">Acceptation</th>
                <th className="pr-3 font-medium">Valeur attendue</th><th className="font-medium">Pourquoi</th>
              </tr>
            </thead>
            <tbody>
              {panel.options.map((o) => {
                const chosen = o.key === panel.chosen;
                return (
                  <tr key={o.key} className={cn("border-t border-border", chosen && "bg-success/[.07] font-medium")}>
                    <td className="py-1 pr-3">{o.key} {chosen ? <Badge tone="success">retenue</Badge> : o.key === panel.alternative ? <Badge tone="info">alternative</Badge> : null}</td>
                    <td className="num pr-3">{o.qty.toLocaleString("fr-FR")} {UNIT[o.unit] ?? o.unit}</td>
                    <td className="num pr-3">{eur(o.unitPrice)}{o.pct ? <span className="text-muted-foreground"> (−{o.pct.toLocaleString("fr-FR")} %)</span> : null}</td>
                    <td className="num pr-3">{eur(o.margin)}</td>
                    <td className="num pr-3">{o.wasteAvoided ? eur(o.wasteAvoided) : "—"}</td>
                    <td className="num pr-3">{Math.round(o.pAccept * 100)} %</td>
                    <td className="num pr-3">{eur(o.expected)}</td>
                    <td className="text-muted-foreground">{o.why}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="mt-1.5 text-[12px]"><span className="font-medium text-success">Décision ▸</span> {panel.decision}</div>
        </div>
      ) : working ? <div className="mt-2 text-[12px] text-muted-foreground">Les quatre agents travaillent en parallèle…</div> : null}
    </div>
  );
}

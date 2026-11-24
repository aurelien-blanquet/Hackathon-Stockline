/** Customer-facing view of what the side agents found during a call: a status line and the offer card.
 *  Never the internal dialogue, costs, margins or ids (the server sends none of them); producers only as the
 *  provenance of an option the caller may pick. */
import { CircleCheck, PackageSearch, Repeat, Tractor, Warehouse } from "lucide-react";
import type { OfferChoice, OfferLine } from "@kit/shared";
import { cn } from "@/lib/cn";
import { Money, Qty, SECTION_LABEL, Spinner } from "@/ui";

export function AgentStatus({ label, done }: { label: string; done: boolean }) {
  const found = label.startsWith("Meilleure offre");
  return (
    <span className={cn("flex h-6 items-center gap-1.5 text-[12px]", found ? "text-success" : "text-violet")}>
      {found ? <CircleCheck size={13} strokeWidth={1.75} /> : done ? <PackageSearch size={13} strokeWidth={1.75} /> : <Spinner size={12} />}
      {label}
    </span>
  );
}

const TONE = (availability: string) =>
  /^En stock/.test(availability) ? "text-success" : /Indisponible|Rupture|manque/.test(availability) ? "text-destructive" : /préciser/.test(availability) ? "text-muted-foreground" : "text-warning";

const KIND: Record<string, { icon: typeof Warehouse; label: string }> = {
  stock: { icon: Warehouse, label: "Stock" },
  producer: { icon: Tractor, label: "Producteur" },
  alternative: { icon: Repeat, label: "Produit proche" },
};

/** Every possibility for a short product, side by side: our stock, EACH producer's own offer, similar products in stock. */
function Choices({ choices }: { choices: OfferChoice[] }) {
  return (
    <div className="col-span-2 mt-1.5 rounded-[4px] border border-border">
      <div className={cn(SECTION_LABEL, "flex items-center justify-between border-b border-border px-2 py-1")}>
        <span>Toutes les possibilités</span>
        <span className="normal-case tracking-normal text-muted-foreground">{choices.filter((c) => c.kind === "producer").length} producteurs consultés</span>
      </div>
      <ul className="divide-y divide-border">
        {choices.map((c, i) => {
          const k = KIND[c.kind] ?? KIND.alternative;
          const Icon = k.icon;
          return (
            <li key={i} className={cn("grid grid-cols-[16px_1fr_auto] items-center gap-x-2 px-2 py-1.5 text-[12px]", c.best && "bg-success/[.06]", !c.inTime && "opacity-70")}>
              <Icon size={13} strokeWidth={1.75} className="text-muted-foreground" />
              <span className="min-w-0">
                <span className="font-medium">{c.label}</span>
                <span className="ml-1.5 text-[11px] text-muted-foreground">{k.label}</span>
                {c.best ? <span className="ml-1.5 rounded-[3px] bg-success/15 px-1 text-[10.5px] font-medium text-success">Conseillé</span> : null}
                <span className="block text-[11px] text-muted-foreground">
                  {c.qty != null ? <><Qty value={c.qty} unit={c.unit ?? undefined} /> · </> : "Toute la quantité · "}
                  {c.delivery ? (c.inTime ? `livraison ${c.delivery}` : c.delivery) : "livraison au prochain passage"}
                </span>
              </span>
              <span className="text-right">
                {c.unitPrice != null ? <><Money value={c.unitPrice} />{c.unit ? <span className="text-muted-foreground"> /{c.unit === "piece" ? "pièce" : c.unit}</span> : null}</> : null}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function OfferCard({ lines }: { lines: OfferLine[] }) {
  const total = lines.every((l) => l.total != null) ? lines.reduce((s, l) => s + (l.total ?? 0), 0) : null;
  return (
    <div className="w-full max-w-[560px] rounded-[4px] border border-border bg-card shadow-sm">
      <div className={cn(SECTION_LABEL, "border-b border-border px-3 py-1.5")}>Offre</div>
      <ul className="divide-y divide-border">
        {lines.map((l) => (
          <li key={l.product + (l.options?.join() ?? "")} className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 px-3 py-2 text-[12.5px]">
            <span className="min-w-0 break-words font-medium">
              {l.qty != null ? <><Qty value={l.qty} unit={l.unit ?? undefined} /> · </> : null}
              {l.product}
            </span>
            <span className="text-right">
              {l.unitPrice != null ? <><Money value={l.unitPrice} />{l.unit ? <span className="text-muted-foreground"> /{l.unit === "piece" ? "pièce" : l.unit}</span> : null}</> : null}
            </span>
            <span className={cn("min-w-0 text-[11.5px]", TONE(l.availability))}>
              {l.options?.length ? `À préciser : ${l.options.join(" ou ")}` : l.availability}
            </span>
            <span className="text-right text-[11.5px] text-muted-foreground">
              {l.total != null ? <Money value={l.total} /> : null}
              {l.delivery ? <span className="ml-2">Livraison {l.delivery}</span> : null}
            </span>
            {l.choices?.length ? <Choices choices={l.choices} /> : null}
          </li>
        ))}
      </ul>
      {total != null && lines.length > 1 ? (
        <div className="flex justify-between border-t border-border px-3 py-1.5 text-[12px]"><span className="text-muted-foreground">Total HT</span><Money value={total} /></div>
      ) : null}
    </div>
  );
}

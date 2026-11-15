// Local visual check only: the Command Center without the Fabric auth gate. Filter clicks are answered from the
// recorded live results of the example filters (src/command-center/__fixtures__/filtered); other combinations fall
// back to the full snapshot. Not part of the deployed app.
import { createRoot } from "react-dom/client";

import { CommandCenter } from "./command-center/CommandCenter";
import type { Filters } from "./command-center/filters";
import proof from "./command-center/proof.json";
import { mergeData, shapeLive, type LiveResults } from "./command-center/shape";
import snapshot from "./command-center/snapshot.json";

const files = import.meta.glob("./command-center/__fixtures__/filtered/*.json", { eager: true, import: "default" });
const EX: Record<string, Filters> = {
    mid_day: { mid: "MID900001", from: "2026-02-21", to: "2026-02-21" }, city: { city: "Jeddah" },
    egs_flow: { egs: "EGS-05", flow: "REPORTING" }, not_assessed: { status: "NOT_ASSESSED" }, method_city: { method: "MADA", city: "Jeddah" },
};
const norm = (f: Filters) => JSON.stringify(Object.fromEntries(Object.entries(f).filter(([, v]) => v).sort()));

async function query(f: Filters) {
    const hit = Object.entries(EX).find(([, e]) => norm(e) === norm(f));
    if (!hit) return snapshot;
    const pick = (q: string) => files[`./command-center/__fixtures__/filtered/${hit[0]}__${q}.json`];
    const live = { recon_totals: pick("recon_totals"), recon_cells: pick("recon_cells"), calendar: pick("calendar"),
                   zatca: pick("zatca"), ndmo: pick("ndmo"), payments: pick("payments") } as LiveResults;
    return mergeData(shapeLive(live), proof);
}

createRoot(document.getElementById("root")!).render(<CommandCenter query={query} />);

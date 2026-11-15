import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { buildQueries, paymentFilters, settlementFilters, withFilters, zatcaFilters, type Filters } from "./filters";
import { shapeLive, type LiveResults, type QueryName } from "./shape";
import snapshot from "./snapshot.json";

const HERE = dirname(fileURLToPath(import.meta.url));
const NAMES: QueryName[] = ["recon_totals", "recon_cells", "calendar", "zatca", "ndmo", "payments"];
const base = Object.fromEntries(NAMES.map((n) => [n, readFileSync(join(HERE, "queries", `${n}.dax`), "utf8")])) as Record<QueryName, string>;
// Example filter sets: their generated DAX is committed (queries/examples) and recorded live (__fixtures__/filtered).
export const EXAMPLES: Record<string, Filters> = {
    mid_day: { mid: "MID900001", from: "2026-02-21", to: "2026-02-21" },
    city: { city: "Jeddah" },
    egs_flow: { egs: "EGS-05", flow: "REPORTING" },
    not_assessed: { status: "NOT_ASSESSED" },
    method_city: { method: "MADA", city: "Jeddah" },
};

describe("filter DAX", () => {
    it("rejects anything outside the known value patterns", () => {
        expect(() => settlementFilters({ mid: 'MID900001" || 1=1 || "' })).toThrow();
        expect(() => settlementFilters({ city: "Atlantis" })).toThrow();
        expect(() => settlementFilters({ from: "2026-02-21); EVALUATE x //" })).toThrow();
        expect(() => zatcaFilters({ state: "PAID" })).toThrow();
        expect(() => zatcaFilters({ egs: "EGS-5" })).toThrow();
        expect(() => paymentFilters({ method: "CRYPTO" })).toThrow();
    });
    it("wraps the table expression and keeps ORDER BY outside", () => {
        const q = withFilters(base.recon_cells, ['x[y] = "z"']);
        expect(q).toMatch(/EVALUATE\nCALCULATETABLE\(\nSELECTCOLUMNS\(/);
        expect(q.trimEnd().endsWith("ORDER BY [merchant_id], [d]")).toBe(true);
        expect(withFilters(base.recon_totals, [])).toBe(base.recon_totals);
    });
    it.each(Object.entries(EXAMPLES))("example %s matches its committed query files", (name, f) => {
        const q = buildQueries(base, f);
        for (const n of NAMES) {
            const file = join(HERE, "queries", "examples", `${name}__${n}.dax`);
            if (process.env.UPDATE_EXAMPLES) { mkdirSync(dirname(file), { recursive: true }); writeFileSync(file, q[n]); }
            expect(q[n]).toBe(readFileSync(file, "utf8"));
        }
    });
});

function fixture(name: string): LiveResults | null {
    const dir = join(HERE, "__fixtures__", "filtered");
    if (!existsSync(join(dir, `${name}__recon_totals.json`))) return null;
    return Object.fromEntries(NAMES.map((n) => [n, JSON.parse(readFileSync(join(dir, `${name}__${n}.json`), "utf8"))])) as LiveResults;
}

const H = (s: string) => BigInt(s.replace(".", ""));
const cells = snapshot.heat.merchants.flatMap((m, i) => snapshot.heat.days.map((d, j) => ({ m, d, g: snapshot.heat.cells[i][j] })))
    .filter((c) => c.g !== null) as { m: string; d: string; g: string }[];

describe("live filtered results agree with the unfiltered Gold data", () => {
    it("one MID-day", () => {
        const live = shapeLive(fixture("mid_day")!);
        const cell = cells.find((c) => c.m === "MID900001" && c.d === "2026-02-21")!;
        expect(live.recon.mid_days).toBe(1);
        expect(live.recon.gross).toBe(cell.g);
        expect(live.heat.merchants).toEqual(["MID900001"]);
    });
    it("one city", () => {
        const live = shapeLive(fixture("city")!);
        const mids = new Set(snapshot.stores.filter((s) => s.city === "Jeddah").map((s) => s.merchant));
        const expected = cells.filter((c) => mids.has(c.m)).reduce((a, c) => a + H(c.g), 0n);
        expect(H(live.recon.gross)).toBe(expected);
        expect(live.heat.merchants.every((m: string) => mids.has(m))).toBe(true);
    });
    it("one EGS device and invoice type", () => {
        const live = shapeLive(fixture("egs_flow")!);
        expect(live.zatca.egs.map((e: { egs: string }) => e.egs)).toEqual(["EGS-05"]);
        expect(live.zatca.flows.map((f: { flow: string }) => f.flow)).toEqual(["REPORTING"]);
        const docs = Object.values(live.zatca.states as Record<string, number>).reduce((a, b) => a + b, 0);
        expect(docs).toBe(live.zatca.egs[0].docs);
        expect(live.recon).toEqual(snapshot.recon);             // ZATCA filters never slice the settlement scenes
    });
    it("payment method + city slices the payment cards (and the city slices settlement)", () => {
        const live = shapeLive(fixture("method_city")!);
        expect(live.payments.methods.map((m: { method: string }) => m.method)).toEqual(["MADA"]);
        const all = shapeLive(fixture("city")!);
        const mada = all.payments.methods.find((m: { method: string }) => m.method === "MADA");
        expect(live.payments.methods[0].captures).toBe(mada.captures);     // MADA in Jeddah, both ways
        expect(live.recon).toEqual(all.recon);                             // method never slices the recon
    });
    it("MID-days not assessed (no bank file)", () => {
        const live = shapeLive(fixture("not_assessed")!);
        expect(live.recon.mid_days).toBe(snapshot.truth.not_assessed_mid_days);
        expect(live.recon.bank).toBe("0.00");
        expect(live.recon.transit).toBe(snapshot.recon.transit);
    });
});

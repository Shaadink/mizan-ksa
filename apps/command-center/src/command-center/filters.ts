// Builds the filtered DAX for the live filter bar. Each base query (queries/*.dax) is wrapped in CALCULATETABLE with
// the active filters, so every number stays a semantic-model result. Filter values are validated against strict
// patterns before they reach DAX: nothing typed into the bar can inject DAX.

import type { QueryName } from "./shape";

export interface Filters {
    from?: string; to?: string; mid?: string; city?: string; status?: string;
    egs?: string; flow?: string; state?: string;
}

const R = "fact_merchant_settlement_recon";
const Z = "fact_zatca_clearance_ledger";
const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const CITIES = new Set(["Riyadh", "Jeddah", "Dammam", "Makkah", "Madinah"]);
const STATES = new Set(["CLEARED", "REPORTED", "ACCEPTED_WITH_WARNINGS", "CONFIRMED_REJECTION"]);

function daxDate(v: string): string {
    const m = DATE.exec(v);
    if (!m) throw new Error(`invalid date filter: ${v}`);
    return `DATE(${Number(m[1])}, ${Number(m[2])}, ${Number(m[3])})`;
}

function str(v: string, ok: (x: string) => boolean, what: string): string {
    if (!ok(v)) throw new Error(`invalid ${what} filter: ${v}`);
    return `"${v}"`;                       // validated values never contain quotes
}

/** Filter predicates for the settlement table (reconciliation queries). */
export function settlementFilters(f: Filters): string[] {
    const out: string[] = [];
    if (f.from) out.push(`${R}[business_date_ksa] >= ${daxDate(f.from)}`);
    if (f.to) out.push(`${R}[business_date_ksa] <= ${daxDate(f.to)}`);
    if (f.mid) out.push(`${R}[merchant_id] = ${str(f.mid, (x) => /^MID\d{6}$/.test(x), "merchant")}`);
    if (f.city) out.push(`merchant_store_reference[city] = ${str(f.city, (x) => CITIES.has(x), "city")}`);
    if (f.status === "ASSESSED") out.push(`${R}[in_transit_sar] = 0`);
    else if (f.status === "NOT_ASSESSED") out.push(`${R}[in_transit_sar] <> 0`);
    else if (f.status) throw new Error(`invalid status filter: ${f.status}`);
    return out;
}

/** Filter predicates for the ZATCA ledger. */
export function zatcaFilters(f: Filters): string[] {
    const out: string[] = [];
    if (f.from) out.push(`${Z}[issue_date_ksa] >= ${daxDate(f.from)}`);
    if (f.to) out.push(`${Z}[issue_date_ksa] <= ${daxDate(f.to)}`);
    if (f.egs) out.push(`${Z}[egs_id] = ${str(f.egs, (x) => /^EGS-\d{2}$/.test(x), "EGS")}`);
    if (f.flow) out.push(`${Z}[invoice_flow] = ${str(f.flow, (x) => x === "REPORTING" || x === "CLEARANCE", "flow")}`);
    if (f.state) out.push(`${Z}[state] = ${str(f.state, (x) => STATES.has(x), "outcome")}`);
    return out;
}

/** Wraps the table expression after EVALUATE (and before a trailing ORDER BY) in CALCULATETABLE(..., filters). */
export function withFilters(dax: string, preds: string[]): string {
    if (!preds.length) return dax;
    const at = dax.indexOf("EVALUATE");
    if (at < 0) throw new Error("query has no EVALUATE");
    const head = dax.slice(0, at + "EVALUATE".length);
    let body = dax.slice(at + "EVALUATE".length);
    let order = "";
    const ob = body.lastIndexOf("\nORDER BY");
    if (ob >= 0) { order = body.slice(ob); body = body.slice(0, ob); }
    return `${head}\nCALCULATETABLE(\n${body.trim()},\n    ${preds.join(",\n    ")}\n)${order}`;
}

export function buildQueries(base: Record<QueryName, string>, f: Filters): Record<QueryName, string> {
    const s = settlementFilters(f), z = zatcaFilters(f);
    return {
        recon_totals: withFilters(base.recon_totals, s),
        recon_cells: withFilters(base.recon_cells, s),
        calendar: base.calendar,             // the full Gregorian/Hijri window, labels only
        zatca: withFilters(base.zatca, z),
        ndmo: base.ndmo,                     // governance scorecard: not sliced by business filters
    };
}

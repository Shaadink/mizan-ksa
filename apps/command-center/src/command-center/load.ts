// Loads the Command Center data: live DAX through the Rayfin semantic-model connector when it is configured,
// otherwise the committed export snapshot (clearly labelled), so the page never shows invented numbers.
import calendarDax from "./queries/calendar.dax?raw";
import ndmoDax from "./queries/ndmo.dax?raw";
import reconCellsDax from "./queries/recon_cells.dax?raw";
import reconTotalsDax from "./queries/recon_totals.dax?raw";
import zatcaDax from "./queries/zatca.dax?raw";
import proof from "./proof.json";
import snapshot from "./snapshot.json";
import { buildQueries, type Filters } from "./filters";
import { mergeData, shapeLive, type LiveResults, type MizanData, type QueryName, type QueryTableLike } from "./shape";

export const CONNECTOR = "mizan";
export const QUERIES: Record<QueryName, string> = {
    recon_totals: reconTotalsDax, recon_cells: reconCellsDax, calendar: calendarDax, zatca: zatcaDax, ndmo: ndmoDax,
};

type QueryResult = { status: "success"; table: QueryTableLike } | { status: "error"; error: { message: string } };
export type Runner = (query: string) => Promise<QueryResult>;

export interface Loaded {
    data: MizanData;
    mode: "live" | "snapshot";
    note: string;
}

/** Live data for the current filter bar state; throws on any query error (the page shows the message). */
export async function queryFiltered(run: Runner, f: Filters): Promise<MizanData> {
    const q = buildQueries(QUERIES, f);
    const names = Object.keys(q) as QueryName[];
    const results = await Promise.all(names.map((n) => run(q[n])));
    const bad = results.findIndex((r) => r.status !== "success");
    if (bad >= 0) throw new Error(`${names[bad]}: ${(results[bad] as Extract<QueryResult, { status: "error" }>).error.message}`);
    const live = Object.fromEntries(names.map((n, i) => [n, (results[i] as Extract<QueryResult, { status: "success" }>).table])) as LiveResults;
    return mergeData(shapeLive(live), proof);
}

export async function loadData(run: Runner | null): Promise<Loaded> {
    if (!run) return { data: snapshot, mode: "snapshot", note: "Export snapshot (no semantic-model connector yet)" };
    try {
        const names = Object.keys(QUERIES) as QueryName[];
        const results = await Promise.all(names.map((n) => run(QUERIES[n])));
        const bad = results.findIndex((r) => r.status !== "success");
        if (bad >= 0) {
            const r = results[bad] as Extract<QueryResult, { status: "error" }>;
            throw new Error(`${names[bad]}: ${r.error.message}`);
        }
        const live = Object.fromEntries(names.map((n, i) => [n, (results[i] as Extract<QueryResult, { status: "success" }>).table])) as LiveResults;
        return { data: mergeData(shapeLive(live), proof), mode: "live", note: "Live from MIZAN Control Tower Model (DAX)" };
    } catch (e) {
        return { data: snapshot, mode: "snapshot", note: `Snapshot shown: live query failed (${(e as Error).message})` };
    }
}

import { describe, expect, it } from "vitest";

import calendar from "./__fixtures__/calendar.json";
import ndmo from "./__fixtures__/ndmo.json";
import reconCells from "./__fixtures__/recon_cells.json";
import reconTotals from "./__fixtures__/recon_totals.json";
import zatca from "./__fixtures__/zatca.json";
import payments from "./__fixtures__/payments.json";
import proof from "./proof.json";
import snapshot from "./snapshot.json";
import { big, hundredths, mergeData, shapeLive, type LiveResults, type MizanData } from "./shape";

// Fixtures are real results of the app's DAX queries on the Fabric semantic model (scripts/record_app_dax.py).
const live = shapeLive({ recon_totals: reconTotals, recon_cells: reconCells, calendar, zatca, ndmo, payments } as LiveResults);

describe("money is exact", () => {
    it("formats integer halalas without floats", () => {
        expect(hundredths(2239073016)).toBe("22390730.16");
        expect(hundredths(-253633n)).toBe("-2536.33");
        expect(hundredths("1")).toBe("0.01");
        expect(() => big(0.1)).toThrow();
    });
});

// The __fixtures__ here are live DAX results recorded from the Fabric semantic model, so they can only
// be compared with snapshot.json while both describe the same dataset. A local regeneration that moves
// money (the 2026-11-16 price correction for ZATCA BR-KSA-50) leaves Fabric a dataset behind until the
// pipeline is re-run there. Skip with a reason instead of failing: no code change can reconcile them.
// Refresh: re-run the pipeline on Fabric, then scripts/record_app_dax.py.
// "Same dataset" has two halves, and only the money half existed until 2026-11-20. A SCHEMA difference is
// just as disqualifying: when Gold became incremental (ADR-015) Silver gained a `source_ingested_at`
// column on four tables, so the NDMO catalogue counts four more columns locally than the Fabric semantic
// model has ever seen. The money matched, so the old gate said "same dataset" and then compared two
// different lakehouses' governance scorecards -- which is not a finding, it is a category error.
// Counting the catalogued columns is the cheapest way to ask "is Fabric running the schema we are?".
const catalogueColumns = (d: MizanData): number =>
    (d.ndmo?.scorecard ?? [])
        .filter((r: { family: string }) => r.family === "CLASSIFICATION")
        .reduce((n: number, r: { den: number }) => n + r.den, 0);

const sameMoney = live.recon?.gross === snapshot.recon.gross;
const sameSchema = catalogueColumns(live) === catalogueColumns(snapshot);
const sameDataset = sameMoney && sameSchema;
if (!sameDataset) {
    const why = !sameMoney
        ? `gross ${live.recon?.gross} vs snapshot ${snapshot.recon.gross}`
        : `catalogued columns ${catalogueColumns(live)} vs snapshot ${catalogueColumns(snapshot)}`;
    console.warn(
        `[shape.spec] recorded Fabric fixtures are a different dataset than snapshot.json (${why}); ` +
        `live cross-checks skipped until the Fabric pipeline is re-run and scripts/record_app_dax.py ` +
        `is redone. See HONESTY.md row 36.`,
    );
}

// A signed ZATCA invoice is never re-priced: run_zatca skips every request_id already in
// ctl.invoice_outbox, so the chain on Fabric still carries the prices it was signed with on 2026-11-14,
// while snapshot.json comes from a local rebuild that started empty and signed the corrected ones.
// Verified 2026-11-19: the live total 30919828.86 is exactly the local figure before the 2026-11-16
// BR-KSA-50 price correction (30920225.04). Every count, state, ICV and flow still agrees -- only the
// amounts differ, and the only way to make them agree would be to re-sign a tax document, which is the
// one thing a ZATCA chain must not do. So the chain's SHAPE is still compared exactly; only the money is
// bounded, and the exact comparison turns itself back on the moment the two totals meet again. The
// correction never produced credit notes on Fabric either -- see HONESTY.md row 29.
const zatcaChainPredatesCorrection = live.zatca?.sar !== snapshot.zatca.sar;
const withoutMoney = (z: MizanData): MizanData =>
    JSON.parse(JSON.stringify(z), (k, v) => (k === "sar" ? undefined : v));
const halalas = (s: string): bigint => big(s.replace(".", ""));

describe.skipIf(!sameDataset)("live DAX results equal the exported Gold figures", () => {
    it.each(["recon", "daily", "calendar", "zatca", "payments"] as const)("%s", (k) => {
        if (k === "zatca" && zatcaChainPredatesCorrection) {
            expect(withoutMoney(live.zatca)).toEqual(withoutMoney(snapshot.zatca));
            const gap = halalas(live.zatca.sar) - halalas(snapshot.zatca.sar);
            // Under SAR 1,000 is a handful of corrected item prices; anything larger is a lost batch.
            expect((gap < 0n ? -gap : gap) < 100_000n).toBe(true);
            return;
        }
        expect(live[k]).toEqual(snapshot[k]);
    });
    it("heatmap cells, days and merchant order", () => {
        expect(live.heat.days).toEqual(snapshot.heat.days);
        expect(live.heat.merchants).toEqual(snapshot.heat.merchants);
        expect(live.heat.cells).toEqual(snapshot.heat.cells);
    });
    it("NDMO scorecard", () => {
        expect(live.ndmo.scorecard).toEqual(snapshot.ndmo.scorecard);
    });
    it("Stage 1 truth facts", () => {
        const { zatca_sar, egs_merchants, ...gold } = snapshot.truth; // eslint-disable-line @typescript-eslint/no-unused-vars
        expect(live.truth).toEqual(gold);
    });
    it("merged document is the full snapshot", () => {
        const merged = mergeData(live, proof);
        const { sources, ...rest } = merged; // eslint-disable-line @typescript-eslint/no-unused-vars
        if (zatcaChainPredatesCorrection) {
            expect({ ...rest, zatca: withoutMoney(rest.zatca) })
                .toEqual({ ...snapshot, zatca: withoutMoney(snapshot.zatca) });
            return;
        }
        expect(rest).toEqual(snapshot);
    });
});

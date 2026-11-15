import { describe, expect, it } from "vitest";

import calendar from "./__fixtures__/calendar.json";
import ndmo from "./__fixtures__/ndmo.json";
import reconCells from "./__fixtures__/recon_cells.json";
import reconTotals from "./__fixtures__/recon_totals.json";
import zatca from "./__fixtures__/zatca.json";
import proof from "./proof.json";
import snapshot from "./snapshot.json";
import { big, hundredths, mergeData, shapeLive, type LiveResults } from "./shape";

// Fixtures are real results of the app's DAX queries on the Fabric semantic model (scripts/record_app_dax.py).
const live = shapeLive({ recon_totals: reconTotals, recon_cells: reconCells, calendar, zatca, ndmo } as LiveResults);

describe("money is exact", () => {
    it("formats integer halalas without floats", () => {
        expect(hundredths(2239073016)).toBe("22390730.16");
        expect(hundredths(-253633n)).toBe("-2536.33");
        expect(hundredths("1")).toBe("0.01");
        expect(() => big(0.1)).toThrow();
    });
});

describe("live DAX results equal the exported Gold figures", () => {
    it.each(["recon", "daily", "calendar", "zatca"] as const)("%s", (k) => {
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
        expect(rest).toEqual(snapshot);
    });
});

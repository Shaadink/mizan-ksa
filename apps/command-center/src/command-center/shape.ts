// Shapes the five live DAX results (src/command-center/queries/*.dax) into exactly the data shape the scenes use,
// the same shape scripts/build_command_center.py exports (command_center/data.json). Money arrives as integer
// halalas and is formatted with BigInt arithmetic, so no amount ever passes through a float.

export interface QueryTableLike {
    columns: { name: string }[];
    rows: unknown[][];
}

export type QueryName = "recon_totals" | "recon_cells" | "calendar" | "zatca" | "ndmo";
export type LiveResults = Record<QueryName, QueryTableLike>;
// The scenes consume an untyped JSON document (same as the standalone page).
export type MizanData = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

/** "[gross_h]" or "table[col]" -> "gross_h" / "col". */
function key(name: string): string {
    const m = /\[([^\]]+)\]$/.exec(name);
    return m ? m[1] : name;
}

function records(t: QueryTableLike): Record<string, unknown>[] {
    const ks = t.columns.map((c) => key(c.name));
    return t.rows.map((r) => Object.fromEntries(ks.map((k, i) => [k, r[i]])));
}

/** An integer value from the connector: number, bigint or numeric string. Throws on fractions. */
export function big(v: unknown): bigint {
    if (typeof v === "bigint") return v;
    if (typeof v === "number") {
        if (!Number.isInteger(v)) throw new Error(`expected an integer, got ${v}`);
        return BigInt(v);
    }
    if (typeof v === "string" && /^-?\d+$/.test(v)) return BigInt(v);
    if (v === null || v === undefined) return 0n;
    throw new Error(`expected an integer, got ${String(v)}`);
}

/** Integer hundredths -> "1234.56" (exact). */
export function hundredths(v: unknown): string {
    const h = big(v);
    const neg = h < 0n;
    const a = neg ? -h : h;
    return `${neg ? "-" : ""}${a / 100n}.${(a % 100n).toString().padStart(2, "0")}`;
}

function int(v: unknown): number {
    return Number(big(v));
}

function bool(v: unknown): boolean {
    return v === true || v === 1 || v === "1" || v === "true" || v === 1n;
}

/** Round num/den to one decimal, half to even (Python Decimal.quantize default). */
function pct1(num: bigint, den: bigint): string {
    const scaled = num * 1000n;
    let q = scaled / den;
    const r = scaled % den;
    if (2n * r > den || (2n * r === den && q % 2n === 1n)) q += 1n;
    return `${q / 10n}.${q % 10n}`;
}

export function shapeLive(res: LiveResults): MizanData {
    const [t] = records(res.recon_totals);
    const recon = {
        gross: hundredths(t.gross_h), refunds: hundredths(t.refunds_h), fees: hundredths(t.fees_h),
        net: hundredths(t.net_h), bank: hundredths(t.bank_h), transit: hundredths(t.transit_h),
        quarantined: hundredths(t.quarantined_h), gl: hundredths(t.gl_h),
        bank_variance: hundredths(t.bank_variance_h), gl_variance: hundredths(t.gl_variance_h),
        unclassified: int(t.unclassified), mid_days: int(t.mid_days), merchants: int(t.merchants),
        from: String(t.date_from), to: String(t.date_to),
    };

    const cells = records(res.recon_cells);
    const byDay = new Map<string, Record<string, bigint>>();
    const byMerchant = new Map<string, bigint>();
    for (const c of cells) {
        const d = String(c.d);
        const acc = byDay.get(d) ?? { gross: 0n, bank: 0n, transit: 0n, gl: 0n, fees: 0n, refunds: 0n };
        acc.gross += big(c.gross_h); acc.bank += big(c.bank_h); acc.transit += big(c.transit_h);
        acc.gl += big(c.gl_h); acc.fees += big(c.fees_h); acc.refunds += big(c.refunds_h);
        byDay.set(d, acc);
        const m = String(c.merchant_id);
        byMerchant.set(m, (byMerchant.get(m) ?? 0n) + big(c.gross_h));
    }
    const days = [...byDay.keys()].sort();
    const daily = days.map((d) => {
        const a = byDay.get(d)!;
        return { d, gross: hundredths(a.gross), bank: hundredths(a.bank), transit: hundredths(a.transit),
                 gl: hundredths(a.gl), fees: hundredths(a.fees), refunds: hundredths(a.refunds) };
    });
    const merchants = [...byMerchant.entries()]
        .sort((a, b) => (a[1] === b[1] ? (a[0] < b[0] ? -1 : 1) : (a[1] > b[1] ? -1 : 1)))
        .map(([m]) => m);
    const grid = new Map(merchants.map((m) => [m, days.map((): string | null => null)]));
    const notAssessed: [string, string][] = [];
    for (const c of cells) {
        grid.get(String(c.merchant_id))![days.indexOf(String(c.d))] = hundredths(c.gross_h);
        if (big(c.transit_h) !== 0n) notAssessed.push([String(c.merchant_id), String(c.d)]);
    }
    notAssessed.sort((a, b) => (a[0] + a[1] < b[0] + b[1] ? -1 : 1));

    const calendar = Object.fromEntries(records(res.calendar).map((r) => [String(r.d), {
        hijri: `${int(r.hijri_day)} ${String(r.hijri_month_name)} ${int(r.hijri_year)}`,
        ramadan: bool(r.is_ramadan), weekend: bool(r.is_saudi_weekend),
    }]));

    const z = records(res.zatca);
    const of = (kind: string) => z.filter((r) => r.kind === kind).sort((a, b) => (String(a.key) < String(b.key) ? -1 : 1));
    const total = (k: string) => z.find((r) => r.kind === "TOTAL" && r.key === k)!;
    const zatca = {
        states: Object.fromEntries(of("STATE").map((r) => [String(r.key), int(r.docs)])),
        egs: of("EGS").map((r) => ({ egs: String(r.key), docs: int(r.docs), sar: hundredths(r.sar_h) })),
        flows: of("FLOW").map((r) => ({ flow: String(r.key), docs: int(r.docs), sar: hundredths(r.sar_h) })),
        daily: of("DAY").map((r) => ({ d: String(r.key), docs: int(r.docs) })),
        sar: hundredths(total("SAR").sar_h), corrections: int(total("CORRECTIONS").docs),
        retried: int(total("RETRIED").docs),
    };

    const scorecard = records(res.ndmo).map((r) => ({
        family: String(r.family), dimension: String(r.dimension), table: String(r.table), num: int(r.num),
        den: int(r.den), score: hundredths(r.score_x100), threshold: hundredths(r.threshold_x100),
        status: String(r.status), tier: r.tier === null || r.tier === undefined || r.tier === "" ? null : String(r.tier),
    }));

    const top = merchants[0];
    const truth = {
        assessed_mid_days: int(t.assessed), not_assessed_mid_days: int(t.not_assessed),
        not_assessed_dates: [...new Set(notAssessed.map(([, d]) => d))].sort(),
        not_assessed_cells: notAssessed, not_assessed_expected_net: hundredths(t.not_assessed_net_h),
        largest_merchant: top && big(t.gross_h) > 0n
            ? { merchant: top, share_of_sar_pct: pct1(byMerchant.get(top)!, big(t.gross_h)) }
            : { merchant: "", share_of_sar_pct: "0.0" },           // a filter that matches no captures
    };

    return { recon, daily, calendar, heat: { days, merchants, cells: merchants.map((m) => grid.get(m)!) },
             zatca, ndmo: { scorecard }, truth };
}

/** Live Gold figures over the labelled proof-run sections (proof.json). */
export function mergeData(live: MizanData, proof: MizanData): MizanData {
    return {
        ...proof, ...live,
        heat: { ...live.heat, demo_breaks: proof.heat.demo_breaks },
        ndmo: { ...live.ndmo, catalog: proof.ndmo.catalog },
        truth: { ...live.truth, ...proof.truth },
    };
}

import { useEffect, useRef, useState, type ReactElement } from "react";

import { connectorConfigs } from "@/lib/connectors";
import { getRayfinClient } from "@/lib/rayfin-client";
import { installGlobals } from "./legacy/globals.js";
import pageHtml from "./legacy/page.html?raw";
import "./legacy/page.css";
import "./app.css";
import { mountScenes } from "./legacy/scenes.js";
import type { Filters } from "./filters";
import { CONNECTOR, loadData, queryFiltered, type Loaded, type Runner } from "./load";

function runner(): Runner | null {
    if (!(CONNECTOR in connectorConfigs)) return null;
    let client;
    try {
        client = getRayfinClient();           // throws without deployment settings (tests, a plain `vite` preview)
    } catch {
        return null;                          // -> the labelled export snapshot
    }
    const connectors = client.connectors as unknown as Record<string, { executeQuery(a: { query: string }): Promise<unknown> }>;
    return async (query) => (await connectors[CONNECTOR].executeQuery({ query })) as Awaited<ReturnType<Runner>>;
}

/** `query` is only for the local preview (recorded live results); the app itself always uses the connector. */
export function CommandCenter({ query }: { query?: (f: Filters) => Promise<unknown> } = {}): ReactElement {
    const [loaded, setLoaded] = useState<Loaded | null>(null);
    const mounted = useRef(false);
    const host = useRef<HTMLDivElement>(null);

    useEffect(() => { void loadData(runner()).then(setLoaded); }, []);

    useEffect(() => {
        if (!loaded || mounted.current || !host.current) return;
        mounted.current = true;           // the scene module binds window listeners: mount exactly once
        installGlobals();
        const run = runner();
        const w = window as unknown as { MIZAN_QUERY?: (f: Filters) => Promise<unknown> };
        if (loaded.mode === "live" && run) w.MIZAN_QUERY = (f) => queryFiltered(run, f);   // live filter bar
        else if (query) w.MIZAN_QUERY = query;
        else delete w.MIZAN_QUERY;
        mountScenes(loaded.data);
    }, [loaded]);

    if (!loaded) {
        return <div className="mizan-loading">Loading live figures from the semantic model…</div>;
    }
    return (
        <>
            <div ref={host} dangerouslySetInnerHTML={{ __html: pageHtml }} />
            <div className={`mizan-source ${loaded.mode}`} role="status">{loaded.note}</div>
        </>
    );
}

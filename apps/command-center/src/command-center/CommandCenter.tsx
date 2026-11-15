import { useEffect, useRef, useState, type ReactElement } from "react";

import { connectorConfigs } from "@/lib/connectors";
import { getRayfinClient } from "@/lib/rayfin-client";
import { installGlobals } from "./legacy/globals.js";
import pageHtml from "./legacy/page.html?raw";
import "./legacy/page.css";
import "./app.css";
import { mountScenes } from "./legacy/scenes.js";
import { CONNECTOR, loadData, type Loaded, type Runner } from "./load";

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

export function CommandCenter(): ReactElement {
    const [loaded, setLoaded] = useState<Loaded | null>(null);
    const mounted = useRef(false);
    const host = useRef<HTMLDivElement>(null);

    useEffect(() => { void loadData(runner()).then(setLoaded); }, []);

    useEffect(() => {
        if (!loaded || mounted.current || !host.current) return;
        mounted.current = true;           // the scene module binds window listeners: mount exactly once
        installGlobals();
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

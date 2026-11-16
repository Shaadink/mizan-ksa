// Runs the Ask MIZAN agent tools and the number check of command_center/template.html against a data file.
// Usage: node tests/ask_agent_harness.cjs <template.html> <data.json>   (jobs as JSON on stdin)
// jobs: {"tools": [[role, name, argsJson]], "verify": [[text, [toolContent...]]]}
const fs = require("fs");
const [tplPath, dataPath] = process.argv.slice(2);
const tpl = fs.readFileSync(tplPath, "utf8");
const a = tpl.indexOf("/* =========================================================== 13 ASK MIZAN */");
const b = tpl.indexOf("/* =========================================================== 01 PULSE */", a);
const line = (start) => { const i = tpl.indexOf(start); if (i < 0) throw new Error(start); return tpl.slice(i, tpl.indexOf("\n", i) + 1); };
const h0 = tpl.indexOf("function H(s)"), h1 = tpl.indexOf("const fmtI", h0);
const D = JSON.parse(fs.readFileSync(dataPath, "utf8"));
const jobs = JSON.parse(fs.readFileSync(0, "utf8"));
const src = `${tpl.slice(h0, tpl.indexOf("\n", h1) + 1)}${line("function hStr(h)")}${line("const PAYNAME")}
const window = { MIZAN_DAX: { recon_totals: "EVALUATE ROW(...)" } };
const C = { gold: "", dim: "", ok: "", warn: "", crit: "" };
const F = { from: "", to: "", mid: "", city: "", status: "", method: "", egs: "", flow: "", state: "" };
const FLABEL = {}; const BASE = D; const riyadh = x => x; const $ = () => ({});
${tpl.slice(a, b)}
return (async () => {
  const tools = [];
  for (const [role, name, args] of jobs.tools) tools.push(await agentRunTool(name, args, role));
  const verify = jobs.verify.map(([text, contents]) => agentVerify(text, contents.map(c => ({ role: "tool", content: c }))));
  return { tools: tools.map(t => ({ result: t.result, tables: t.tables || [], queries: t.queries || [] })), verify, names: Object.keys(AGENT_TOOLS) };
})();`;
new Function("D", "jobs", src)(D, jobs).then(r => process.stdout.write(JSON.stringify(r)));

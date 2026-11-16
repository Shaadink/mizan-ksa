// Runs the Ask MIZAN logic of command_center/template.html against a data file, without a browser.
// Usage: node tests/ask_mizan_harness.cjs <template.html> <data.json>   (questions as JSON on stdin)
// Prints [{role, q, kind, code, text, tables}] as JSON.
const fs = require("fs");
const [tplPath, dataPath] = process.argv.slice(2);
const tpl = fs.readFileSync(tplPath, "utf8");
const a = tpl.indexOf("/* =========================================================== 13 ASK MIZAN */");
const b = tpl.indexOf("/* =========================================================== 01 PULSE */", a);
if (a < 0 || b < 0) throw new Error("Ask MIZAN block not found");
const h0 = tpl.indexOf("function H(s)"), h1 = tpl.indexOf("const fmtI", h0);
const helpers = tpl.slice(h0, tpl.indexOf("\n", h1) + 1);
const pn0 = tpl.indexOf("const PAYNAME");
const payname = tpl.slice(pn0, tpl.indexOf("\n", pn0) + 1);
const D = JSON.parse(fs.readFileSync(dataPath, "utf8"));
const questions = JSON.parse(fs.readFileSync(0, "utf8"));
const src = `${helpers}${payname}
const C = { gold: "", dim: "", ok: "", warn: "", crit: "" };
const F = { from: "", to: "", mid: "", city: "", status: "", method: "", egs: "", flow: "", state: "" };
const FLABEL = {}; const BASE = D; const riyadh = x => x; const $ = () => ({});
${tpl.slice(a, b)}
return questions.map(([role, q]) => { const r = askAnswer(q, role);
  return { role, q, kind: r.kind, code: r.code || null, text: r.text, tables: r.intent ? r.intent.tables : [] }; });`;
process.stdout.write(JSON.stringify(new Function("D", "questions", src)(D, questions)));

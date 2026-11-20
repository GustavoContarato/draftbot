// Testes da página (index.html) com dados reais da OP.GG (tests/fixtures) e um navegador simulado.
// Rodar:  node tests/test_page.mjs
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const META = JSON.parse(fs.readFileSync(path.join(ROOT, "tests/fixtures/meta.json"), "utf8"));
const TABLES = JSON.parse(fs.readFileSync(path.join(ROOT, "tests/fixtures/tables.json"), "utf8"));
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];

// ---------- navegador simulado ----------
const els = {};
const mk = id => ({ id, innerHTML: "", textContent: "", value: "", checked: true, style: {}, className: "",
  classList: { toggle() {}, add() {}, remove() {} }, addEventListener() {}, insertAdjacentHTML(p, h) { this.innerHTML = h + this.innerHTML; },
  scrollIntoView() {}, dataset: {} });
globalThis.document = { getElementById: id => els[id] || (els[id] = mk(id)), querySelectorAll: () => [], body: { classList: { toggle() {} } } };
globalThis.window = { addEventListener() {}, open() { return {}; } };
globalThis.history = { replaceState() {} };
globalThis.localStorage = { getItem: () => null, setItem() {} };
globalThis.location = { hostname: "127.0.0.1", hash: "", origin: "http://127.0.0.1:8765", pathname: "/" };
globalThis.DRAFTBOT_RETRY_MS = 50;
globalThis.setInterval = () => 0;   // sem renovação periódica durante os testes

// respostas do programa local (controladas pelos testes)
const S = { failNext: {}, calls: [], meta: META };
const ok = data => ({ json: async () => ({ ok: true, data }) });
const fail = msg => ({ json: async () => ({ ok: false, error: msg }) });
globalThis.fetch = async (url) => {
  const u = new URL(url, "http://127.0.0.1:8765"), q = Object.fromEntries(u.searchParams);
  S.calls.push(u.pathname + u.search);
  if (u.pathname === "/api/state") return { json: async () => ({ connected: false, message: "teste" }) };
  if (u.pathname === "/api/meta") return ok(S.meta);
  if (u.pathname === "/api/version") return { json: async () => ({ ok: true, version: "teste" }) };
  if (u.pathname === "/api/table") {
    const role = { adc: "adc", top: "top", jungle: "jg", mid: "mid", support: "sup" }[q.pos];
    const key = role + "|" + q.champ;
    if (S.failNext[key]) { S.failNext[key]--; return fail("HTTP Error 503"); }
    const t = TABLES[key];
    return t ? ok({ champ: q.champ, pos: q.pos, rows: t.rows }) : fail("sem dados");
  }
  if (u.pathname === "/api/synergy") return ok([]);
  return fail("não simulado: " + u.pathname);
};

// avalia o script da página e expõe o que os testes precisam em __T
globalThis.__T = {};
(0, eval)(script.replace("setTimeout(poll,1000);", "") +
  `;Object.assign(globalThis.__T,{st:()=>st,D,update,rankRole,chanceOf,placeEnemies,resolve,EMPTY,loadMeta,
     registerChamp,metaEntry,blindProfile,setAcct:a=>{D.acct=a;}});`);
const sleep = ms => new Promise(r => setTimeout(r, ms));

// ---------- mini framework ----------
let passed = 0, failed = 0;
async function test(name, fn) {
  try { await fn(); passed++; console.log("  ok  ", name); }
  catch (e) { failed++; console.log("  FALHOU", name, "\n        ", e.message); }
}
function assert(c, msg) { if (!c) throw new Error(msg || "falhou"); }
async function settle() {   // espera todos os dados pedidos chegarem
  for (let i = 0; i < 200; i++) {
    __T.update(); await sleep(5);
    if (!Object.keys(__T.D.pending).length) { __T.update(); return; }
  }
  throw new Error("dados não chegaram");
}
const strip = s => s.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
const rows = id => strip(els[id].innerHTML).split(/ Build ?/).filter(Boolean);
function draft(role, enemy = {}, ally = {}, bans = []) {
  const s = __T.st(); s.role = role; s.ally = Object.assign(__T.EMPTY(), ally); s.enemy = Object.assign(__T.EMPTY(), enemy);
  s.bans = bans; s.pins = {};
}
const g = (champ, pos, n, w, queue = 420) => Array.from({ length: n }, (_, i) => ({ champ, pos, win: i < w, k: 5, d: 3, a: 6, queue, ts: 1000 - i }));
const ACC = {
  A: { name: "ContaA", games: [...g("Ziggs", "adc", 10, 7), ...g("Jinx", "adc", 8, 4)], mastery: [{ champ: "Ziggs", level: 7, points: 200000 }],
       owned: ["Ziggs", "Jinx", "Kog'Maw", "Xayah", "Twitch", "Zeri", "Miss Fortune", "Smolder"] },
  B: { name: "ContaB", games: [...g("Jhin", "adc", 12, 7)], mastery: [{ champ: "Jhin", level: 6, points: 90000 }],
       owned: ["Jhin", "Xayah", "Jinx", "Miss Fortune", "Twitch"] },
};

// ---------- testes ----------
await __T.loadMeta();
console.log("Página");

await test("estatísticas carregadas e patch exibido", async () => {
  assert(__T.D.meta && __T.D.meta.positions.adc.length > 20, "meta");
  assert(els.patch.textContent.includes("26.22"), els.patch.textContent);
});

await test("às cegas: chance em % e campeões fortes do patch no topo", async () => {
  __T.setAcct(null); draft("adc"); await settle();
  const r = rows("recs");
  assert(r.length === 8, "8 recomendações");
  assert(/\d+,\d% chance/.test(r[0]), r[0]);
  const top3 = r.slice(0, 3).join(" ");
  assert(top3.includes("Kog'Maw") || top3.includes("Xayah"), top3);
});

await test("counter: picks fora da rota não ficam no topo", async () => {
  draft("adc", { adc: "Draven" }); await settle();
  const list = __T.rankRole("adc").slice(0, 3);
  for (const x of list) {
    const e = __T.metaEntry("adc", x.n);
    assert(!e || e.role_rate >= 0.35, `${x.n} é pick fora da rota (${e && e.role_rate})`);
  }
  assert(rows("recs")[0].includes("contra Draven"), rows("recs")[0]);
});

await test("coluna Recomendações é igual para qualquer conta", async () => {
  draft("adc");
  __T.setAcct(JSON.parse(JSON.stringify(ACC.A))); await settle(); const a = rows("recs");
  __T.setAcct(JSON.parse(JSON.stringify(ACC.B))); await settle(); const b = rows("recs");
  const clean = l => l.map(x => x.replace(/ (SEU POOL|VOCÊ NÃO TEM)/g, ""));
  assert(JSON.stringify(clean(a)) === JSON.stringify(clean(b)), "\nA: " + clean(a).join("\n   ") + "\nB: " + clean(b).join("\n   "));
  assert(b.some(x => x.includes("VOCÊ NÃO TEM")), "marca campeões que a conta não tem");
});

await test("Seu pool usa a experiência pessoal e respeita a rota", async () => {
  draft("adc"); __T.setAcct(JSON.parse(JSON.stringify(ACC.A))); await settle();
  const p = rows("pool");
  assert(p[0].includes("Ziggs") && p[0].includes("10 jogos"), p[0]);
  assert(els.poolSub.textContent.includes("18 das suas 18"), els.poolSub.textContent);
  const geral = __T.chanceOf("adc", "Jinx").p, pessoal = __T.chanceOf("adc", "Jinx", true).p;
  assert(geral !== pessoal, "a chance pessoal deve diferir da geral");
});

await test("rota inimiga fixada pelo usuário é respeitada", async () => {
  draft("adc"); const s = __T.st();
  const auto = __T.placeEnemies(["Aatrox", "Malzahar", "Draven", "Leona", "Kha'Zix"]);
  assert(auto.mid === "Malzahar" && auto.top === "Aatrox", JSON.stringify(auto));
  s.pins = { "Malzahar": "top" };
  const fixed = __T.placeEnemies(["Aatrox", "Malzahar", "Draven", "Leona", "Kha'Zix"]);
  assert(fixed.top === "Malzahar" && fixed.adc === "Draven", JSON.stringify(fixed));
});

await test("campeão novo (fora da lista do app) é reconhecido", async () => {
  assert(!__T.resolve("Zyrael"));
  __T.registerChamp("Zyrael", "Zyrael");
  assert(__T.resolve("zyrael") === "Zyrael");
});

await test("falha temporária: tenta de novo e recupera (erro corrigido)", async () => {
  __T.setAcct(null); draft("top", { top: "Darius" });
  S.failNext["top|Darius"] = 1;
  delete __T.D.tables["top|Darius"];
  await settle();
  assert(__T.D.tables["top|Darius"] === null, "primeira tentativa falha");
  await sleep(120);                       // passa o tempo de nova tentativa (50 ms nos testes)
  await settle();
  assert(__T.D.tables["top|Darius"] && __T.D.tables["top|Darius"].rows.length > 10, "deveria ter recuperado");
  assert(rows("recs")[0].includes("contra Darius"), rows("recs")[0]);
});

await test("patch novo descarta dados antigos ao renovar (erro corrigido)", async () => {
  assert(Object.keys(__T.D.tables).length > 0);
  S.meta = Object.assign({}, META, { version: "16.23" });
  await __T.loadMeta();
  assert(Object.keys(__T.D.tables).length === 0, "tabelas do patch antigo deveriam ser descartadas");
  assert(els.patch.textContent.includes("26.23"), els.patch.textContent);
  S.meta = META; await __T.loadMeta();
});

await test("dia de patch novo: avisa a mistura e renova ao terminar", async () => {
  await settle();
  const until = Date.now() / 1000 + 20 * 3600;
  S.meta = Object.assign({}, META, { version: "16.23", blend: { prev: "16.22", until, weight: 0.8 } });
  await __T.loadMeta();
  assert(els.patch.textContent.includes("26.23 + 26.22"), els.patch.textContent);
  assert(strip(els.banner.innerHTML).includes("também usam o patch 26.22"), els.banner.innerHTML);
  __T.D.tables["x|y"] = { rows: [] };
  S.meta = Object.assign({}, META, { version: "16.23", blend: null });   // passou o primeiro dia
  await __T.loadMeta();
  assert(!("x|y" in __T.D.tables), "deveria buscar de novo só com o patch novo");
  assert(els.banner.innerHTML === "", els.banner.innerHTML);
  S.meta = META; await __T.loadMeta();
});

await test("patch recém-saído: sem falso 'Seguro às cegas' e com aviso de poucos dados", async () => {
  const thin = JSON.parse(JSON.stringify(META));
  Object.values(thin.positions).forEach(l => l.forEach(x => { x.play = Math.round(x.play / 100); x.win = Math.round(x.win / 100); }));
  thin.version = "16.24";
  S.meta = thin; await __T.loadMeta();
  assert(strip(els.banner.innerHTML).includes("poucas partidas"), els.banner.innerHTML);
  // tabela com pouquíssimos jogos e nenhum counter visível
  const tiny = { rows: ["Jinx", "Caitlyn", "Ezreal", "Kai'Sa"].map(n => ({ name: n, play: 120, win: 62 })) };
  __T.D.tables["adc|Xayah"] = tiny;
  const bp = __T.blindProfile("adc", "Xayah");
  assert(bp && !bp.sure, "deveria marcar poucos dados");
  assert(bp.gap > bp.raw + 0.01, `risco deveria ir para o típico: ${bp.raw} → ${bp.gap}`);
  draft("adc"); await settle();
  const x = __T.chanceOf("adc", "Xayah");
  assert(!x.R.some(r => r[1] === "Seguro às cegas"), JSON.stringify(x.R));
  assert(x.R.some(r => r[1].startsWith("Poucas partidas de confronto")), JSON.stringify(x.R));
  S.meta = META; delete __T.D.tables["adc|Xayah"]; await __T.loadMeta();
  assert(!strip(els.banner.innerHTML).includes("poucas partidas"));
});

await test("pool: 1 vitória não põe o campeão acima do que a média geral justifica", async () => {
  draft("adc"); await settle();
  __T.setAcct({ name: "X", games: [...g("Kog'Maw", "adc", 1, 1), ...g("Jinx", "adc", 30, 21)], mastery: [], owned: ["Kog'Maw", "Jinx"] });
  const um = __T.chanceOf("adc", "Kog'Maw", true), muitos = __T.chanceOf("adc", "Jinx", true);
  assert(um.p <= um.pGeral + 0.002, `1 jogo: ${um.pGeral} → ${um.p}`);
  assert(muitos.p >= muitos.pGeral + 0.02, `30 jogos a 70%: ${muitos.pGeral} → ${muitos.p}`);
  __T.setAcct(null);
});

console.log(`\n${passed} ok, ${failed} falharam`);
process.exit(failed ? 1 : 0);

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
  if (u.pathname === "/api/build" && S.build) return ok(S.build);
  if (u.pathname === "/api/riot") return ok(S.riot || { hasKey: false, state: "sem chave", matches: 0 });
  return fail("não simulado: " + u.pathname);
};

// avalia o script da página e expõe o que os testes precisam em __T
globalThis.__T = {};
(0, eval)(script.replace("setTimeout(poll,1000);", "") +
  `;Object.assign(globalThis.__T,{st:()=>st,D,update,rankRole,chanceOf,placeEnemies,resolve,EMPTY,loadMeta,
     registerChamp,metaEntry,blindProfile,loadRiot,setAcct:a=>{D.acct=a;}});`);
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

await test("Seu pool: só os campeões da conta, com a mesma chance da coluna do meio", async () => {
  draft("adc"); __T.setAcct(JSON.parse(JSON.stringify(ACC.A))); await settle();
  const p = rows("pool"), r = rows("recs");
  assert(p.some(x => x.includes("Ziggs") && x.includes("10 jogos")), p.join("\n"));
  assert(els.poolSub.textContent.includes("18 das suas 18"), els.poolSub.textContent);
  const of = (l, n) => l.find(x => x.replace(/^\S+ /, "").startsWith(n + " "));
  for (const n of ["Ziggs", "Jinx"]) {
    const inPool = of(p, n), inRec = of(r, n);
    const ch = x => x && (x.match(/(\d+,\d)%\s*chance/i) || [])[1];
    const pc = ch(inPool), rc = ch(inRec);
    assert(pc, `${n}: chance não encontrada no pool: ${inPool}`);
    assert(!inRec || pc === rc, `${n}: pool ${pc} × recomendações ${rc}`);
    assert(Math.abs(__T.chanceOf("adc", n).p - (parseFloat(pc.replace(",", ".")) / 100)) < 0.0006, `${n}: ${pc} × ${__T.chanceOf("adc", n).p} rec=${rc}`);
  }
  assert(!["Xayah", "Twitch", "Kai'Sa"].some(n => of(p, n)), "só campeões que a conta joga");
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

await test("build: várias páginas de runas, a recomendada primeiro, e ícones do jogo", async () => {
  const pg = (src, ids, extra = {}) => Object.assign({ src, primary: 8000, secondary: 8400, ids, names: ids.slice(0, 6).map(i => "R" + i),
    play: src === "riot" ? 0 : 3000, win: 1600, pick: 0.4 }, extra);
  S.build = { champ: "Jinx", pos: "adc", opp: "", vs: null, tip: "", advantage: "", style: "", source: "general", note: "",
    runes: [pg("general", [8008, 9111, 9104, 8014, 8473, 8451, 5005, 5008, 5011], { rec: true }),
            pg("riot", [8021, 9111, 9104, 8014, 8473, 8451, 5005, 5008, 5011], { label: "Agilidade" }),
            pg("riot", [8005, 9111, 9104, 8014, 8473, 8451, 5005, 5008, 5011], { label: "Pressione" })],
    starter: [{ ids: [1055, 2003], names: [], play: 1, win: 1 }], core: [{ ids: [3031, 3036], names: [], play: 900, win: 500 }],
    boots: [], spells: [{ ids: [4, 7] }], late: [], order: [], priority: [] };
  draft("adc", {}, { adc: "Jinx" }); await settle();
  const h = els.build.innerHTML;
  assert((h.match(/data-page="/g) || []).length === 3, "3 opções de runas");
  assert((h.match(/RECOMENDADA/g) || []).length === 1 && h.indexOf("RECOMENDADA") < h.indexOf('data-page="1"'), "recomendada é a primeira");
  assert(h.includes("Sugestão do cliente (Riot)") && h.includes("sem estatística"));
  for (const k of ["champ&id=Jinx", "perk&id=8008", "style&id=8400", "item&id=3031", "spell&id=4"])
    assert(h.includes("/api/icon?k=" + k), "ícone " + k);
  assert(strip(els.recs.innerHTML).length && els.recs.innerHTML.includes("/api/icon?k=champ"), "ícones nas recomendações");
  S.build = null;
});

await test("dados Mestre+ da Riot: % por runa, builds e itens contra o tipo de time", async () => {
  const pg = (src, ids, extra = {}) => Object.assign({ src, primary: 8000, secondary: 8400, ids, names: ids.slice(0, 6).map(i => "R" + i),
    play: 3000, win: 1600, pick: 0.4 }, extra);
  const st = (n, w) => ({ n, w, wr: w / n });
  S.build = { champ: "Jinx", pos: "adc", opp: "Ezreal", vs: null, tip: "", advantage: "", style: "", source: "general", note: "",
    runes: [pg("riot-stats", [8008, 9111, 9104, 8014, 8473, 8451, 5005, 5008, 5011], { rec: true, play: 300, win: 170, master: { n: 300, w: 170 } }),
            pg("general", [8021, 9111, 9104, 8014, 8473, 8451, 5005, 5008, 5011], { master: { n: 80, w: 35 } })],
    starter: [], core: [], boots: [], spells: [{ ids: [4, 7] }], late: [], order: [], priority: [],
    riot: { n: 380, w: 205, wr: 0.54, slots: { p0: { "8008": st(300, 170), "8021": st(80, 35) }, s: { "8473": st(380, 205) } },
      spells: [{ key: "4,7", n: 350, w: 190, wr: 0.543 }], core3: [{ key: "3031,3085,3036", n: 120, w: 70, wr: 0.583 }],
      boots: [{ key: "3006", n: 360, w: 195, wr: 0.54 }],
      comp: { type: "ap", n: 150, w: 80, items: [{ key: "3156", n: 40, w: 27, wr: 0.675, lift: 0.08 }] },
      vs: { opp: "Ezreal", n: 60, w: 33, wr: 0.55, core2: [{ key: "3031,3085", n: 30, w: 18, wr: 0.6 }] } } };
  S.riot = { hasKey: true, state: "coletando", patch: "16.23", region: "BR", matches: 380, local: 300, remote: 80 };
  draft("adc", { adc: "Ezreal" }, { adc: "Jinx" }); await settle(); await __T.loadRiot();
  const h = strip(els.build.innerHTML);
  assert(h.includes("Mestre+ do patch (API da Riot)"), "página Mestre+");
  assert(h.includes("56,7% · 300"), "% da runa na página: " + h.slice(0, 400));
  assert(h.includes("Contra time de dano mágico") && h.includes("+8,0 pts"), "item contra o tipo de time");
  assert(h.includes("Contra Ezreal · 55,0% em 60 partidas"), "recorte do oponente");
  assert(h.includes("Mestre+: 43,8% · 80"), "estatística Mestre+ ao lado da página da OP.GG");
  const box = strip(els.riotBox.innerHTML);
  assert(box.includes("Coletando partidas Mestre+ do patch 26.23") && box.includes("380 partidas"), box);
  S.riot = null; await __T.loadRiot();
  assert(strip(els.riotBox.innerHTML).includes("developer.riotgames.com"), "sem chave: explica como conseguir");
  S.build = null;
});

console.log(`\n${passed} ok, ${failed} falharam`);
process.exit(failed ? 1 : 0);

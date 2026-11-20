"""Estatísticas próprias a partir da API oficial da Riot (partidas ranqueadas Mestre+ do patch atual).

Usado pelo DraftBot (coleta no PC enquanto ele está aberto) e por tools/collect.py (coleta diária no GitHub).
Só biblioteca padrão. As contagens são somáveis: dois arquivos de estatística do mesmo patch podem ser
juntados com merge().
"""
import json
import os
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# servidor do cliente (LCU /riotclient/region-locale) → (plataforma, região da match-v5)
REGIONS = {
    "BR": ("br1", "americas"), "NA": ("na1", "americas"), "LA1": ("la1", "americas"), "LAN": ("la1", "americas"),
    "LA2": ("la2", "americas"), "LAS": ("la2", "americas"), "OC1": ("oc1", "sea"), "OCE": ("oc1", "sea"),
    "EUW": ("euw1", "europe"), "EUNE": ("eun1", "europe"), "TR": ("tr1", "europe"), "RU": ("ru", "europe"),
    "ME": ("me1", "europe"), "KR": ("kr", "asia"), "JP": ("jp1", "asia"), "SG": ("sg2", "sea"),
    "TW": ("tw2", "sea"), "VN": ("vn2", "sea"),
}
POS = {"TOP": "top", "JUNGLE": "jungle", "MIDDLE": "mid", "BOTTOM": "adc", "UTILITY": "support"}
QUEUE = 420                     # ranqueada solo/duo
SEED_TIERS = ("challengerleagues", "grandmasterleagues", "masterleagues")
STATS_VERSION = 1


class RiotError(Exception):
    def __init__(self, status, msg=""):
        super().__init__(f"HTTP {status} {msg}".strip())
        self.status = status


class Limiter:
    """Limites da chave (por servidor): 20 pedidos/s e 100 a cada 2 min. Fica um pouco abaixo para sobrar."""

    def __init__(self, windows=((1.0, 18), (120.0, 95))):
        self.windows = windows
        self.calls = []
        self.block_until = 0.0
        self.lock = threading.Lock()

    def wait(self, stop=None):
        while True:
            with self.lock:
                now = time.time()
                self.calls = [t for t in self.calls if now - t < max(w for w, _ in self.windows)]
                delay = max(0.0, self.block_until - now)
                for win, cap in self.windows:
                    inside = [t for t in self.calls if now - t < win]
                    if len(inside) >= cap:
                        delay = max(delay, win - (now - inside[0]) + 0.05)
                if delay <= 0:
                    self.calls.append(now)
                    return
            if stop is not None and stop.wait(min(delay, 5)):
                raise InterruptedError()
            elif stop is None:
                time.sleep(min(delay, 5))

    def penalize(self, secs):
        with self.lock:
            self.block_until = max(self.block_until, time.time() + secs)


class RiotAPI:
    def __init__(self, key, region="BR", base=None, ua="DraftBot", windows=None):
        self.key = key.strip()
        # com um servidor de testes no lugar da Riot, sem esperar pelos limites reais
        self.windows = windows or (((1.0, 500), (120.0, 100000)) if base else ((1.0, 18), (120.0, 95)))
        self.platform, self.cluster = REGIONS.get(region.upper(), REGIONS["BR"])
        self.base = base                     # testes: um servidor falso no lugar dos da Riot
        self.ua = ua
        self.limiters = {}

    def _host(self, which):
        if self.base:
            return self.base
        return f"https://{self.platform if which == 'platform' else self.cluster}.api.riotgames.com"

    def get(self, which, path, params=None, stop=None, tries=4):
        lim = self.limiters.setdefault(which, Limiter(self.windows))
        url = self._host(which) + path + ("?" + urllib.parse.urlencode(params) if params else "")
        for attempt in range(tries):
            lim.wait(stop)
            req = urllib.request.Request(url, headers={"X-Riot-Token": self.key, "User-Agent": self.ua})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    lim.penalize(float(e.headers.get("Retry-After") or 10))
                    continue
                if e.code in (500, 502, 503, 504) and attempt < tries - 1:
                    lim.penalize(2 ** attempt)
                    continue
                raise RiotError(e.code, {401: "chave inválida", 403: "chave inválida ou vencida",
                                         404: "não encontrado"}.get(e.code, ""))
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt < tries - 1:
                    lim.penalize(2 ** attempt)
                    continue
                raise RiotError(0, str(e))
        raise RiotError(429, "limite de pedidos")

    def check(self):
        """Confere se a chave funciona (uma chamada barata)."""
        self.get("platform", "/lol/status/v4/platform-data", tries=1)
        return True


# ---------------------------------------------------------------- itens (para achar os "completos")
class ItemInfo:
    """Classifica itens pelo Data Dragon: lendários (completos), botas e iniciais."""

    def __init__(self, data=None):
        self.legendary, self.boots, self.consum = set(), set(), set()
        if data:
            self.load(data)

    def load(self, data):
        for sid, it in (data.get("data") or {}).items():
            try:
                iid = int(sid)
            except ValueError:
                continue
            tags = set(it.get("tags") or [])
            maps = it.get("maps") or {}
            if maps and not maps.get("11", False):
                continue
            gold = (it.get("gold") or {}).get("total", 0)
            if "Consumable" in tags or "Trinket" in tags:
                self.consum.add(iid)
            if "Boots" in tags and it.get("from"):
                self.boots.add(iid)
            elif not it.get("into") and gold >= 2000 and "Consumable" not in tags and "Boots" not in tags:
                self.legendary.add(iid)

    @staticmethod
    def fetch(ddragon="https://ddragon.leagueoflegends.com", version=None, ua="DraftBot"):
        def get(u):
            req = urllib.request.Request(u, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        version = version or get(ddragon + "/api/versions.json")[0]
        return ItemInfo(get(f"{ddragon}/cdn/{version}/data/en_US/item.json"))


# ---------------------------------------------------------------- agregação
def _inc(d, key, win):
    e = d.get(key)
    if e is None:
        d[key] = [1, int(win)]
    else:
        e[0] += 1
        e[1] += int(win)


def patch_of(game_version):
    p = str(game_version).split(".")
    return f"{p[0]}.{p[1]}" if len(p) >= 2 else ""


def comp_type(team_magic, team_phys):
    tot = (team_magic or 0) + (team_phys or 0)
    if tot <= 0:
        return "mix"
    ap = team_magic / tot
    return "ap" if ap >= 0.55 else "ad" if ap <= 0.30 else "mix"


def new_stats(patch, region):
    return {"v": STATS_VERSION, "patch": patch, "region": region, "matches": 0, "ids": [], "champs": {},
            "updated": 0}


def _pages_key(p):
    return ",".join(str(x) for x in p)


def add_match(stats, match, timeline, items):
    """Soma uma partida (match-v5 + timeline) às estatísticas. Devolve False se não for do patch/fila."""
    info = (match or {}).get("info") or {}
    if info.get("queueId") != QUEUE or patch_of(info.get("gameVersion")) != stats["patch"]:
        return False
    parts = info.get("participants") or []
    if len(parts) != 10:
        return False
    # perfil de dano de cada time (para "contra time de dano mágico/físico")
    dmg = {}
    for p in parts:
        t = dmg.setdefault(p.get("teamId"), [0, 0])
        t[0] += p.get("magicDamageDealtToChampions", 0)
        t[1] += p.get("physicalDamageDealtToChampions", 0)
    # compras e habilidades na ordem, da timeline
    buys, skills = {}, {}
    for fr in ((timeline or {}).get("info") or {}).get("frames") or []:
        for ev in fr.get("events") or []:
            pid, ty = ev.get("participantId"), ev.get("type")
            if ty == "ITEM_PURCHASED":
                buys.setdefault(pid, []).append((ev.get("timestamp", 0), ev.get("itemId")))
            elif ty == "ITEM_UNDO":
                lst = buys.get(pid) or []
                for i in range(len(lst) - 1, -1, -1):
                    if lst[i][1] == ev.get("beforeId"):
                        del lst[i]
                        break
            elif ty == "SKILL_LEVEL_UP" and ev.get("levelUpType", "NORMAL") == "NORMAL":
                skills.setdefault(pid, []).append(ev.get("skillSlot"))
    lane = {}
    for p in parts:
        lane[(p.get("teamId"), p.get("teamPosition"))] = p
    for idx, p in enumerate(parts, start=1):
        pos = POS.get(p.get("teamPosition"))
        if not pos:
            continue
        pid = p.get("participantId", idx)
        win = bool(p.get("win"))
        c = stats["champs"].setdefault(f"{p.get('championName')}|{pos}", {"n": 0, "w": 0})
        c["n"] += 1
        c["w"] += int(win)
        # runas
        perks = p.get("perks") or {}
        styles = perks.get("styles") or []
        prim = next((s for s in styles if s.get("description") == "primaryStyle"), None)
        sub = next((s for s in styles if s.get("description") == "subStyle"), None)
        sp = perks.get("statPerks") or {}
        if prim and sub:
            pr = [s.get("perk") for s in prim.get("selections") or []]
            sr = [s.get("perk") for s in sub.get("selections") or []]
            sh = [sp.get("offense"), sp.get("flex"), sp.get("defense")]
            if len(pr) == 4 and len(sr) == 2 and all(sh):
                slots = c.setdefault("slots", {})
                for i, r in enumerate(pr):
                    _inc(slots.setdefault(f"p{i}", {}), str(r), win)
                for r in sr:
                    _inc(slots.setdefault("s", {}), str(r), win)
                _inc(slots.setdefault("sec", {}), str(sub.get("style")), win)
                for i, r in enumerate(sh):
                    _inc(slots.setdefault(f"sh{i}", {}), str(r), win)
                key = f"{prim.get('style')}:{sub.get('style')}:" + _pages_key(pr + sorted(sr) + sh)
                _inc(c.setdefault("pages", {}), key, win)
        # feitiços
        sp2 = sorted([p.get("summoner1Id", 0), p.get("summoner2Id", 0)])
        _inc(c.setdefault("spells", {}), f"{sp2[0]},{sp2[1]}", win)
        # habilidades: ordem em que Q/W/E chegam ao nível máximo (5)
        lv, order = {1: 0, 2: 0, 3: 0}, []
        for s in skills.get(pid) or []:
            if s in lv:
                lv[s] += 1
                if lv[s] == 5:
                    order.append(s)
        for s in sorted(lv, key=lambda k: -lv[k]):
            if s not in order:
                order.append(s)
        _inc(c.setdefault("skills", {}), "".join("QWE"[s - 1] for s in order[:3]), win)
        # itens
        bl = sorted(buys.get(pid) or [])
        start = sorted({it for t, it in bl if t <= 60000 and it})
        if start:
            _inc(c.setdefault("start", {}), _pages_key(start), win)
        core, boots, seen = [], None, set()
        for t, it in bl:
            if it in items.boots and boots is None:
                boots = it
            if it in items.legendary and it not in seen:
                seen.add(it)
                core.append(it)
        if boots:
            _inc(c.setdefault("boots", {}), str(boots), win)
        if len(core) >= 2:
            _inc(c.setdefault("core2", {}), _pages_key(core[:2]), win)
        if len(core) >= 3:
            _inc(c.setdefault("core3", {}), _pages_key(core[:3]), win)
        enemy = 200 if p.get("teamId") == 100 else 100
        ctype = comp_type(*dmg.get(enemy, (0, 0)))
        for it in core:
            _inc(c.setdefault("items", {}), str(it), win)
            _inc(c.setdefault("items_" + ctype, {}), str(it), win)
        _inc(c.setdefault("comp", {}), ctype, win)
        # contra o oponente da rota
        opp = lane.get((enemy, p.get("teamPosition")))
        if opp:
            vs = c.setdefault("vs", {}).setdefault(opp.get("championName"), {"n": 0, "w": 0})
            vs["n"] += 1
            vs["w"] += int(win)
            if prim:
                _inc(vs.setdefault("ks", {}), str((prim.get("selections") or [{}])[0].get("perk")), win)
            if len(core) >= 2:
                _inc(vs.setdefault("core2", {}), _pages_key(core[:2]), win)
            for it in core:
                _inc(vs.setdefault("items", {}), str(it), win)
    stats["matches"] += 1
    stats["updated"] = time.time()
    return True


def _merge_counts(a, b):
    for k, v in b.items():
        if isinstance(v, list):
            e = a.get(k)
            if e is None:
                a[k] = list(v)
            else:
                e[0] += v[0]
                e[1] += v[1]
        elif isinstance(v, dict):
            _merge_counts(a.setdefault(k, {}), v)
        elif isinstance(v, (int, float)) and k in ("n", "w"):
            a[k] = a.get(k, 0) + v


def merge(a, b):
    """Soma b em a (mesmo patch). Partidas repetidas são evitadas pela lista de ids na coleta."""
    if not b or b.get("patch") != a.get("patch"):
        return a
    _merge_counts(a["champs"], b.get("champs") or {})
    a["matches"] = a.get("matches", 0) + b.get("matches", 0)
    a["updated"] = max(a.get("updated", 0), b.get("updated", 0))
    return a


# ---------------------------------------------------------------- resumo para a página
def _rate(nw, k=60, prior=0.5):
    n, w = nw
    return (w + prior * k) / (n + k)


def _top(d, minimum=1, limit=5, prior=0.5):
    rows = [(k, v) for k, v in (d or {}).items() if v[0] >= minimum]
    rows.sort(key=lambda kv: -kv[1][0])
    return [{"key": k, "n": v[0], "w": v[1], "wr": v[1] / v[0], "adj": _rate(v, prior=prior)} for k, v in rows[:limit]]


def summary(stats, champ_id, pos, opp_id=None, enemy_comp=None):
    """O que a página mostra para um campeão/rota: páginas e runas com taxa de vitória, itens em ordem,
    feitiços, habilidades e o recorte da situação (oponente de rota, tipo de dano do time inimigo)."""
    c = (stats or {}).get("champs", {}).get(f"{champ_id}|{pos}")
    if not c or not c.get("n"):
        return None
    base = c["w"] / c["n"]
    out = {"n": c["n"], "w": c["w"], "wr": base, "patch": stats.get("patch"), "matches": stats.get("matches", 0)}
    pages = []
    for row in _top(c.get("pages"), minimum=max(5, c["n"] // 200), limit=6, prior=base):
        prim, sec, ids = row["key"].split(":")
        pages.append(dict(row, primary=int(prim), secondary=int(sec), ids=[int(x) for x in ids.split(",")]))
    out["pages"] = pages
    out["slots"] = {k: {r["key"]: r for r in _top(v, limit=12, prior=base)} for k, v in (c.get("slots") or {}).items()}
    for k in ("spells", "skills", "start", "boots", "core2", "core3"):
        out[k] = _top(c.get(k), minimum=3, limit=5, prior=base)
    items = c.get("items") or {}
    out["items"] = _top(items, minimum=5, limit=15, prior=base)
    sit = []
    if enemy_comp in ("ap", "ad"):
        sub = c.get("items_" + enemy_comp) or {}
        comp_n = (c.get("comp") or {}).get(enemy_comp, [0, 0])
        comp_wr = _rate(comp_n, prior=base) if comp_n[0] else base
        for k, v in sub.items():
            if v[0] < 15 or v[0] > 0.9 * comp_n[0]:      # item de quase todo jogo não diz nada sobre a situação
                continue
            lift = _rate(v, prior=comp_wr) - comp_wr
            if lift >= 0.015:
                sit.append({"key": k, "n": v[0], "w": v[1], "wr": v[1] / v[0], "lift": lift})
        sit.sort(key=lambda r: -r["lift"])
        out["comp"] = {"type": enemy_comp, "n": comp_n[0], "w": comp_n[1], "items": sit[:4]}
    if opp_id:
        vs = (c.get("vs") or {}).get(opp_id)
        if vs and vs.get("n"):
            out["vs"] = {"opp": opp_id, "n": vs["n"], "w": vs["w"], "wr": vs["w"] / vs["n"],
                         "ks": _top(vs.get("ks"), limit=3, prior=base), "core2": _top(vs.get("core2"), limit=3, prior=base),
                         "items": _top(vs.get("items"), minimum=3, limit=6, prior=base)}
    return out


# ---------------------------------------------------------------- coleta
class Collector:
    """Junta partidas Mestre+ do patch atual. Guarda tudo em `path` (JSON) e retoma de onde parou."""

    def __init__(self, api, patch, path, items, region="BR", log=print, skip_ids=None):
        self.api, self.patch, self.path, self.items, self.log = api, patch, path, items, log
        self.region = region.upper()
        self.stats = self._load() or new_stats(patch, self.region)
        self.done = set(self.stats.get("ids") or [])
        self.skip = set(skip_ids or [])
        self.players, self.players_t = [], 0
        self.old_players = set()               # jogadores cujas partidas recentes já são do patch anterior
        self.lock = threading.Lock()
        self.last_error = ""
        self.dirty = False
        self.idle = False

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                s = json.load(f)
            if s.get("patch") == self.patch and s.get("v") == STATS_VERSION:
                return s
        except (OSError, ValueError):
            pass
        return None

    def save(self):
        with self.lock:
            if not self.dirty:
                return
            self.stats["ids"] = sorted(self.done)
            data = json.dumps(self.stats, separators=(",", ":"))
            self.dirty = False
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, self.path)

    def _seed(self, stop):
        if self.players and time.time() - self.players_t < 6 * 3600:
            return
        ps = []
        for tier in SEED_TIERS:
            d = self.api.get("platform", f"/lol/league/v4/{tier}/by-queue/RANKED_SOLO_5x5", stop=stop)
            for e in d.get("entries") or []:
                if e.get("puuid"):
                    ps.append(e["puuid"])
        random.shuffle(ps)
        self.players, self.players_t = ps, time.time()
        self.old_players.clear()
        self.log(f"Riot: {len(ps)} jogadores Mestre+ para coletar.")

    def step(self, stop=None, max_matches=10):
        """Um ciclo: pega um jogador, busca até `max_matches` partidas novas dele. Devolve quantas somou."""
        self._seed(stop)
        cand = [p for p in self.players if p not in self.old_players]
        self.idle = not cand
        if not cand:                     # já vimos todo mundo: espera partidas novas (lista refeita a cada 20 min)
            if time.time() - self.players_t > 1200:
                self.players_t = 0
            return 0
        puuid = random.choice(cand)
        ids = self.api.get("cluster", f"/lol/match/v5/matches/by-puuid/{puuid}/ids",
                           {"queue": QUEUE, "type": "ranked", "start": 0, "count": 20}, stop=stop)
        added = 0
        for mid in ids or []:
            if mid in self.done or mid in self.skip:
                continue
            m = self.api.get("cluster", f"/lol/match/v5/matches/{mid}", stop=stop)
            info = (m or {}).get("info") or {}
            gp = patch_of(info.get("gameVersion"))
            if gp != self.patch:
                with self.lock:
                    self.done.add(mid)
                if gp and tuple(map(int, gp.split("."))) < tuple(map(int, self.patch.split("."))):
                    self.old_players.add(puuid)     # daqui para trás é tudo do patch anterior
                    break
                continue
            tl = self.api.get("cluster", f"/lol/match/v5/matches/{mid}/timeline", stop=stop)
            with self.lock:
                if add_match(self.stats, m, tl, self.items):
                    added += 1
                self.done.add(mid)
                self.dirty = True
            if added >= max_matches:
                break
        else:
            self.old_players.add(puuid)            # já vimos tudo de recente dele
        return added

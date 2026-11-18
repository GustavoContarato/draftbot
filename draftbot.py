"""
DraftBot — assistente de seleção de campeões para todas as rotas.

- Lê a seleção de campeões e a conta logada pela API local do cliente do LoL (LCU).
- Busca estatísticas do patch atual na API pública da OP.GG (mcp-api.op.gg):
  meta por rota, tabelas de confronto, sinergias, runas, itens e habilidades.
- Serve a página do assistente em http://127.0.0.1:8765

Só usa a biblioteca padrão do Python 3.8+.  Rode com:  python draftbot.py

Ele só LÊ a seleção. Quando você pede (ou liga o envio automático), cria uma
página de runas e um conjunto de itens "DraftBot". Nunca bane, escolhe ou
trava campeões por você.
"""
import base64, glob, json, os, platform, re, socket, ssl, subprocess, sys, threading, time, webbrowser, hashlib
import urllib.request, urllib.error
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

VERSION = "2.5.0"
PORT = int(os.environ.get("DRAFTBOT_PORT", "8765"))
# Rodando como executável (Nuitka ou PyInstaller) ou como script Python
FROZEN = bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()
HERE = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))   # onde está a página
APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0])) if FROZEN else HERE           # onde está o .exe / .py
# Dados (cache, registro): ao lado do script; no .exe, numa pasta do usuário que sempre aceita gravação
DATA_DIR = os.environ.get("DRAFTBOT_DATA") or (
    os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "DraftBot") if FROZEN else HERE)
os.makedirs(DATA_DIR, exist_ok=True)
PAGE = os.path.join(HERE, "index.html")
ICON = os.path.join(HERE, "assets", "draftbot.ico")
CACHE_FILE = os.path.join(DATA_DIR, "cache_opgg.json")
PREV_FILE = os.path.join(DATA_DIR, "cache_patch_anterior.json")
LOG_FILE = os.path.join(DATA_DIR, "draftbot.log")
CONFIG_FILE = next((p for p in (os.path.join(APP_DIR, "config.json"), os.path.join(DATA_DIR, "config.json"))
                    if os.path.exists(p)), os.path.join(APP_DIR, "config.json"))
CACHE_TTL = 6 * 3600            # dados da OP.GG: atualizados diariamente
CACHE_KEEP = 48 * 3600          # entradas mais velhas que isso são apagadas do arquivo
BLEND_SECS = 24 * 3600          # no 1º dia de patch novo, mistura com o patch anterior (peso caindo de 1 a 0)
OPGG_URL = os.environ.get("DRAFTBOT_OPGG", "https://mcp-api.op.gg/mcp")
LANG = "pt_BR"
MIN_BUILD_SAMPLE = 150          # abaixo disso, a build do confronto é considerada rara

# Configuração opcional (config.json ao lado do programa):
#   {"update_url": "https://.../version.json"}   → aviso de nova versão
#   version.json: {"version": "2.2", "url": "https://.../DraftBot.zip", "notes": "o que mudou"}
CONFIG = {}
try:
    with open(CONFIG_FILE, encoding="utf-8") as _f:
        CONFIG = json.load(_f)
except Exception:
    CONFIG = {}
def _builtin_update_url():
    """Endereço do aviso de versão embutido no .exe pelo GitHub (arquivo update_url.txt)."""
    try:
        with open(os.path.join(HERE, "update_url.txt"), encoding="utf-8-sig") as f:
            return f.read().strip()
    except Exception:
        return ""


UPDATE_URL = os.environ.get("DRAFTBOT_UPDATE_URL") or CONFIG.get("update_url", "") or _builtin_update_url()

# O cliente usa um certificado próprio em 127.0.0.1: a verificação TLS é
# desligada SOMENTE para essa conexão local. A OP.GG usa verificação normal.
_LOCAL_SSL = ssl.create_default_context()
_LOCAL_SSL.check_hostname = False
_LOCAL_SSL.verify_mode = ssl.CERT_NONE

LOCKFILE_GUESSES = [
    r"C:\Riot Games\League of Legends\lockfile",
    r"D:\Riot Games\League of Legends\lockfile",
    r"E:\Riot Games\League of Legends\lockfile",
    r"C:\Program Files\Riot Games\League of Legends\lockfile",
    r"C:\Program Files (x86)\Riot Games\League of Legends\lockfile",
    "/Applications/League of Legends.app/Contents/LoL/lockfile",
]

LOGS = deque(maxlen=200)


def log(*a):
    line = time.strftime("[%H:%M:%S] ") + " ".join(str(x) for x in a)
    LOGS.append(line)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:   # registro em arquivo (ajuda no diagnóstico); recomeça ao passar de 1 MB
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1_000_000:
            os.replace(LOG_FILE, LOG_FILE + ".old")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d ") + line + "\n")
    except Exception:
        pass


# =====================================================================
#  OP.GG — leitor do formato compacto ("class X: a,b" + X(1,"a",[...]))
# =====================================================================
class _P:
    def __init__(self, s, classes):
        self.s, self.i, self.c = s, 0, classes

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \n\r\t":
            self.i += 1

    def val(self):
        self.ws()
        ch = self.s[self.i]
        if ch == '"':
            return self.string()
        if ch == "[":
            self.i += 1
            out = []
            self.ws()
            if self.s[self.i] == "]":
                self.i += 1
                return out
            while True:
                out.append(self.val())
                self.ws()
                if self.s[self.i] == ",":
                    self.i += 1
                    continue
                if self.s[self.i] == "]":
                    self.i += 1
                    return out
                raise ValueError("lista malformada em %d" % self.i)
        m = re.compile(r"-?\d+(\.\d+)?([eE][-+]?\d+)?").match(self.s, self.i)
        if m:
            self.i = m.end()
            t = m.group(0)
            return float(t) if ("." in t or "e" in t or "E" in t) else int(t)
        m = re.compile(r"[A-Za-z_][A-Za-z0-9_]*").match(self.s, self.i)
        if not m:
            raise ValueError("símbolo inesperado em %d: %r" % (self.i, self.s[self.i:self.i + 20]))
        name = m.group(0)
        self.i = m.end()
        if name in ("true", "false", "null", "None", "True", "False"):
            return {"true": True, "True": True, "false": False, "False": False}.get(name)
        self.ws()
        if self.i < len(self.s) and self.s[self.i] == "(":
            self.i += 1
            args = []
            self.ws()
            if self.s[self.i] != ")":
                while True:
                    args.append(self.val())
                    self.ws()
                    if self.s[self.i] == ",":
                        self.i += 1
                        continue
                    if self.s[self.i] == ")":
                        break
                    raise ValueError("argumentos malformados em %d" % self.i)
            self.i += 1
            fields = self.c.get(name)
            if fields and len(fields) == len(args):
                return dict(zip(fields, args))
            if fields:
                d = dict(zip(fields, args))
                d["_args"] = args
                return d
            return {"_type": name, "_args": args}
        return name

    def string(self):
        self.i += 1
        out = []
        while True:
            ch = self.s[self.i]
            if ch == "\\":
                nxt = self.s[self.i + 1]
                if nxt == "u":
                    out.append(chr(int(self.s[self.i + 2:self.i + 6], 16)))
                    self.i += 6
                    continue
                out.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                self.i += 2
                continue
            if ch == '"':
                self.i += 1
                return "".join(out)
            out.append(ch)
            self.i += 1


def parse_compact(text):
    t = text.strip()
    if t.startswith("{") or t.startswith("["):
        return json.loads(t)
    classes, body = {}, []
    for line in t.split("\n"):
        m = re.match(r"^class (\w+): ?(.*)$", line)
        if m and not body:
            classes[m.group(1)] = [f.strip() for f in m.group(2).split(",") if f.strip()]
        elif line.strip() or body:
            body.append(line)
    return _P("\n".join(body).strip(), classes).val()


def champ_key(name):
    """'Kai'Sa' -> KAISA, 'Miss Fortune' -> MISS_FORTUNE, 'Dr. Mundo' -> DR_MUNDO"""
    n = name.replace("&", " ").replace("'", "").replace(".", "")
    return re.sub(r"\s+", "_", n.strip()).upper()



# =====================================================================
#  OP.GG
# =====================================================================
class OPGG:
    def __init__(self):
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=4)
        self.cache = {}
        self.dirty = False
        self.ok = None
        self.last_error = ""
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                self.cache = json.load(f)
        except Exception:
            self.cache = {}
        self._prune()
        self.prev = {}                   # patch anterior guardado na virada: {"version","since","until","entries"}
        try:
            with open(PREV_FILE, encoding="utf-8") as f:
                self.prev = json.load(f)
        except Exception:
            self.prev = {}
        threading.Thread(target=self._saver, daemon=True).start()

    def _prune(self):
        now = time.time()
        for k in [k for k, v in self.cache.items() if now - v.get("t", 0) > CACHE_KEEP]:
            self.cache.pop(k, None)

    def _saver(self):
        """Grava o cache no disco no máximo a cada 10 s, numa única thread (sem corrida)."""
        while True:
            time.sleep(10)
            self.flush()

    def flush(self):
        if not self.dirty:
            return
        with self.lock:
            self._prune()
            snapshot = json.dumps(self.cache, ensure_ascii=False)
            self.dirty = False
        try:
            tmp = CACHE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(snapshot)
            os.replace(tmp, CACHE_FILE)
        except Exception as e:
            log("Aviso: não consegui gravar o cache:", e)

    def size(self):
        try:
            return os.path.getsize(CACHE_FILE)
        except Exception:
            return 0

    def call(self, tool, args, ttl=CACHE_TTL):
        key = self._key(tool, args)
        args = dict(args, client_app=f"DraftBot/{VERSION}")
        with self.lock:
            hit = self.cache.get(key)
            if hit and time.time() - hit["t"] < ttl:
                return hit["v"]
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": tool, "arguments": args}}).encode()
        req = urllib.request.Request(OPGG_URL, data=body, method="POST", headers={
            "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
            "User-Agent": f"DraftBot/{VERSION}"})
        try:
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    raw = r.read().decode("utf-8")
            except urllib.error.HTTPError as e:
                if e.code not in (403, 406):
                    raise
                req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DraftBot/" + VERSION)
                with urllib.request.urlopen(req, timeout=20) as r:
                    raw = r.read().decode("utf-8")
        except Exception as e:
            self.ok, self.last_error = False, str(e)
            if hit:                      # sem internet: usa o cache antigo
                return hit["v"]
            raise
        if raw.lstrip().startswith("event:") or raw.lstrip().startswith("data:"):
            raw = "\n".join(l[5:].strip() for l in raw.splitlines() if l.startswith("data:"))
        msg = json.loads(raw)
        if "error" in msg:
            raise RuntimeError(msg["error"].get("message", str(msg["error"])))
        res = msg.get("result", {})
        text = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        if res.get("isError"):
            raise RuntimeError(text[:300])
        val = parse_compact(text)
        self.ok, self.last_error = True, ""
        with self.lock:
            self.cache[key] = {"t": time.time(), "v": val, "a": [tool, args]}
            self.dirty = True
        return val

    # ---------- consultas ----------
    def meta(self):
        f = "{champion,tier,rank,win,win_rate,pick_rate,ban_rate,role_rate,play,is_rip}"
        margs = {"position": "all", "lang": LANG, "desired_output_fields":
                 [f"data.positions.{p}[].{f}" for p in ("top", "jungle", "mid", "adc", "support")]}
        mkey = self._key("lol_list_lane_meta_champions", margs)
        with self.lock:
            old_meta = self.cache.get(mkey)      # guardado antes de ser trocado pelo do patch novo
        v = self.call("lol_list_lane_meta_champions", margs)
        pos = (v.get("data") or {}).get("positions") or {}
        out = {p: [x for x in (pos.get(p) or []) if isinstance(x, dict)] for p in ("top", "jungle", "mid", "adc", "support")}
        version = ""
        try:
            t = self.call("lol_get_champion_analysis", {"game_mode": "ranked", "champion": "ANNIE", "position": "mid",
                          "desired_output_fields": ["data.trends.win.{version,rate}"]})
            w = t["data"]["trends"]["win"]
            version = (w[0] if isinstance(w, list) else w).get("version", "")
        except Exception:
            pass
        if version:
            with self.lock:
                pe = self.cache.get("__patch__") or {}
                prev = pe.get("v")
                if prev and prev != version:
                    self._turn_patch(prev, version, pe.get("t", 0), mkey, old_meta)
                self.cache["__patch__"] = {"t": time.time(), "v": version}
                self.dirty = True
        w = self.blend_weight(version)
        if w > 0:
            ov = ((self.prev["entries"].get(mkey) or {}).get("v") or {})
            opos = (ov.get("data") or {}).get("positions") or {}
            out = {p: self._mix_meta(out[p], [x for x in (opos.get(p) or []) if isinstance(x, dict)], w) for p in out}
        return {"version": version, "positions": out, "blend": self.blend_info(version)}

    # ---------- virada de patch ----------
    @staticmethod
    def _key(tool, args):
        args = dict(args, client_app=f"DraftBot/{VERSION}")
        return hashlib.sha1((tool + json.dumps(args, sort_keys=True)).encode()).hexdigest()

    def _turn_patch(self, prev, version, prev_seen, mkey, old_meta):
        """Chamado com o lock. No 1º dia do patch novo há poucas partidas; se o programa estava em uso
        no patch anterior (visto há menos de 24 h), guarda as estatísticas dele para misturar por um dia."""
        now = time.time()
        old = {k: v for k, v in self.cache.items() if v.get("t", 0) < now - 60 and not k.startswith("__")}
        if old_meta:
            old[mkey] = old_meta
        self.cache = {k: v for k, v in self.cache.items() if v.get("t", 0) >= now - 60}
        if now - prev_seen < BLEND_SECS and old:
            self.prev = {"version": prev, "new": version, "since": now, "until": now + BLEND_SECS, "entries": old}
            log(f"Patch novo detectado ({prev} → {version}): até amanhã as estatísticas misturam os dois patches.")
        else:
            self.prev = {}
            log(f"Patch novo detectado ({prev} → {version}): descartando estatísticas antigas.")
        self._save_prev()

    def _save_prev(self):
        try:
            if self.prev:
                tmp = PREV_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.prev, f, ensure_ascii=False)
                os.replace(tmp, PREV_FILE)
            elif os.path.exists(PREV_FILE):
                os.remove(PREV_FILE)
        except Exception as e:
            log("Aviso: não consegui gravar o patch anterior:", e)

    def blend_weight(self, version=None):
        """Peso das partidas do patch anterior: 1 na virada, caindo até 0 em 24 h."""
        p = self.prev
        if not p or not p.get("entries"):
            return 0.0
        version = version or (self.cache.get("__patch__") or {}).get("v")
        if version and p.get("new") and version != p["new"]:
            return 0.0
        left = p.get("until", 0) - time.time()
        if left <= 0:
            with self.lock:
                self.prev = {}
            self._save_prev()
            return 0.0
        return max(0.0, min(1.0, left / BLEND_SECS))

    def blend_info(self, version=None):
        w = self.blend_weight(version)
        if w <= 0:
            return None
        return {"prev": self.prev.get("version", ""), "until": self.prev.get("until", 0), "weight": round(w, 3)}

    @staticmethod
    def _mix_counts(new_play, new_win, old_play, old_win, w):
        play = (new_play or 0) + w * (old_play or 0)
        win = (new_win or 0) + w * (old_win or 0)
        return play, win

    def _mix_meta(self, new, old, w):
        idx = {champ_key(x.get("champion", "")): x for x in old}
        out, seen = [], set()
        for x in new:
            k = champ_key(x.get("champion", ""))
            seen.add(k)
            o = idx.get(k)
            if o:
                x = dict(x)
                x["play"], x["win"] = self._mix_counts(x.get("play"), x.get("win"), o.get("play"), o.get("win"), w)
                if x["play"]:
                    x["win_rate"] = round(x["win"] / x["play"], 4)
            out.append(x)
        for k, o in idx.items():            # campeões que ainda não aparecem no patch novo
            if k not in seen and o.get("play"):
                o = dict(o, play=w * o.get("play", 0), win=w * o.get("win", 0))
                out.append(o)
        return out

    def _mix_rows(self, new, old, w, name="name"):
        idx = {champ_key(r.get(name, "")): r for r in old}
        out, seen = [], set()
        for r in new:
            k = champ_key(r.get(name, ""))
            seen.add(k)
            o = idx.get(k)
            if o:
                r = dict(r)
                r["play"], r["win"] = self._mix_counts(r.get("play"), r.get("win"), o.get("play"), o.get("win"), w)
            out.append(r)
        for k, o in idx.items():
            if k not in seen and o.get("play"):
                out.append(dict(o, play=w * o.get("play", 0), win=w * o.get("win", 0)))
        return out

    def _prev_guide_rows(self, pos, champ):
        """Tabela de confrontos do patch anterior para o campeão (qualquer oponente de referência)."""
        for e in (self.prev.get("entries") or {}).values():
            a = e.get("a") or []
            if len(a) == 2 and a[0] == "lol_get_lane_matchup_guide" and a[1].get("position") == pos \
                    and a[1].get("my_champion") == champ_key(champ):
                d = ((e.get("v") or {}).get("data") or {})
                return [{"name": c.get("champion_name"), "play": c.get("play", 0), "win": c.get("win", 0)}
                        for c in (d.get("counters") or []) if c.get("champion_name")]
        return []

    def common_opp(self, pos, champ):
        """Um adversário comum na rota (só para obter a tabela de confrontos)."""
        try:
            for e in self.meta()["positions"].get(pos, []):
                if champ_key(e.get("champion", "")) != champ_key(champ):
                    return e["champion"]
        except Exception:
            pass
        d = {"top": "Darius", "jungle": "Lee Sin", "mid": "Ahri", "adc": "Jinx", "support": "Thresh"}.get(pos, "Ahri")
        return d if champ_key(d) != champ_key(champ) else "Garen"

    def guide(self, pos, champ, opp):
        return self.call("lol_get_lane_matchup_guide", {"position": pos, "my_champion": champ_key(champ),
                         "opponent_champion": champ_key(opp), "lang": LANG})

    def table(self, pos, champ, opp):
        d = (self.guide(pos, champ, opp) or {}).get("data") or {}
        rows = [{"name": c.get("champion_name"), "play": c.get("play", 0), "win": c.get("win", 0)}
                for c in (d.get("counters") or []) if c.get("champion_name")]
        w = self.blend_weight()
        if w > 0:
            rows = self._mix_rows(rows, self._prev_guide_rows(pos, champ), w)
        return {"champ": champ, "pos": pos, "rows": rows}

    def synergy(self, champ, pos, target):
        sargs = {"champion": champ_key(champ), "my_position": pos, "synergy_position": target, "lang": LANG,
                 "desired_output_fields": ["data.synergies[].{synergy_champion_name,score_rank,score,play,win_rate}"]}
        v = self.call("lol_get_champion_synergies", sargs)
        rows = [r for r in (((v or {}).get("data") or {}).get("synergies") or []) if isinstance(r, dict)]
        w = self.blend_weight()
        if w > 0:
            ov = ((self.prev["entries"].get(self._key("lol_get_champion_synergies", sargs)) or {}).get("v") or {})
            old = [r for r in ((ov.get("data") or {}).get("synergies") or []) if isinstance(r, dict)]
            if old:
                def counted(lst):   # sinergia vem com taxa; converte em vitórias para somar
                    return [dict(r, win=(r.get("win_rate") or 0) * (r.get("play") or 0)) for r in lst]
                rows = self._mix_rows(counted(rows), counted(old), w, name="synergy_champion_name")
                for r in rows:
                    if r.get("play"):
                        r["win_rate"] = round(r["win"] / r["play"], 4)
        return rows

    def general(self, pos, champ):
        fields = ["data.runes.{primary_page_id,primary_rune_ids[],primary_rune_names[],secondary_page_id,secondary_rune_ids[],secondary_rune_names[],stat_mod_ids[],stat_mod_names[],play,win,pick_rate}",
                  "data.core_items.{ids[],ids_names[],play,win,pick_rate}", "data.boots.{ids[],ids_names[],play,win,pick_rate}",
                  "data.starter_items.{ids[],ids_names[],play,win,pick_rate}", "data.summoner_spells.{ids[],ids_names[],play,win,pick_rate}",
                  "data.last_items[].{ids[],ids_names[],play,win,pick_rate}", "data.fourth_items[].{ids[],ids_names[],play,win,pick_rate}",
                  "data.skills.{order[],play,win,pick_rate}", "data.skill_masteries.{ids[],play,win,pick_rate}",
                  "data.summary.average_stats.{win_rate,pick_rate,tier,rank}"]
        v = self.call("lol_get_champion_analysis", {"game_mode": "ranked", "champion": champ_key(champ), "position": pos,
                      "lang": LANG, "desired_output_fields": fields})
        return (v or {}).get("data") or {}

    def build(self, pos, champ, opp):
        """Runas, itens, feitiços e habilidades do patch atual.
        Com oponente: do confronto; se o confronto tiver poucas partidas, completa com a build geral."""
        def L(x):
            return [i for i in (x if isinstance(x, list) else ([x] if x else [])) if isinstance(i, dict)]

        def items(x, n=3):
            return [{"ids": i.get("ids") or [], "names": i.get("ids_names") or [], "play": i.get("play", 0),
                     "win": i.get("win", 0), "pick": i.get("pick_rate", 0)} for i in L(x)[:n]]

        def runes_of(d):
            out = []
            for r in L(d.get("runes"))[:3]:
                out.append({"primary": r.get("primary_page_id"), "secondary": r.get("secondary_page_id"),
                            "ids": (r.get("primary_rune_ids") or []) + (r.get("secondary_rune_ids") or []) + (r.get("stat_mod_ids") or []),
                            "names": (r.get("primary_rune_names") or []) + (r.get("secondary_rune_names") or []),
                            "play": r.get("play", 0), "win": r.get("win", 0), "pick": r.get("pick_rate", 0)})
            return out

        def pack(d):
            sk = L(d.get("skills"))
            ms = L(d.get("skill_masteries"))
            return {"runes": runes_of(d), "starter": items(d.get("starter_items"), 2), "core": items(d.get("core_items"), 3),
                    "boots": items(d.get("boots"), 2), "spells": items(d.get("summoner_spells"), 2),
                    "late": items(d.get("last_items"), 8) or items(d.get("fourth_items"), 6),
                    "order": (sk[0].get("order") if sk else []) or [],
                    "priority": (ms[0].get("ids") if ms else []) or []}

        out = {"champ": champ, "pos": pos, "opp": opp, "vs": None, "tip": "", "advantage": "", "style": "",
               "source": "general", "note": ""}
        if opp:
            d = (self.guide(pos, champ, opp) or {}).get("data") or {}
            for c in d.get("counters") or []:
                if champ_key(c.get("champion_name", "")) == champ_key(opp):
                    out["vs"] = {"play": c.get("play", 0), "win": c.get("win", 0)}
            out.update(tip=d.get("opponent_champion_tip") or "", advantage=d.get("lane_advantage_champion") or "",
                       style=d.get("recommended_play_style") or "")
            b = pack(d)
            core_n = b["core"][0]["play"] if b["core"] else 0
            rune_n = b["runes"][0]["play"] if b["runes"] else 0
            out["source"] = "matchup"
            if core_n < MIN_BUILD_SAMPLE or rune_n < MIN_BUILD_SAMPLE:
                g = pack(self.general(pos, champ))
                for k in ("core", "boots", "starter", "late", "spells", "order", "priority"):
                    if core_n < MIN_BUILD_SAMPLE or not b[k]:
                        b[k] = g[k] or b[k]
                if rune_n < MIN_BUILD_SAMPLE:
                    b["runes"] = g["runes"] or b["runes"]
                out["source"] = "mixed"
                out["note"] = f"Confronto raro (poucas partidas): usei a build geral de {champ} nesta rota."
        else:
            b = pack(self.general(pos, champ))
        core_n = b["core"][0]["play"] if b["core"] else 0
        if core_n and core_n < 50:
            out["note"] = (out["note"] + " " if out["note"] else "") + \
                f"Poucos jogos de {champ} nesta rota: a build tem amostra pequena ({core_n} partidas)."
        out.update(b)
        return out


opgg = OPGG()


# =====================================================================
#  CLIENTE DO LOL (LCU)
# =====================================================================
class LCU:
    SR_QUEUES = {420, 440, 700}   # só ranqueada solo/duo, ranqueada flex e Clash
    LANES = {"TOP": "top", "JUNGLE": "jg", "MIDDLE": "mid", "MID": "mid", "UTILITY": "sup"}

    def __init__(self):
        self.base = None
        self.auth = None
        self.champs = {}          # id -> alias (nome interno)
        self.champ_list = []      # [{id, alias, name}] para a página
        self.items = {}
        self.perks = None
        self._acct, self._acct_t = None, 0
        self._who, self._who_t = None, 0
        self._next_try = 0
        self._cs = {"key": None, "queue": None, "pick": [], "pick_t": 0}
        self.lock = threading.Lock()

    # ---------- conexão ----------
    def _from_process(self):
        try:
            if os.name == "nt":
                cmd = ["powershell", "-NoProfile", "-Command",
                       "Get-CimInstance Win32_Process -Filter \"name='LeagueClientUx.exe'\" | Select-Object -ExpandProperty CommandLine"]
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=8,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            else:
                out = subprocess.run(["ps", "-A", "-o", "args"], capture_output=True, text=True, timeout=5).stdout
                out = "\n".join(l for l in out.splitlines() if "LeagueClientUx" in l)
            port = re.search(r"--app-port=(\d+)", out or "")
            tok = re.search(r"--remoting-auth-token=([\w-]+)", out or "")
            if port and tok:
                return port.group(1), tok.group(1)
        except Exception:
            pass
        return None

    def _from_lockfile(self):
        paths = list(LOCKFILE_GUESSES)
        if os.environ.get("LOL_DIR"):
            paths.insert(0, os.path.join(os.environ["LOL_DIR"], "lockfile"))
        for p in paths + glob.glob(r"?:\*\League of Legends\lockfile"):
            try:
                with open(p, encoding="utf-8") as f:
                    parts = f.read().strip().split(":")
                return parts[2], parts[3]
            except Exception:
                continue
        return None

    def connect(self):
        if time.time() < self._next_try:      # cliente fechado: tenta de novo só a cada 5 s
            return False
        self._next_try = time.time() + 5
        if os.environ.get("DRAFTBOT_LCU"):
            self.base, pw = os.environ["DRAFTBOT_LCU"].rsplit("|", 1)
        else:
            found = self._from_lockfile() or self._from_process()
            if not found:
                return False
            port, pw = found
            self.base = f"https://127.0.0.1:{port}"
        self.auth = "Basic " + base64.b64encode(f"riot:{pw}".encode()).decode()
        try:
            self.req("GET", "/lol-gameflow/v1/gameflow-phase")
        except Exception:
            self.base = None
            return False
        self._load_static()
        self._acct, self._who, self._who_t = None, None, 0
        log("Conectado ao cliente do LoL.")
        return True

    def _load_static(self):
        try:
            data = self.req("GET", "/lol-game-data/assets/v1/champion-summary.json")
            self.champ_list = [{"id": c["id"], "alias": c.get("alias") or "", "name": c.get("name") or ""}
                               for c in data if c.get("id", -1) > 0]
            self.champs = {c["id"]: c["alias"] or c["name"] for c in self.champ_list}
        except Exception as e:
            log("Aviso: não consegui ler a lista de campeões:", e)
        try:
            self.items = {int(i["id"]): i.get("name", "") for i in self.req("GET", "/lol-game-data/assets/v1/items.json")}
        except Exception:
            self.items = {}
        try:
            self.perks = {p["id"] for p in self.req("GET", "/lol-perks/v1/perks")}
        except Exception:
            self.perks = None

    def req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data=data, method=method,
                                   headers={"Authorization": self.auth, "Accept": "application/json",
                                            "Content-Type": "application/json"})
        ctx = _LOCAL_SSL if self.base.startswith("https") else None
        with urllib.request.urlopen(r, context=ctx, timeout=4) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None

    def name(self, cid):
        return self.champs.get(cid, "") if cid else ""

    def champ_id(self, display):
        k = champ_key(display).replace("_", "")
        for c in self.champ_list:
            if k in (champ_key(c["alias"]).replace("_", ""), champ_key(c["name"]).replace("_", "")):
                return c["id"]
        return None

    # ---------- conta logada ----------
    def who(self):
        """Conta logada agora (verificada a cada 3 s); detecta troca de conta."""
        if time.time() - self._who_t < 3:
            return self._who
        self._who_t = time.time()
        try:
            s = self.req("GET", "/lol-summoner/v1/current-summoner") or {}
            new = (s.get("puuid"), f"{s.get('gameName') or s.get('displayName') or ''}#{s.get('tagLine') or ''}") if s.get("puuid") else None
        except Exception:
            new = None
        if new and self._who and new[0] != self._who[0]:
            log(f"Troca de conta detectada: agora {new[1]}.")
            self._acct = None
        self._who = new
        return new

    # ---------- estado da seleção ----------
    def state(self):
        with self.lock:
            if not self.base and not self.connect():
                return {"connected": False, "message": "Cliente do LoL não encontrado. Abra o cliente (já logado) e deixe este programa aberto."}
            try:
                phase = self.req("GET", "/lol-gameflow/v1/gameflow-phase")
            except Exception:
                self.base = None
                return {"connected": False, "message": "Perdi a conexão com o cliente. Tentando de novo…"}
            out = {"connected": True, "phase": phase}
            who = self.who()
            if who:
                out["puuid"], out["summoner"] = who
            if phase != "ChampSelect":
                self._cs = {"key": None, "queue": None, "pick": [], "pick_t": 0}
                return out
            try:
                s = self.req("GET", "/lol-champ-select/v1/session")
            except Exception:
                out["phase"] = "Lobby"
                return out
            out.update(self.parse_session(s))
            # modo de jogo (uma vez por seleção) e campeões liberados (a cada 3 s)
            key = f"{s.get('gameId')}-{s.get('localPlayerCellId')}"
            if self._cs["key"] != key:
                self._cs = {"key": key, "queue": None, "pick": [], "pick_t": 0}
                try:
                    gd = (self.req("GET", "/lol-gameflow/v1/session") or {}).get("gameData") or {}
                    q = gd.get("queue") or {}
                    self._cs["queue"] = {"id": q.get("id"), "mapId": q.get("mapId"), "mode": q.get("gameMode") or "",
                                         "name": q.get("description") or q.get("shortName") or ""}
                except Exception:
                    pass
            if time.time() - self._cs["pick_t"] > 3:
                self._cs["pick_t"] = time.time()
                try:
                    self._cs["pick"] = [self.name(i) for i in (self.req("GET", "/lol-champ-select/v1/pickable-champion-ids") or [])]
                except Exception:
                    pass
            out["queue"] = self._cs["queue"]
            out["pickable"] = [p for p in self._cs["pick"] if p]
            out["sessionKey"] = key
            return out

    def parse_session(self, s):
        me = s.get("localPlayerCellId")
        ally, my_pos, my_hover, my_locked, my_champ = [], "", "", False, ""
        bans, my_turn, sub, locked = set(), "", "", set()
        b = s.get("bans") or {}
        for cid in (b.get("myTeamBans") or []) + (b.get("theirTeamBans") or []):
            bans.add(self.name(cid))
        for group in s.get("actions", []):
            for a in group:
                t = a.get("type")
                if a.get("completed") and t == "ban" and a.get("championId"):
                    bans.add(self.name(a["championId"]))
                if a.get("completed") and t == "pick":
                    locked.add((a.get("actorCellId"), a.get("championId")))
                if a.get("isInProgress"):
                    sub = sub or t
                    if a.get("actorCellId") == me and t in ("pick", "ban"):
                        my_turn = t
        for p in s.get("myTeam", []):
            cid = p.get("championId") or 0
            hover = p.get("championPickIntent") or 0
            is_me = p.get("cellId") == me
            is_locked = (p.get("cellId"), cid) in locked if cid else False
            if is_me:
                my_pos = p.get("assignedPosition") or ""
                my_locked = is_locked
                my_champ = self.name(cid) if is_locked else ""
                if not is_locked and (hover or cid):
                    my_hover = self.name(hover or cid)
            ally.append({"champ": self.name(cid or hover), "position": p.get("assignedPosition") or "",
                         "isMe": is_me, "locked": is_locked})
        enemy = [self.name(p.get("championId")) for p in s.get("theirTeam", []) if p.get("championId")]
        timer = s.get("timer") or {}
        try:
            left = max(0, int(timer.get("adjustedTimeLeftInPhase", 0) / 1000))
        except Exception:
            left = None
        return {"myPosition": my_pos, "ally": ally, "enemy": enemy, "bans": sorted(x for x in bans if x),
                "myTurn": my_turn, "subphase": sub, "myHover": my_hover, "myLocked": my_locked, "myChamp": my_champ,
                "timerLeft": left}

    # ---------- histórico, maestria, elo e campeões da conta ----------
    def account(self, refresh=False):
        with self.lock:
            if not self.base and not self.connect():
                raise RuntimeError("cliente do LoL não encontrado")
        try:
            summ = self.req("GET", "/lol-summoner/v1/current-summoner") or {}
        except Exception:
            raise RuntimeError("faça login no cliente do LoL")
        puuid = summ.get("puuid")
        if not puuid:
            raise RuntimeError("faça login no cliente do LoL")
        if self._acct and self._acct.get("puuid") == puuid and not refresh and time.time() - self._acct_t < 600:
            return self._acct
        out = {"puuid": puuid, "name": summ.get("gameName") or summ.get("displayName") or "", "tag": summ.get("tagLine") or "",
               "rank": "", "mastery": [], "games": [], "owned": None}
        try:
            r = self.req("GET", "/lol-ranked/v1/current-ranked-stats") or {}
            qs = r.get("queues") or list((r.get("queueMap") or {}).values())
            solo = next((q for q in qs if q.get("queueType") == "RANKED_SOLO_5x5"), None)
            if solo and solo.get("tier") and solo.get("tier") not in ("NONE", ""):
                out["rank"] = f"{solo['tier']} {solo.get('division', '')}".strip().replace(" NA", "") + f" · {solo.get('leaguePoints', 0)} PdL"
        except Exception:
            pass
        try:
            m = self.req("GET", "/lol-champion-mastery/v1/local-player/champion-mastery") or []
            if isinstance(m, dict):
                m = m.get("masteries") or m.get("championMasteries") or []
            for x in m:
                n = self.name(x.get("championId"))
                if n:
                    out["mastery"].append({"champ": n, "level": x.get("championLevel", 0),
                                           "points": x.get("championPoints", 0), "last": x.get("lastPlayTime", 0)})
        except Exception as e:
            log("Aviso: não consegui ler a maestria:", e)
        try:
            own = self.req("GET", "/lol-champions/v1/owned-champions-minimal") or []
            out["owned"] = [self.name(c.get("id")) for c in own
                            if (c.get("ownership") or {}).get("owned") or c.get("freeToPlay")
                            or ((c.get("ownership") or {}).get("rental") or {}).get("rented")]
            out["owned"] = [n for n in out["owned"] if n]
        except Exception as e:
            log("Aviso: não consegui ler os campeões da conta:", e)
        seen = set()
        for beg in range(0, 200, 20):
            try:
                r = self.req("GET", f"/lol-match-history/v1/products/lol/current-summoner/matches?begIndex={beg}&endIndex={beg + 19}") or {}
            except Exception as e:
                log("Aviso: não consegui ler o histórico:", e)
                break
            games = (r.get("games") or {}).get("games") or []
            if not games:
                break
            for g in games:
                if g.get("gameId") in seen:
                    continue
                seen.add(g.get("gameId"))
                if g.get("queueId") not in self.SR_QUEUES or g.get("mapId", 11) != 11:
                    continue
                parts = g.get("participants") or []
                pid = None
                for ident in g.get("participantIdentities") or []:
                    if (ident.get("player") or {}).get("puuid") == puuid:
                        pid = ident.get("participantId")
                me = next((p for p in parts if p.get("participantId") == pid), None) or (parts[0] if len(parts) == 1 else None)
                if not me:
                    continue
                st = me.get("stats") or {}
                tl = me.get("timeline") or {}
                lane, role = (tl.get("lane") or "").upper(), (tl.get("role") or "").upper()
                pos = self.LANES.get(lane, "")
                if lane in ("BOTTOM", "BOT"):
                    pos = "sup" if "SUPPORT" in role else "adc" if "CARRY" in role else ""
                out["games"].append({"champ": self.name(me.get("championId")), "pos": pos, "win": bool(st.get("win")),
                                     "k": st.get("kills", 0), "d": st.get("deaths", 0), "a": st.get("assists", 0),
                                     "queue": g.get("queueId"), "ts": g.get("gameCreation", 0)})
            if len(games) < 20:
                break
        out["games"].sort(key=lambda g: g["ts"], reverse=True)
        self._acct, self._acct_t = out, time.time()
        log(f"Conta lida: {out['name']}#{out['tag']} · {len(out['games'])} ranqueadas · "
            f"{len(out['mastery'])} campeões com maestria · {len(out['owned'] or [])} campeões disponíveis.")
        return out

    # ---------- envio de runas e itens ----------
    def apply_runes(self, page):
        with self.lock:
            if not self.base and not self.connect():
                return {"ok": False, "error": "cliente do LoL não encontrado"}
            ids = [int(i) for i in page.get("selectedPerkIds", [])]
            if len(ids) != 9:
                return {"ok": False, "error": f"página incompleta ({len(ids)} runas)"}
            if self.perks:
                bad = [i for i in ids if i not in self.perks]
                if bad:
                    return {"ok": False, "error": f"runas que não existem no seu cliente: {bad}"}
            try:
                for p in self.req("GET", "/lol-perks/v1/pages") or []:
                    if str(p.get("name", "")).startswith("DraftBot") and p.get("isDeletable", True):
                        self.req("DELETE", f"/lol-perks/v1/pages/{p['id']}")
                body = {"name": page.get("name", "DraftBot")[:25], "primaryStyleId": int(page["primaryStyleId"]),
                        "subStyleId": int(page["subStyleId"]), "selectedPerkIds": ids, "current": True}
                try:
                    self.req("POST", "/lol-perks/v1/pages", body)
                except urllib.error.HTTPError:
                    cur = self.req("GET", "/lol-perks/v1/currentpage")
                    if cur and cur.get("isDeletable"):
                        self.req("DELETE", f"/lol-perks/v1/pages/{cur['id']}")
                        self.req("POST", "/lol-perks/v1/pages", body)
                    else:
                        raise
                return {"ok": True}
            except urllib.error.HTTPError as e:
                return {"ok": False, "error": f"o cliente recusou ({e.code}): {e.read().decode(errors='ignore')[:200]}"}
            except Exception as e:
                return {"ok": False, "error": str(e)}

    def apply_itemset(self, data):
        with self.lock:
            if not self.base and not self.connect():
                return {"ok": False, "error": "cliente do LoL não encontrado"}
            try:
                summ = self.req("GET", "/lol-summoner/v1/current-summoner")
                sid = summ.get("summonerId")
                cur = self.req("GET", f"/lol-item-sets/v1/item-sets/{sid}/sets") or {}
                sets = [x for x in (cur.get("itemSets") or []) if not str(x.get("title", "")).startswith("DraftBot")]
                champ_id = self.champ_id(data.get("champ", ""))
                if not champ_id:
                    return {"ok": False, "error": f"não achei o campeão {data.get('champ')} no cliente"}
                blocks = []
                for b in data.get("blocks", []):
                    its = [{"id": str(int(i)), "count": 1} for i in b.get("items", [])
                           if str(i).isdigit() and (not self.items or int(i) in self.items)]
                    if its:
                        blocks.append({"type": b.get("title", "")[:40], "items": its})
                new = {"title": f"DraftBot · {data.get('champ', '')}"[:40], "associatedChampions": [champ_id],
                       "associatedMaps": [11], "blocks": blocks, "map": "any", "mode": "any", "preferredItemSlots": [],
                       "sortrank": 0, "startedFrom": "blank", "type": "custom",
                       "uid": "draftbot-" + hashlib.md5(str(time.time()).encode()).hexdigest()[:12]}
                sets.insert(0, new)
                self.req("PUT", f"/lol-item-sets/v1/item-sets/{sid}/sets",
                         {"accountId": cur.get("accountId", summ.get("accountId")), "itemSets": sets,
                          "timestamp": int(time.time() * 1000)})
                return {"ok": True}
            except urllib.error.HTTPError as e:
                return {"ok": False, "error": f"o cliente recusou ({e.code}): {e.read().decode(errors='ignore')[:200]}"}
            except Exception as e:
                return {"ok": False, "error": str(e)}


lcu = LCU()


# =====================================================================
#  VERSÃO, ATUALIZAÇÃO E DIAGNÓSTICO
# =====================================================================
_update = {"checked": 0, "info": None}


def update_info():
    if not UPDATE_URL:
        return None
    if time.time() - _update["checked"] > 3600:
        _update["checked"] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(UPDATE_URL, headers={"User-Agent": f"DraftBot/{VERSION}"}), timeout=8) as r:
                info = json.loads(r.read().decode("utf-8"))
            def v(s):
                return tuple(int(x) for x in re.findall(r"\d+", str(s)))
            _update["info"] = info if v(info.get("version", "0")) > v(VERSION) else None
            if _update["info"]:
                log(f"Nova versão disponível: {info.get('version')}.")
        except Exception as e:
            log("Aviso: não consegui verificar atualizações:", e)
    return _update["info"]


# ---------- atualização automática ----------
UPD_DIR = os.path.join(DATA_DIR, "atualizacao")
UPD_MAX = 300 * 1024 * 1024


def direct_url(url):
    """Link de compartilhamento → link de download direto (Google Drive e OneDrive)."""
    u = urlparse(url)
    if u.netloc.endswith("drive.google.com") or u.netloc.endswith("docs.google.com"):
        m = re.search(r"/d/([\w-]{10,})", u.path) or re.search(r"[?&]id=([\w-]{10,})", url)
        if m:
            return f"https://drive.usercontent.google.com/download?id={m.group(1)}&export=download&confirm=t"
    if u.netloc.endswith("1drv.ms") or u.netloc.endswith("sharepoint.com") or u.netloc.endswith("onedrive.live.com"):
        if "download=1" not in url:
            return url + ("&" if "?" in url else "?") + "download=1"
    return url


def can_self_update():
    """Só o .exe no Windows, numa pasta onde dá para escrever."""
    if not (FROZEN and os.name == "nt"):
        return False
    try:
        t = os.path.join(APP_DIR, ".draftbot_teste")
        with open(t, "w") as f:
            f.write("ok")
        os.remove(t)
        return os.path.isfile(os.path.join(APP_DIR, "DraftBot.exe"))
    except OSError:
        return False


def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": f"Mozilla/5.0 DraftBot/{VERSION}"})
    h = hashlib.sha256()
    n = 0
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            n += len(chunk)
            if n > UPD_MAX:
                raise RuntimeError("arquivo grande demais")
            h.update(chunk)
            f.write(chunk)
    return h.hexdigest()


def prepare_update(info):
    """Baixa, confere a impressão digital (SHA-256) e extrai a versão nova numa pasta temporária.
    Devolve a pasta que contém o DraftBot.exe novo."""
    import shutil, zipfile
    url, want = (info or {}).get("url", ""), str((info or {}).get("sha256", "")).strip().lower()
    if not url.startswith("https://"):
        raise RuntimeError("o aviso de versão não tem um link de download válido")
    if not re.fullmatch(r"[0-9a-f]{64}", want):
        raise RuntimeError("o aviso de versão não tem a impressão digital (sha256) do arquivo")
    shutil.rmtree(UPD_DIR, ignore_errors=True)
    os.makedirs(UPD_DIR)
    zpath = os.path.join(UPD_DIR, "novo.zip")
    got = _download(direct_url(url), zpath)
    if got != want:
        raise RuntimeError("o arquivo baixado não confere com a versão publicada (impressão digital diferente). "
                           "Confira se o link é público e aponta para o .zip certo.")
    out = os.path.join(UPD_DIR, "novo")
    with zipfile.ZipFile(zpath) as z:
        for m in z.infolist():
            name = m.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/") or ":" in name:
                raise RuntimeError("pacote com caminho inválido")
        z.extractall(out)
    for root, _dirs, files in os.walk(out):
        if "DraftBot.exe" in files:
            return root
    raise RuntimeError("o pacote não tem o DraftBot.exe")


def _backup(src, dst, bak):
    """Guarda uma cópia dos arquivos atuais que a versão nova vai substituir."""
    import shutil
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        for fn in files:
            cur = os.path.join(dst, rel, fn)
            if os.path.isfile(cur):
                os.makedirs(os.path.join(bak, rel), exist_ok=True)
                shutil.copy2(cur, os.path.join(bak, rel, fn))


# Os caminhos vão como argumentos (Unicode), não escritos no .cmd: assim pastas como
# "Área de Trabalho" funcionam, sem depender da página de código do prompt.
UPDATER_CMD = r"""@echo off
setlocal
set "SRC=%~1"
set "DST=%~2"
set "BAK=%~3"
set "STATUS=%~4"
set "PID=%~5"
set "VER=%~6"
set /a N=0
:espera
tasklist /FI "PID eq %PID%" /NH 2>nul | find " %PID% " >nul
if errorlevel 1 goto copia
set /a N+=1
if %N% GEQ 60 goto copia
ping -n 2 127.0.0.1 >nul
goto espera
:copia
robocopy "%SRC%" "%DST%" /E /R:10 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if %ERRORLEVEL% GEQ 8 goto restaura
> "%STATUS%" echo ok %VER%
goto abre
:restaura
robocopy "%BAK%" "%DST%" /E /R:10 /W:1 /NFL /NDL /NJH /NJS /NP >nul
> "%STATUS%" echo falhou %VER%
:abre
start "" "%DST%\DraftBot.exe"
"""


def updater_command(script, *args):
    """Linha de comando para o cmd: com /s, só as aspas de fora são removidas, e cada caminho fica entre aspas."""
    q = lambda x: '"' + str(x).replace('"', "") + '"'
    return 'cmd /d /s /c "' + " ".join(q(x) for x in (script,) + args) + '"'


def install_update_and_exit(new_dir, version):
    """Escreve o script que troca os arquivos depois que este processo terminar, e encerra."""
    bak = os.path.join(UPD_DIR, "anterior")
    _backup(new_dir, APP_DIR, bak)
    script = os.path.join(UPD_DIR, "aplicar.cmd")
    with open(script, "w", encoding="ascii", newline="\r\n") as f:
        f.write(UPDATER_CMD)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(updater_command(script, new_dir, APP_DIR, bak, os.path.join(UPD_DIR, "resultado.txt"),
                                     os.getpid(), version), creationflags=flags, close_fds=True)
    log(f"Instalando a versão {version}. O DraftBot vai reabrir sozinho.")
    try:
        opgg.flush()
    except Exception:
        pass
    if Window.proc is not None and Window.proc.poll() is None:
        try:
            Window.proc.terminate()
        except Exception:
            pass
    os._exit(0)


_updated = {"read": False, "val": None}


def update_result():
    """Na primeira abertura depois de uma atualização: deu certo? (e limpa a pasta temporária)."""
    if not _updated["read"]:
        _updated["read"] = True
        f = os.path.join(UPD_DIR, "resultado.txt")
        try:
            with open(f, encoding="utf-8", errors="replace") as h:
                parts = h.read().split()
            if parts:
                _updated["val"] = {"result": parts[0], "version": parts[1] if len(parts) > 1 else ""}
                log("Atualização:", " ".join(parts))
            import shutil
            shutil.rmtree(UPD_DIR, ignore_errors=True)
        except OSError:
            pass
    return _updated["val"]


def diagnostics():
    lines = [
        f"DraftBot {VERSION}",
        f"Python {platform.python_version()} · {platform.system()} {platform.release()} · {'executável' if FROZEN else 'script'}",
        f"Pasta de dados: {DATA_DIR}",
        f"Cliente do LoL: {'conectado' if lcu.base else 'não conectado'}",
        f"Conta lida: {'sim' if lcu._acct else 'não'}"
        + (f" ({len(lcu._acct.get('games', []))} ranqueadas)" if lcu._acct else ""),
        f"OP.GG: {'ok' if opgg.ok else ('ainda não testado' if opgg.ok is None else 'falhou: ' + opgg.last_error)}",
        f"Cache: {len(opgg.cache)} respostas, {opgg.size() / 1e6:.1f} MB",
        f"Atualização configurada: {'sim' if UPDATE_URL else 'não'}",
        "", "Últimas mensagens:",
    ] + list(LOGS)[-40:]
    return "\n".join(lines)


# =====================================================================
#  SERVIDOR LOCAL
# =====================================================================
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}


class Server(ThreadingHTTPServer):
    """Servidor local. No Windows, a porta é reservada com exclusividade: sem isso, uma segunda
    cópia do DraftBot conseguiria abrir a mesma porta em vez de detectar a que já está aberta."""
    daemon_threads = True
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _guard(self, fn):
        try:
            return self._send(200, {"ok": True, "data": fn()})
        except Exception as e:
            return self._send(200, {"ok": False, "error": str(e)[:300]})

    def _host_ok(self):
        # protege contra sites que tentem falar com o programa (DNS rebinding)
        return (self.headers.get("Host") or "") in ALLOWED_HOSTS

    def do_OPTIONS(self):
        self._send(403, {"error": "não permitido"})

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "não permitido"})
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in ("/", "/index.html"):
            with open(PAGE, "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if u.path == "/favicon.ico":
            try:
                with open(ICON, "rb") as f:
                    return self._send(200, f.read(), "image/x-icon")
            except OSError:
                return self._send(404, {"error": "sem ícone"})
        if u.path == "/api/state":
            Window.seen = time.time()
            st = lcu.state()
            st["opgg"] = opgg.ok
            return self._send(200, st)
        if u.path == "/api/meta":
            return self._guard(opgg.meta)
        if u.path == "/api/table":
            return self._guard(lambda: opgg.table(q["pos"], q["champ"], q.get("opp") or opgg.common_opp(q["pos"], q["champ"])))
        if u.path == "/api/synergy":
            return self._guard(lambda: opgg.synergy(q["champ"], q["pos"], q["target"]))
        if u.path == "/api/build":
            return self._guard(lambda: opgg.build(q["pos"], q["champ"], q.get("opp") or ""))
        if u.path == "/api/account":
            return self._guard(lambda: lcu.account(refresh=q.get("refresh") == "1"))
        if u.path == "/api/items":
            return self._send(200, {"ok": True, "data": {str(k): v for k, v in lcu.items.items()}})
        if u.path == "/api/champs":
            return self._send(200, {"ok": True, "data": lcu.champ_list})
        if u.path == "/api/version":
            return self._send(200, {"ok": True, "app": "DraftBot", "version": VERSION, "update": update_info(),
                                    "autoUpdate": can_self_update(), "updated": update_result()})
        if u.path == "/api/diag":
            return self._send(200, {"ok": True, "data": diagnostics()})
        self._send(404, {"error": "não encontrado"})

    def do_POST(self):
        # só a própria página pode pedir alterações: exige o cabeçalho X-DraftBot,
        # que um site externo não consegue enviar sem a permissão do programa
        if not self._host_ok() or self.headers.get("X-DraftBot") != "1":
            return self._send(403, {"ok": False, "error": "não permitido"})
        n = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, {"ok": False, "error": "pedido inválido"})
        if self.path == "/api/runes":
            res = lcu.apply_runes(body)
            log("Runas:", body.get("name"), "→", "ok" if res["ok"] else res["error"])
            return self._send(200, res)
        if self.path == "/api/itemset":
            res = lcu.apply_itemset(body)
            log("Itens:", body.get("champ"), "→", "ok" if res["ok"] else res["error"])
            return self._send(200, res)
        if self.path == "/api/update":
            info = update_info()
            if not info:
                return self._send(200, {"ok": False, "error": "não há versão nova"})
            if not can_self_update():
                return self._send(200, {"ok": False, "error": "atualização automática indisponível nesta instalação"})
            try:
                new_dir = prepare_update(info)
            except Exception as e:
                log("Atualização falhou:", e)
                return self._send(200, {"ok": False, "error": str(e)})
            self._send(200, {"ok": True, "version": info.get("version")})
            threading.Timer(1.5, install_update_and_exit, args=(new_dir, info.get("version", ""))).start()
            return
        self._send(404, {"error": "não encontrado"})


class Window:
    """Abre o DraftBot numa janela própria (modo aplicativo do Edge/Chrome/Brave), sem abas nem barra
    de endereço, e encerra o programa quando essa janela é fechada."""
    seen = 0.0          # último pedido da página (/api/state a cada 1s)
    proc = None

    @staticmethod
    def find():
        env = os.environ.get
        roots = [env("ProgramFiles(x86)"), env("ProgramFiles"), env("LOCALAPPDATA")]
        rels = [r"Microsoft\Edge\Application\msedge.exe",
                r"Google\Chrome\Application\chrome.exe",
                r"BraveSoftware\Brave-Browser\Application\brave.exe"]
        for rel in rels:
            for root in roots:
                if root and os.path.isfile(os.path.join(root, rel)):
                    return os.path.join(root, rel)
        return None

    @classmethod
    def open(cls, url):
        exe = cls.find() if os.name == "nt" and "--navegador" not in sys.argv else None
        if not exe:
            webbrowser.open(url)
            return False
        profile = os.path.join(DATA_DIR, "janela")
        os.makedirs(profile, exist_ok=True)
        args = [exe, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1440,900",
                "--no-first-run", "--no-default-browser-check", "--disable-sync",
                "--disable-features=Translate,msEdgeSidebarV2,msUndersideButton",
                # a página precisa continuar atualizando mesmo minimizada (seleção de campeões)
                "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows"]
        try:
            cls.proc = subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return True
        except OSError as e:
            log("Não consegui abrir a janela própria; usando o navegador:", e)
            webbrowser.open(url)
            return False

    @classmethod
    def watch(cls, srv, app_mode, tick=2.0, grace=30.0):
        """Sai quando a janela foi fechada: o processo dela terminou e a página parou de pedir dados.
        No navegador comum (sem janela própria) espera mais, porque abas em segundo plano ficam lentas."""
        limit = (12 if app_mode else 180) * tick / 2
        start = time.time()
        while True:
            time.sleep(tick)
            alive = cls.proc is not None and cls.proc.poll() is None
            last = max(cls.seen, start)
            if not alive and time.time() - last > limit and time.time() - start > grace:
                log("Janela fechada. Encerrando o DraftBot.")
                srv.shutdown()
                return


def alert(msg):
    """Mostra uma mensagem ao usuário mesmo sem a janela preta (console) aberta."""
    log(msg)
    if os.name == "nt" and FROZEN:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, "DraftBot", 0x40)
        except Exception:
            pass


def already_running():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/version", timeout=2) as r:
            return json.loads(r.read().decode()).get("app") == "DraftBot"
    except Exception:
        return False


def selftest():
    """Usado pelo GitHub para conferir se o .exe gerado funciona: sobe o servidor, consulta e sai."""
    srv = Server(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{PORT}"
    def get(path):
        req = urllib.request.Request(base + path, headers={"Host": f"127.0.0.1:{PORT}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.read().decode("utf-8")
    v = json.loads(get("/api/version"))
    assert v.get("app") == "DraftBot" and v.get("version") == VERSION, v
    assert "DRAFT<b>BOT</b>" in get("/"), "página não encontrada"
    assert parse_compact('class X: a,b\n\nX("ok",[1,2])') == {"a": "ok", "b": [1, 2]}
    assert "DraftBot" in json.loads(get("/api/diag"))["data"]
    with urllib.request.urlopen(base + "/favicon.ico", timeout=5) as r:
        assert r.status == 200 and r.read(4) == b"\x00\x00\x01\x00", "ícone não encontrado"
    srv.shutdown()
    msg = f"SELFTEST OK · DraftBot {VERSION} · {'executável' if FROZEN else 'script'}"
    with open(os.path.join(DATA_DIR, "selftest.txt"), "w", encoding="utf-8") as f:
        f.write(msg)
    try:
        print(msg, flush=True)
    except Exception:
        pass


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    if "--version" in sys.argv:
        try:
            print(VERSION)
        except Exception:
            pass
        return
    if "--selftest" in sys.argv:
        selftest()
        return
    url = f"http://127.0.0.1:{PORT}"
    show = "--no-browser" not in sys.argv
    try:
        srv = Server(("127.0.0.1", PORT), Handler)
    except OSError:
        if already_running():
            log("O DraftBot já está aberto. Abrindo a janela dele.")
            if show:
                Window.open(url)
            return
        alert(f"A porta {PORT} está ocupada por outro programa. Feche-o e abra o DraftBot de novo.")
        return
    log(f"DraftBot {VERSION} rodando em {url}.")

    def warm():
        try:
            m = opgg.meta()
            log(f"Estatísticas da OP.GG carregadas (patch {m.get('version') or '?'}).")
        except Exception as e:
            log("Aviso: não consegui buscar estatísticas da OP.GG agora:", e)
        update_info()
    threading.Thread(target=warm, daemon=True).start()
    if show:
        app_mode = Window.open(url)
        threading.Thread(target=Window.watch, args=(srv, app_mode), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        opgg.flush()


if __name__ == "__main__":
    main()

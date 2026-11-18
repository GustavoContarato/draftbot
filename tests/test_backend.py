"""Testes do programa local (draftbot.py) com o cliente do LoL e a OP.GG simulados.

Rodar:  python -m unittest discover -s tests -v
"""
import importlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tests.mocks.fake_lcu import FakeLCU      # noqa: E402
from tests.mocks.fake_opgg import FakeOPGG    # noqa: E402


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


LCU = OPGG = DB = SRV = None
TMP = tempfile.mkdtemp(prefix="draftbot-test-")


def setUpModule():
    global LCU, OPGG, DB, SRV
    LCU, OPGG = FakeLCU().start(), FakeOPGG().start()
    os.environ.update(DRAFTBOT_LCU=f"http://127.0.0.1:{LCU.port}|senha", DRAFTBOT_OPGG=OPGG.url,
                      DRAFTBOT_PORT=str(free_port()), DRAFTBOT_DATA=TMP)
    DB = importlib.import_module("draftbot")
    SRV = DB.Server(("127.0.0.1", DB.PORT), DB.Handler)
    threading.Thread(target=SRV.serve_forever, daemon=True).start()


def tearDownModule():
    SRV.shutdown()
    LCU.stop()
    OPGG.stop()


def api(path, method="GET", body=None, headers=None):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(f"http://127.0.0.1:{DB.PORT}{path}", method=method, headers=h,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def post(path, body):
    return api(path, "POST", body, {"X-DraftBot": "1"})


class Parser(unittest.TestCase):
    REAL_ANALYSIS = '''class LolGetChampionAnalysis: data
class Data: summary,damage_type,strong_counters,weak_counters,core_items,boots,starter_items,fourth_items,summoner_spells,runes
class Summary: average_stats
class AverageStats: win_rate,pick_rate,tier,rank
class StrongCounter: champion_name,play,my_win_rate
class WeakCounter: champion_name,play,my_win_rate,counter_win_rate
class CoreItems: ids,ids_names,pick_rate
class Boots: ids,ids_names
class Runes: primary_page_id,primary_rune_ids,primary_rune_names,secondary_page_id,secondary_rune_ids,secondary_rune_names,stat_mod_ids,stat_mod_names,win,pick_rate

LolGetChampionAnalysis(Data(Summary(AverageStats(0.51,0.11,1,8)),"AD",[StrongCounter("Kai'Sa",25015,0.53)],[WeakCounter("Vel'Koz",704,0.4,0.6)],CoreItems([2523,3085,3031],["Hexoptics C44","Runaan's Hurricane","Infinity Edge"],0.4),Boots([3006],["Berserker's Greaves"]),Boots([1086,2003,2003],["Doran's Bow","Health Potion","Health Potion"]),[CoreItems([3036],["Lord Dominik's Regards"],0.47)],Boots([4,21],[4,21]),Runes(8000,[8008,8009,9103,8017],["Lethal Tempo","Presence of Mind","Legend: Bloodline","Cut Down"],8300,[8313,8321],["Triple Tonic","Cash Back"],[5005,5008,5011],[5005,5008,5011],45395,0.36)))'''

    def test_formato_compacto_real(self):
        d = DB.parse_compact(self.REAL_ANALYSIS)["data"]
        self.assertEqual(d["summary"]["average_stats"]["tier"], 1)
        self.assertEqual(d["weak_counters"][0]["champion_name"], "Vel'Koz")
        self.assertEqual(d["starter_items"]["ids"], [1086, 2003, 2003])
        self.assertEqual(d["runes"]["primary_rune_ids"], [8008, 8009, 9103, 8017])
        self.assertEqual(d["fourth_items"][0]["ids_names"], ["Lord Dominik's Regards"])

    def test_textos_numeros_e_nulos(self):
        v = DB.parse_compact('class X: a,b,c,d\n\nX("a\\"b \\u00e9",-1.5e-3,[],null)')
        self.assertEqual(v, {"a": 'a"b é', "b": -0.0015, "c": [], "d": None})

    def test_nomes_para_a_api(self):
        self.assertEqual([DB.champ_key(n) for n in ["Kai'Sa", "Miss Fortune", "Dr. Mundo", "Nunu & Willump", "Jarvan IV"]],
                         ["KAISA", "MISS_FORTUNE", "DR_MUNDO", "NUNU_WILLUMP", "JARVAN_IV"])


class Cliente(unittest.TestCase):
    def setUp(self):
        LCU.account, LCU.locked, LCU.map_id, LCU.phase = "A", False, 11, "ChampSelect"
        DB.lcu._who_t = 0
        DB.lcu._cs["pick_t"] = 0

    def test_estado_da_selecao(self):
        st, d = api("/api/state")
        self.assertEqual(st, 200)
        self.assertEqual(d["phase"], "ChampSelect")
        self.assertEqual(d["summoner"], "Contarato#BR1")
        self.assertEqual(d["myPosition"], "middle")
        self.assertEqual(d["myHover"], "Syndra")
        self.assertFalse(d["myLocked"])
        self.assertEqual(d["queue"]["mapId"], 11)
        self.assertIn("Jinx", d["pickable"])
        self.assertEqual(sorted(d["bans"]), ["Ahri", "MonkeyKing"])
        self.assertEqual(len(d["enemy"]), 5)

    def test_travar_e_modo_de_jogo(self):
        LCU.locked, LCU.map_id, LCU.game_id = True, 12, 778
        _, d = api("/api/state")
        self.assertTrue(d["myLocked"])
        self.assertEqual(d["myChamp"], "Syndra")
        self.assertEqual(d["queue"]["mapId"], 12)
        LCU.game_id = 777

    def test_conta_so_ranqueadas(self):
        _, r = api("/api/account?refresh=1")
        a = r["data"]
        self.assertEqual(a["name"], "Contarato")
        self.assertEqual(len(a["games"]), 30 + 18 + 6 + 10)          # normal alternada, rápida e ARAM ficam de fora
        self.assertEqual({g["queue"] for g in a["games"]}, {420, 440})
        self.assertEqual({g["pos"] for g in a["games"] if g["champ"] == "Jinx"}, {"adc"})
        self.assertNotIn("Twitch", a["owned"])
        self.assertIn("Zyrael", a["owned"])
        self.assertTrue(a["rank"].startswith("GOLD II"))

    def test_troca_de_conta(self):
        api("/api/account?refresh=1")
        LCU.account = "B"
        DB.lcu._who_t = 0
        _, s = api("/api/state")
        self.assertEqual(s["summoner"], "Amigo#2077")
        _, r = api("/api/account")
        self.assertEqual(r["data"]["name"], "Amigo")
        self.assertEqual({g["champ"] for g in r["data"]["games"]}, {"Thresh", "Leona"})

    def test_deslogado(self):
        LCU.account = None
        DB.lcu._who_t = 0
        _, s = api("/api/state")
        self.assertNotIn("puuid", s)
        _, r = api("/api/account?refresh=1")
        self.assertFalse(r["ok"])
        self.assertIn("login", r["error"])

    def test_lista_de_campeoes_inclui_novos(self):
        _, r = api("/api/champs")
        self.assertIn({"id": 999, "alias": "Zyrael", "name": "Zyrael"}, r["data"])
        self.assertNotIn(-1, [c["id"] for c in r["data"]])


class Envio(unittest.TestCase):
    def test_runas_validas(self):
        n = len(LCU.posts)
        st, r = post("/api/runes", {"name": "DraftBot · Jinx", "primaryStyleId": 8000, "subStyleId": 8300,
                                     "selectedPerkIds": [8008, 8009, 9103, 8017, 8313, 8321, 5005, 5008, 5011]})
        self.assertTrue(r["ok"], r)
        path, body = LCU.posts[-1]
        self.assertEqual(path, "/lol-perks/v1/pages")
        self.assertTrue(body["current"])
        self.assertIn("/lol-perks/v1/pages/7", LCU.deletes)        # só a página antiga do DraftBot é apagada
        self.assertNotIn("/lol-perks/v1/pages/8", LCU.deletes)
        self.assertEqual(len(LCU.posts), n + 1)

    def test_runas_inexistentes_sao_recusadas(self):
        n = len(LCU.posts)
        _, r = post("/api/runes", {"name": "x", "primaryStyleId": 8000, "subStyleId": 8300,
                                    "selectedPerkIds": [8008, 8009, 9103, 8017, 8313, 8321, 5005, 5008, 99999]})
        self.assertFalse(r["ok"])
        self.assertEqual(len(LCU.posts), n)

    def test_conjunto_de_itens(self):
        _, r = post("/api/itemset", {"champ": "Wukong", "blocks": [{"title": "Núcleo", "items": [3031, 99999, 3036]}]})
        self.assertTrue(r["ok"], r)
        _, body = LCU.puts[-1]
        titles = [s["title"] for s in body["itemSets"]]
        self.assertIn("Meu set", titles)                           # os conjuntos do jogador ficam
        self.assertNotIn("DraftBot · Antigo", titles)               # o antigo do DraftBot sai
        new = body["itemSets"][0]
        self.assertEqual(new["associatedChampions"], [62])          # Wukong = MonkeyKing
        self.assertEqual([i["id"] for i in new["blocks"][0]["items"]], ["3031", "3036"])   # 99999 não existe


class Seguranca(unittest.TestCase):
    def test_host_estranho(self):
        st, _ = api("/api/account", headers={"Host": "evil.com:8765"})
        self.assertEqual(st, 403)

    def test_post_sem_cabecalho(self):
        st, _ = api("/api/itemset", "POST", {"champ": "Jinx", "blocks": []})
        self.assertEqual(st, 403)

    def test_options(self):
        st, _ = api("/api/runes", "OPTIONS")
        self.assertEqual(st, 403)


class Estatisticas(unittest.TestCase):
    def test_meta_e_versao(self):
        _, r = api("/api/meta")
        self.assertEqual(r["data"]["version"], "16.22")
        self.assertEqual(r["data"]["positions"]["adc"][0]["champion"], "Xayah")
        self.assertIn("win", r["data"]["positions"]["adc"][0])

    def test_build_do_confronto(self):
        _, r = api("/api/build?pos=adc&champ=Jinx&opp=Draven")
        b = r["data"]
        self.assertEqual(b["source"], "matchup")
        self.assertEqual(len(b["runes"][0]["ids"]), 9)
        self.assertEqual(len(b["order"]), 18)
        self.assertEqual(b["note"], "")

    def test_confronto_raro_usa_build_geral(self):
        _, r = api("/api/build?pos=mid&champ=Syndra&opp=Malzahar")
        b = r["data"]
        self.assertEqual(b["source"], "mixed")
        self.assertIn("Confronto raro", b["note"])
        self.assertGreaterEqual(b["core"][0]["play"], 150)
        self.assertEqual(b["runes"][0]["primary"], 8100)

    def test_falha_temporaria_e_recuperacao(self):
        OPGG.fail = 1   # a OP.GG falha uma vez
        _, r = api("/api/table?pos=top&champ=Fiora&opp=Darius")
        self.assertFalse(r["ok"])
        _, r = api("/api/table?pos=top&champ=Fiora&opp=Darius")
        self.assertTrue(r["ok"], r)
        self.assertEqual(len(r["data"]["rows"]), 8)

    def test_patch_novo_descarta_dados_antigos(self):
        api("/api/table?pos=jungle&champ=Vi&opp=Lee%20Sin")
        DB.opgg.meta()
        with DB.opgg.lock:
            for v in DB.opgg.cache.values():       # "envelhece" o cache para forçar nova consulta
                v["t"] -= DB.CACHE_TTL + 1
        OPGG.version = "16.23"
        try:
            self.assertEqual(DB.opgg.meta()["version"], "16.23")
            with DB.opgg.lock:
                tools = [v for k, v in DB.opgg.cache.items() if k != "__patch__"]
            self.assertTrue(all(time.time() - v["t"] < 60 for v in tools))   # só sobrou o que veio do patch novo
            self.assertEqual(DB.opgg.cache["__patch__"]["v"], "16.23")
        finally:
            OPGG.version = "16.22"

    def test_cache_gravado_e_limpo(self):
        api("/api/synergy?champ=Jinx&pos=adc&target=support")
        with DB.opgg.lock:
            DB.opgg.cache["velho"] = {"t": time.time() - DB.CACHE_KEEP - 10, "v": 1}
            DB.opgg.dirty = True
        DB.opgg.flush()
        with open(DB.CACHE_FILE, encoding="utf-8") as f:
            disk = json.load(f)
        self.assertNotIn("velho", disk)
        self.assertGreater(len(disk), 0)
        self.assertFalse(os.path.exists(DB.CACHE_FILE + ".tmp"))


class AvisoDeVersao(unittest.TestCase):
    def test_avisa_quando_ha_versao_nova(self):
        from http.server import BaseHTTPRequestHandler
        info = {"version": "9.9.9", "url": "https://exemplo/DraftBot.zip", "notes": "novidades"}

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                b = json.dumps(info).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
        gist = DB.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=gist.serve_forever, daemon=True).start()
        old = DB.UPDATE_URL
        try:
            DB.UPDATE_URL = f"http://127.0.0.1:{gist.server_address[1]}/version.json"
            DB._update.update(checked=0, info=None)
            _, r = api("/api/version")
            self.assertEqual(r["update"]["version"], "9.9.9")
            info["version"] = DB.VERSION                  # mesma versão: sem aviso
            DB._update.update(checked=0, info=None)
            _, r = api("/api/version")
            self.assertIsNone(r["update"])
        finally:
            DB.UPDATE_URL = old
            gist.shutdown()

    def test_endereco_embutido_no_exe(self):
        path = os.path.join(DB.HERE, "update_url.txt")
        with open(path, "w", encoding="utf-8-sig") as f:   # com BOM, como o PowerShell pode gravar
            f.write("https://gist.githubusercontent.com/x/y/raw/version.json")
        try:
            self.assertEqual(DB._builtin_update_url(), "https://gist.githubusercontent.com/x/y/raw/version.json")
        finally:
            os.remove(path)


class Processo(unittest.TestCase):
    def run_app(self, *args, port=None, timeout=20):
        env = dict(os.environ, DRAFTBOT_PORT=str(port or free_port()), DRAFTBOT_DATA=TMP)
        return subprocess.run([sys.executable, os.path.join(ROOT, "draftbot.py"), *args], env=env,
                              capture_output=True, text=True, timeout=timeout)

    def test_selftest(self):
        r = self.run_app("--selftest")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SELFTEST OK", r.stdout)

    def test_versao(self):
        self.assertEqual(self.run_app("--version").stdout.strip(), DB.VERSION)

    def test_segunda_janela(self):
        r = self.run_app("--no-browser", port=DB.PORT)
        self.assertIn("já está aberto", r.stdout)

    def test_cliente_fechado_nao_procura_toda_hora(self):
        L = DB.LCU()
        calls = []
        L._from_lockfile = lambda: calls.append(1)
        L._from_process = lambda: None
        old = os.environ.pop("DRAFTBOT_LCU")
        try:
            for _ in range(10):
                L.state()
        finally:
            os.environ["DRAFTBOT_LCU"] = old
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

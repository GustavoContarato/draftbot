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
            with DB.opgg.lock:
                DB.opgg.cache, DB.opgg.prev = {}, {}
            DB.opgg._save_prev()

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


class PatchNovo(unittest.TestCase):
    """No 1º dia do patch novo, as estatísticas misturam o patch anterior com peso caindo até 0 em 24 h."""

    def setUp(self):
        self.reset()

    def tearDown(self):
        self.reset()

    def reset(self):
        OPGG.version, OPGG.scale, OPGG.shift = "16.22", 1.0, 0.0
        with DB.opgg.lock:
            DB.opgg.cache = {}
            DB.opgg.prev = {}
        DB.opgg._save_prev()

    def virar_patch(self, visto_ha=None):
        """Usa o patch 16.22, envelhece o cache e publica o 16.23 com 1% das partidas."""
        _, m = api("/api/meta")
        _, t = api("/api/table?pos=jungle&champ=Vi&opp=Lee%20Sin")
        _, y = api("/api/synergy?champ=Jinx&pos=adc&target=support")
        with DB.opgg.lock:
            for v in DB.opgg.cache.values():
                v["t"] -= (visto_ha or DB.CACHE_TTL + 1)
        OPGG.version, OPGG.scale, OPGG.shift = "16.23", 0.01, 0.05
        return m["data"], t["data"], y["data"]

    @staticmethod
    def row(lst, name, key="champion"):
        return next(x for x in lst if x[key] == name)

    def test_mistura_no_primeiro_dia(self):
        m0, t0, y0 = self.virar_patch()
        _, r = api("/api/meta")
        m = r["data"]
        self.assertEqual(m["version"], "16.23")
        self.assertEqual(m["blend"]["prev"], "16.22")
        self.assertGreater(m["blend"]["weight"], 0.99)
        old, new = self.row(m0["positions"]["adc"], "Xayah"), self.row(m["positions"]["adc"], "Xayah")
        self.assertGreater(new["play"], old["play"])                      # somou as partidas dos dois patches
        self.assertGreater(new["win_rate"], old["win_rate"])             # e puxou um pouco para o patch novo
        self.assertLess(new["win_rate"], old["win_rate"] + 0.01)         # mas o anterior ainda pesa mais
        _, r = api("/api/table?pos=jungle&champ=Vi&opp=Lee%20Sin")
        a, b = self.row(t0["rows"], "Graves", "name"), self.row(r["data"]["rows"], "Graves", "name")
        self.assertGreater(b["play"], a["play"])
        _, r = api("/api/synergy?champ=Jinx&pos=adc&target=support")
        a, b = self.row(y0, "Thresh", "synergy_champion_name"), self.row(r["data"], "Thresh", "synergy_champion_name")
        self.assertGreater(b["play"], a["play"])
        self.assertTrue(os.path.exists(DB.PREV_FILE))

    def test_peso_cai_ao_longo_do_dia(self):
        self.virar_patch()
        DB.opgg.meta()
        DB.opgg.prev["until"] = time.time() + DB.BLEND_SECS / 2
        self.assertAlmostEqual(DB.opgg.blend_weight(), 0.5, places=2)

    def test_depois_do_primeiro_dia_so_o_patch_novo(self):
        self.virar_patch()
        DB.opgg.meta()
        DB.opgg.prev["until"] = time.time() - 1
        _, r = api("/api/meta")
        self.assertIsNone(r["data"]["blend"])
        self.assertEqual(self.row(r["data"]["positions"]["adc"], "Xayah")["play"], 2000)   # só o 1% do patch novo
        self.assertFalse(os.path.exists(DB.PREV_FILE))

    def test_sem_mistura_se_o_patch_anterior_e_velho(self):
        self.virar_patch(visto_ha=25 * 3600)       # programa ficou fechado mais de um dia
        _, r = api("/api/meta")
        self.assertIsNone(r["data"]["blend"])
        self.assertEqual(self.row(r["data"]["positions"]["adc"], "Xayah")["play"], 2000)


class Atualizacao(unittest.TestCase):
    """Atualização automática: link direto, conferência do arquivo e troca dos arquivos."""

    def setUp(self):
        import zipfile
        self.dir = tempfile.mkdtemp(prefix="draftbot-upd-")
        self.zip = os.path.join(self.dir, "pacote.zip")
        with zipfile.ZipFile(self.zip, "w") as z:
            z.writestr("DraftBot/DraftBot.exe", b"novo-exe")
            z.writestr("DraftBot/index.html", "nova pagina")
            z.writestr("DraftBot/lib/x.dll", b"dll")
        import hashlib
        with open(self.zip, "rb") as f:
            self.sha = hashlib.sha256(f.read()).hexdigest()
        self.old_dl = DB._download

        def fake_download(url, dest):
            self.url = url
            import shutil
            shutil.copy(self.zip, dest)
            return hashlib.sha256(open(dest, "rb").read()).hexdigest()
        DB._download = fake_download

    def tearDown(self):
        DB._download = self.old_dl

    def test_link_direto(self):
        g = DB.direct_url("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing")
        self.assertEqual(g, "https://drive.usercontent.google.com/download?id=1AbCdEfGhIjKlMnOp&export=download&confirm=t")
        self.assertEqual(DB.direct_url("https://drive.google.com/open?id=1AbCdEfGhIjKlMnOp"), g)
        self.assertTrue(DB.direct_url("https://1drv.ms/u/s!abc?e=x").endswith("&download=1"))
        self.assertEqual(DB.direct_url("https://exemplo.com/a.zip"), "https://exemplo.com/a.zip")

    def test_baixa_confere_e_extrai(self):
        d = DB.prepare_update({"version": "9.9.9", "url": "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view",
                               "sha256": self.sha.upper()})
        self.assertTrue(self.url.startswith("https://drive.usercontent.google.com/"))
        self.assertEqual(open(os.path.join(d, "DraftBot.exe"), "rb").read(), b"novo-exe")

    def test_recusa_arquivo_diferente_ou_sem_conferencia(self):
        with self.assertRaisesRegex(RuntimeError, "não confere"):
            DB.prepare_update({"url": "https://x.com/a.zip", "sha256": "0" * 64})
        with self.assertRaisesRegex(RuntimeError, "sha256"):
            DB.prepare_update({"url": "https://x.com/a.zip"})
        with self.assertRaisesRegex(RuntimeError, "link"):
            DB.prepare_update({"url": "http://x.com/a.zip", "sha256": self.sha})

    def test_recusa_pacote_com_caminho_perigoso(self):
        import zipfile, hashlib
        with zipfile.ZipFile(self.zip, "w") as z:
            z.writestr("../fora.txt", "x")
        self.sha = hashlib.sha256(open(self.zip, "rb").read()).hexdigest()
        with self.assertRaisesRegex(RuntimeError, "caminho"):
            DB.prepare_update({"url": "https://x.com/a.zip", "sha256": self.sha})

    def test_copia_de_seguranca_so_do_que_muda(self):
        src, dst, bak = (os.path.join(self.dir, n) for n in ("src", "dst", "bak"))
        os.makedirs(os.path.join(src, "lib")); os.makedirs(dst)
        for p, t in (("DraftBot.exe", "novo"), ("lib/x.dll", "novo")):
            open(os.path.join(src, p), "w").write(t)
        open(os.path.join(dst, "DraftBot.exe"), "w").write("velho")
        open(os.path.join(dst, "config.json"), "w").write("{}")
        DB._backup(src, dst, bak)
        self.assertEqual(open(os.path.join(bak, "DraftBot.exe")).read(), "velho")
        self.assertFalse(os.path.exists(os.path.join(bak, "config.json")))
        self.assertFalse(os.path.exists(os.path.join(bak, "lib", "x.dll")))

    def test_sem_versao_nova_nao_atualiza(self):
        st, r = api("/api/update", "POST", {}, {"X-DraftBot": "1"})
        self.assertFalse(r["ok"])
        st, r = api("/api/update", "POST", {})
        self.assertEqual(st, 403)

    @unittest.skipUnless(os.name == "nt", "o instalador é um .cmd do Windows")
    def test_instalador_troca_os_arquivos(self):
        import shutil
        base = os.path.join(self.dir, "Área de Trabalho", "Draft Bot")
        src, dst, bak = os.path.join(self.dir, "novo"), base, os.path.join(self.dir, "anterior")
        os.makedirs(os.path.join(src, "lib")); os.makedirs(dst)
        hostname = shutil.which("hostname") or r"C:\Windows\System32\hostname.exe"
        shutil.copy(hostname, os.path.join(src, "DraftBot.exe"))       # "abre" e sai na hora
        open(os.path.join(src, "lib", "x.dll"), "w").write("novo")
        open(os.path.join(dst, "config.json"), "w").write("{}")
        status = os.path.join(self.dir, "resultado.txt")
        script = os.path.join(self.dir, "aplicar.cmd")
        with open(script, "w", encoding="ascii", newline="\r\n") as f:
            f.write(DB.UPDATER_CMD)
        espera = subprocess.Popen(["ping", "-n", "5", "127.0.0.1"], stdout=subprocess.DEVNULL)   # ~4 s
        t0 = time.time()
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS          # como o DraftBot lança
        p = subprocess.Popen(DB.updater_command(script, src, dst, bak, status, espera.pid, "9.9.9"),
                             creationflags=flags, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        p.wait(timeout=90)
        self.assertGreater(time.time() - t0, 3.0)                        # esperou o programa antigo fechar
        self.assertEqual(open(status).read().split(), ["ok", "9.9.9"])
        self.assertEqual(open(os.path.join(dst, "lib", "x.dll")).read(), "novo")
        self.assertTrue(os.path.exists(os.path.join(dst, "DraftBot.exe")))
        self.assertTrue(os.path.exists(os.path.join(dst, "config.json")))   # arquivos do usuário ficam


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


class Janela(unittest.TestCase):
    """Janela própria: o programa encerra quando ela é fechada, e não antes."""

    class FakeSrv:
        def __init__(self): self.down = threading.Event()
        def shutdown(self): self.down.set()

    class FakeProc:
        def __init__(self, alive): self.alive = alive
        def poll(self): return None if self.alive else 0

    def run_watch(self, proc, beat=False, wait=1.2):
        W = DB.Window
        W.proc, W.seen = proc, 0.0
        srv = self.FakeSrv()
        stop = threading.Event()
        def heartbeat():
            while beat and not stop.is_set():
                W.seen = time.time(); time.sleep(0.02)
        threading.Thread(target=heartbeat, daemon=True).start()
        threading.Thread(target=W.watch, args=(srv, True, 0.05, 0.1), daemon=True).start()
        closed = srv.down.wait(wait)
        stop.set()
        return closed

    def test_fecha_quando_a_janela_fecha(self):
        self.assertTrue(self.run_watch(self.FakeProc(False)))

    def test_continua_com_a_janela_aberta(self):
        self.assertFalse(self.run_watch(self.FakeProc(True)))

    def test_continua_se_a_pagina_ainda_esta_aberta(self):
        # o processo lançado pode repassar a janela a outro já aberto; a página seguir pedindo dados basta
        self.assertFalse(self.run_watch(self.FakeProc(False), beat=True))

    def test_abre_em_modo_aplicativo(self):
        W, calls = DB.Window, []
        old = (DB.os.name, W.find, DB.subprocess.Popen, DB.webbrowser.open)
        try:
            DB.os.name = "nt"
            W.find = staticmethod(lambda: r"C:\Edge\msedge.exe")
            DB.subprocess.Popen = lambda args, **k: calls.append(args) or self.FakeProc(True)
            DB.webbrowser.open = lambda u: calls.append(["navegador", u])
            self.assertTrue(W.open("http://127.0.0.1:1"))
            W.find = staticmethod(lambda: None)
            self.assertFalse(W.open("http://127.0.0.1:1"))
        finally:
            DB.os.name, W.find, DB.subprocess.Popen, DB.webbrowser.open = old
        self.assertIn("--app=http://127.0.0.1:1", calls[0])
        self.assertTrue(any(a.startswith("--user-data-dir=") for a in calls[0]))
        self.assertEqual(calls[1], ["navegador", "http://127.0.0.1:1"])

    def test_icone(self):
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{SRV.server_address[1]}/favicon.ico", timeout=5) as r:
            self.assertEqual(r.read(4), b"\x00\x00\x01\x00")


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

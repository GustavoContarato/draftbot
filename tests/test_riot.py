"""Testes das estatísticas próprias (API da Riot) — riot.py e tools/collect.py."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.dirname(os.path.abspath(__file__))]
import riot as R  # noqa: E402
from mocks.fake_riot import FakeRiot, GOOD_KEY, ITEMS_JSON, make_match  # noqa: E402

ITEMS = R.ItemInfo(ITEMS_JSON)


class Agregacao(unittest.TestCase):
    def stats(self, n=40):
        s = R.new_stats("16.23", "BR")
        for i in range(n):
            m, tl = make_match(f"X{i}", seed=i)
            R.add_match(s, m, tl, ITEMS)
        return s

    def test_itens_classificados(self):
        self.assertIn(3031, ITEMS.legendary)
        self.assertIn(3006, ITEMS.boots)
        self.assertNotIn(1055, ITEMS.legendary)
        self.assertNotIn(3070, ITEMS.legendary)

    def test_partida_de_outro_patch_e_ignorada(self):
        s = R.new_stats("16.23", "BR")
        m, tl = make_match("Y", patch="16.22")
        self.assertFalse(R.add_match(s, m, tl, ITEMS))
        self.assertEqual(s["matches"], 0)

    def test_runas_itens_habilidades(self):
        s = self.stats()
        c = s["champs"]["Jinx|adc"]
        self.assertEqual(c["n"], 40)
        self.assertEqual(sum(v[0] for v in c["slots"]["p0"].values()), 40)
        self.assertEqual(set(c["slots"]["p0"]), {"8008", "8021"})
        self.assertEqual(c["skills"], {"QWE": [40, c["w"]]})
        self.assertEqual(list(c["start"]), ["1055,2003"])           # inicial (desfez a compra de 3070)
        self.assertEqual(list(c["boots"]), ["3006"])
        self.assertTrue(all(k.startswith("3031,3085,") for k in c["core3"]))
        self.assertIn("Ezreal", c["vs"])
        self.assertEqual(c["vs"]["Ezreal"]["n"], 40)

    def test_resumo_aponta_a_runa_melhor(self):
        s = self.stats(60)
        x = R.summary(s, "Jinx", "adc", "Ezreal", "ap")
        self.assertEqual(x["n"], 60)
        ks = x["slots"]["p0"]
        self.assertGreater(ks["8008"]["wr"], ks["8021"]["wr"])
        self.assertEqual(x["pages"][0]["ids"][0], 8008, "página mais jogada primeiro")
        self.assertEqual(len(x["pages"][0]["ids"]), 9)
        self.assertEqual(x["vs"]["opp"], "Ezreal")
        self.assertEqual(x["comp"]["type"], "ap")
        self.assertIn("3156", [i["key"] for i in x["comp"]["items"]], "item que só aparece contra AP")
        self.assertIsNone(R.summary(s, "Teemo", "top"))

    def test_juntar_dois_arquivos(self):
        a, b = self.stats(10), self.stats(15)
        R.merge(a, b)
        self.assertEqual(a["matches"], 25)
        self.assertEqual(a["champs"]["Jinx|adc"]["n"], 25)
        self.assertEqual(sum(v[0] for v in a["champs"]["Jinx|adc"]["slots"]["p0"].values()), 25)
        self.assertEqual(R.merge(a, dict(b, patch="16.22"))["matches"], 25, "outro patch não soma")

    def test_tipo_de_time(self):
        self.assertEqual(R.comp_type(9000, 1000), "ap")
        self.assertEqual(R.comp_type(1000, 9000), "ad")
        self.assertEqual(R.comp_type(4000, 5000), "mix")


class Coleta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeRiot().start()

    def test_coleta_retoma_e_nao_repete(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "riot.json")
        api = R.RiotAPI(GOOD_KEY, "BR", base=self.fake.url)
        col = R.Collector(api, "16.23", path, ITEMS, log=lambda *a: None)
        total = 0
        for _ in range(12):
            total += col.step(max_matches=30)
        col.save()
        self.assertEqual(col.stats["matches"], 60, "todas as partidas do patch, sem repetir")
        self.assertEqual(total, 60)
        self.assertTrue(all(k.startswith("BR1_1") or k.startswith("BR1_9") for k in col.done))
        col2 = R.Collector(api, "16.23", path, ITEMS, log=lambda *a: None)     # reabriu o programa
        self.assertEqual(col2.stats["matches"], 60)
        self.assertEqual(col2.step(max_matches=30), 0)
        col3 = R.Collector(api, "16.24", path, ITEMS, log=lambda *a: None)     # patch novo: começa do zero
        self.assertEqual(col3.stats["matches"], 0)

    def test_chave_recusada(self):
        api = R.RiotAPI("RGAPI-errada", "BR", base=self.fake.url)
        with self.assertRaises(R.RiotError) as e:
            api.check()
        self.assertEqual(e.exception.status, 403)

    def test_espera_o_limite(self):
        lim = R.Limiter(windows=((0.5, 3),))
        t0 = time.time()
        for _ in range(6):
            lim.wait()
        self.assertGreater(time.time() - t0, 0.45)

    def test_coleta_do_github(self):
        d = tempfile.mkdtemp()
        dd = os.path.join(d, "dd")
        os.makedirs(os.path.join(dd, "api"))
        os.makedirs(os.path.join(dd, "cdn", "16.23.1", "data", "en_US"))
        json.dump(["16.23.1"], open(os.path.join(dd, "api", "versions.json"), "w"))
        json.dump(ITEMS_JSON, open(os.path.join(dd, "cdn", "16.23.1", "data", "en_US", "item.json"), "w"))
        import http.server
        import functools
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(
            http.server.SimpleHTTPRequestHandler, directory=dd))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        env = dict(os.environ, RIOT_API_KEY=GOOD_KEY, DRAFTBOT_RIOT_API=self.fake.url,
                   DRAFTBOT_DDRAGON=f"http://127.0.0.1:{srv.server_address[1]}")
        out = os.path.join(d, "riot-BR-16.23.json")
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "collect.py"), "--minutes", "0.15",
                            "--out", out], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        s = json.load(open(out))
        self.assertEqual(s["patch"], "16.23")
        self.assertGreater(s["matches"], 0)
        # sem chave: não faz nada e não falha
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "collect.py")],
                           env=dict(env, RIOT_API_KEY=""), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Sem RIOT_API_KEY", r.stdout)
        srv.shutdown()


if __name__ == "__main__":
    unittest.main()

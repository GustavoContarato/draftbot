"""API da OP.GG simulada (formato compacto real + guia em JSON) para os testes.

    op = FakeOPGG(); op.start()
    op.version = "16.23"     # simula patch novo
    op.fail = 2              # as próximas 2 chamadas falham (HTTP 503)
    op.calls                 # lista de (ferramenta, argumentos) recebidas
    op.scale = 0.01          # patch recém-saído: 1% das partidas
    op.shift = 0.05          # e taxas de vitória diferentes (para ver a mistura)
"""
import json
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

POS = {
    "top": ["Darius", "Garen", "Aatrox", "Sett", "Teemo", "Malphite", "Camille", "Fiora"],
    "jungle": ["Lee Sin", "Vi", "Graves", "Kha'Zix", "Jarvan IV", "Viego", "Amumu", "Warwick"],
    "mid": ["Ahri", "Malzahar", "Syndra", "Yasuo", "Viktor", "Orianna", "Katarina", "Locke"],
    "adc": ["Xayah", "Jhin", "Jinx", "Kai'Sa", "Kog'Maw", "Miss Fortune", "Draven", "Caitlyn", "Ezreal", "Twitch"],
    "support": ["Thresh", "Lulu", "Nautilus", "Leona", "Nami", "Braum", "Janna", "Pyke"],
}


def _it(ids, names, play=1000, win=520, pick=0.4):
    return {"ids": ids, "ids_names": names, "play": play, "win": win, "pick_rate": pick}


class FakeOPGG:
    def __init__(self):
        self.version = "16.22"
        self.fail = 0
        self.calls = []
        self.small = {"SYNDRA"}
        self.scale = 1.0
        self.shift = 0.0      # confrontos com poucas partidas (testa a build geral)
        self.srv = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.srv.server_address[1]}/mcp"

    def start(self):
        op = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                m = json.loads(self.rfile.read(n))
                name, a = m["params"]["name"], m["params"]["arguments"]
                op.calls.append((name, a))
                if op.fail > 0:
                    op.fail -= 1
                    self.send_response(503)
                    self.end_headers()
                    return
                txt = {"lol_list_lane_meta_champions": op.meta, "lol_get_lane_matchup_guide": op.guide,
                       "lol_get_champion_analysis": op.analysis, "lol_get_champion_synergies": op.synergy}[name](a)
                b = json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": {"content": [{"type": "text", "text": txt}]}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self.srv:
            self.srv.shutdown()
            self.srv.server_close()

    # ---- respostas no formato real observado na API ----
    def meta(self, a):
        head = ("class LolListLaneMetaChampions: data\nclass Data: positions\nclass Positions: top,jungle,mid,adc,support\n"
                "class Top: champion,tier,rank,win,win_rate,pick_rate,ban_rate,role_rate,play,is_rip\n\n")
        parts = []
        for p, l in POS.items():
            rows = []
            for i, c in enumerate(l):
                play = int((200000 - i * 15000) * self.scale)
                wr = 0.53 - i * 0.004 + self.shift
                rows.append(f'Top("{c}",{1 + i // 3},{i + 1},{int(play * wr)},{wr:.2f},{0.12 - i * 0.01:.3f},0.02,0.95,{play},false)')
            parts.append("[" + ",".join(rows) + "]")
        return head + "LolListLaneMetaChampions(Data(Positions(" + ",".join(parts) + ")))"

    def analysis(self, a):
        if "data.trends.win.{version,rate}" in a["desired_output_fields"]:
            return (f'class LolGetChampionAnalysis: data\nclass Data: trends\nclass Trends: win\nclass Win: version,rate\n\n'
                    f'LolGetChampionAnalysis(Data(Trends([Win("{self.version}",0.51)])))')
        return '''class LolGetChampionAnalysis: data
class Data: summary,core_items,boots,starter_items,summoner_spells,runes,last_items,skill_masteries,skills
class Summary: average_stats
class AverageStats: win_rate,pick_rate,tier,rank
class CoreItems: ids,ids_names,play,win,pick_rate
class Runes: primary_page_id,primary_rune_ids,primary_rune_names,secondary_page_id,secondary_rune_ids,secondary_rune_names,stat_mod_ids,stat_mod_names,play,win,pick_rate
class SkillMastery: ids,play,win,pick_rate
class Skill: order,play,win,pick_rate

LolGetChampionAnalysis(Data(Summary(AverageStats(0.51,0.11,1,8)),CoreItems([3157,3089,3135],["Ampulheta de Zhonya","Capuz da Morte de Rabadon","Cajado do Vazio"],4000,2100,0.4),CoreItems([3020],["Sapatos do Feiticeiro"],5000,2600,0.9),CoreItems([1056,2003],["Anel de Doran","Poção"],5000,2600,0.8),CoreItems([4,14],[4,14],5000,2600,0.8),Runes(8100,[8112,8139,8140,8106],["Eletrocutar","Gosto de Sangue","Recordações Macabras","Caçador Supremo"],8200,[8226,8210],["Faixa de Fluxo de Mana","Transcendência"],[5008,5008,5001],[5008,5008,5001],45395,23000,0.36),[CoreItems([3157],["Ampulheta de Zhonya"],100,52,0.47)],SkillMastery(["Q","W","E"],10,5,0.9),Skill(["Q","E","W","Q","Q","R"],500,260,0.5)))'''

    def guide(self, a):
        pos, me = a["position"], a["my_champion"]
        small = me in self.small
        counters = [{"champion_id": i, "champion_name": c, "play": int((5000 + i * 300) * self.scale),
                     "win": int((5000 + i * 300) * self.scale * (0.44 + self.shift + (sum(map(ord, me + c)) % 120) / 1000))}
                    for i, c in enumerate(POS[pos])]
        rune = {"id": 8008, "primary_page_id": 8000, "primary_rune_ids": [8008, 8009, 9103, 8017],
                "primary_rune_names": ["Ritmo Fatal", "Presença de Espírito", "Lenda: Linhagem", "Dilacerar"],
                "secondary_page_id": 8300, "secondary_rune_ids": [8313, 8321], "secondary_rune_names": ["Tônico Triplo", "Reembolso"],
                "stat_mod_ids": [5005, 5008, 5011], "play": 30 if small else 2773, "win": 14 if small else 1397, "pick_rate": 0.58}
        return json.dumps({"position": pos, "my_champion": me, "opponent_champion": a["opponent_champion"], "data": {
            "summary": {"positions": [{"name": pos.upper(), "stats": {"play": 250000, "win_rate": 0.511}}]},
            "summoner_spells": [_it([4, 21], ["Flash", "Barreira"])],
            "core_items": [_it([3031, 3036, 3026], ["Gume do Infinito", "Lembranças do Lorde Dominik", "Anjo Guardião"],
                               20 if small else 1000, 9 if small else 520)],
            "boots": [_it([3006], ["Grevas do Berserker"])], "starter_items": [_it([1055, 2003], ["Lâmina de Doran", "Poção de Vida"])],
            "last_items": [_it([3036], ["Lembranças do Lorde Dominik"], 900, 470, 0.5)],
            "runes": [rune], "skill_masteries": [{"ids": ["Q", "W", "E"], "play": 900, "win": 470, "pick_rate": 0.9}],
            "skills": [{"order": list("QWEQQRQWQWRWWEERER"), "play": 900, "win": 470, "pick_rate": 0.6}],
            "counters": counters, "opponent_champion_tip": "Não deixe ele chegar perto.",
            "lane_advantage_champion": "EVEN", "recommended_play_style": "even"}}, ensure_ascii=False)

    def synergy(self, a):
        l = POS[a["synergy_position"]]
        rows = ",".join(f'Synergie("{c}",{i + 1},0,{int((9000 - i * 500) * self.scale)},{0.54 - i * 0.01 + self.shift:.2f})' for i, c in enumerate(l[:6]))
        return ("class LolGetChampionSynergies: data\nclass Data: synergies\n"
                "class Synergie: synergy_champion_name,score_rank,score,play,win_rate\n\n"
                f"LolGetChampionSynergies(Data([{rows}]))")

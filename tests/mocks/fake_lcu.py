"""Cliente do LoL simulado (API local LCU) para os testes.

Roda num servidor HTTP em porta livre. O estado é controlado direto pelo teste:
    lcu = FakeLCU(); lcu.start()
    lcu.account = "B"; lcu.locked = True; lcu.map_id = 12
"""
import copy
import json
import random
import threading
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

CHAMPS = [
    (266, "Aatrox", "Aatrox"), (121, "Khazix", "Kha'Zix"), (90, "Malzahar", "Malzahar"), (119, "Draven", "Draven"),
    (89, "Leona", "Leona"), (516, "Ornn", "Ornn"), (64, "LeeSin", "Lee Sin"), (103, "Ahri", "Ahri"), (117, "Lulu", "Lulu"),
    (222, "Jinx", "Jinx"), (96, "KogMaw", "Kog'Maw"), (62, "MonkeyKing", "Wukong"), (134, "Syndra", "Syndra"),
    (412, "Thresh", "Thresh"), (122, "Darius", "Darius"), (21, "MissFortune", "Miss Fortune"), (29, "Twitch", "Twitch"),
    (51, "Caitlyn", "Caitlyn"), (81, "Ezreal", "Ezreal"), (202, "Jhin", "Jhin"), (145, "Kaisa", "Kai'Sa"),
    (498, "Xayah", "Xayah"), (999, "Zyrael", "Zyrael"),   # Zyrael: campeão "lançado depois" da lista do app
]
ITEMS = [(3033, "Lembrete Mortal"), (3157, "Ampulheta de Zhonya"), (3031, "Gume do Infinito"),
         (3036, "Lembranças do Lorde Dominik"), (3026, "Anjo Guardião"), (3006, "Grevas do Berserker"),
         (1055, "Lâmina de Doran"), (2003, "Poção de Vida"), (3156, "Mandíbula de Malmortius"), (3111, "Passos de Mercúrio")]
PERKS = [8008, 8009, 9104, 9103, 8017, 8014, 8473, 8451, 8444, 8304, 8345, 8313, 8321, 5005, 5008, 5011, 5013, 5001,
         8465, 8463, 9101, 8453, 8226, 8210, 8214, 8237, 8275, 5007]
SESSION = {
    "localPlayerCellId": 2,
    "myTeam": [{"cellId": 0, "championId": 516, "assignedPosition": "top"},
               {"cellId": 1, "championId": 64, "assignedPosition": "jungle"},
               {"cellId": 2, "championId": 0, "championPickIntent": 134, "assignedPosition": "middle"},
               {"cellId": 3, "championId": 222, "assignedPosition": "bottom"},
               {"cellId": 4, "championId": 117, "assignedPosition": "utility"}],
    "theirTeam": [{"cellId": 5, "championId": 89}, {"cellId": 6, "championId": 266}, {"cellId": 7, "championId": 121},
                  {"cellId": 8, "championId": 119}, {"cellId": 9, "championId": 90}],
    "bans": {"myTeamBans": [103], "theirTeamBans": [62]},
    "actions": [[{"actorCellId": 2, "type": "pick", "isInProgress": True, "completed": False, "championId": 96}]],
    "timer": {"adjustedTimeLeftInPhase": 21000},
}


def _games(puuid, pool, seed):
    rnd = random.Random(seed)
    out, gid = [], seed * 10000
    for cid, lane, role, n, wr, queue in pool:
        for _ in range(n):
            gid += 1
            out.append({"gameId": gid, "gameCreation": 1794800000000 - gid * 1000, "queueId": queue, "mapId": 11,
                        "participantIdentities": [{"participantId": 1, "player": {"puuid": puuid}}],
                        "participants": [{"participantId": 1, "championId": cid,
                                          "stats": {"win": rnd.random() < wr, "kills": rnd.randint(1, 12),
                                                    "deaths": rnd.randint(1, 8), "assists": rnd.randint(2, 15)},
                                          "timeline": {"lane": lane, "role": role}}]})
    rnd.shuffle(out)
    return out


ACCOUNTS = {
    "A": {"summoner": {"summonerId": 77, "accountId": 5, "puuid": "a-puuid", "gameName": "Contarato", "tagLine": "BR1"},
          "games": _games("a-puuid", [(222, "BOTTOM", "CARRY", 30, .6, 420), (21, "BOTTOM", "CARRY", 18, .55, 440),
                                      (81, "BOTTOM", "CARRY", 6, .5, 420), (103, "MIDDLE", "SOLO", 10, .5, 420),
                                      (202, "BOTTOM", "CARRY", 7, .5, 400),   # normal alternada: deve ser ignorada
                                      (222, "BOTTOM", "CARRY", 5, .5, 490)],  # rápida: deve ser ignorada
                          1)
          + [{"gameId": 9 + i, "queueId": 450, "mapId": 12, "participants": [{"championId": 222, "stats": {"win": True}}]}
             for i in range(5)],                                               # ARAM: deve ser ignorado
          "mastery": [{"championId": 222, "championLevel": 7, "championPoints": 312000},
                      {"championId": 21, "championLevel": 6, "championPoints": 95000},
                      {"championId": 202, "championLevel": 5, "championPoints": 61000}],
          "owned": [222, 21, 202, 81, 103, 134, 516, 64, 117, 412, 89, 999]},   # não tem Twitch nem Xayah
    "B": {"summoner": {"summonerId": 88, "accountId": 6, "puuid": "b-puuid", "gameName": "Amigo", "tagLine": "2077"},
          "games": _games("b-puuid", [(412, "BOTTOM", "SUPPORT", 18, .66, 420), (89, "BOTTOM", "SUPPORT", 7, .5, 420)], 2),
          "mastery": [{"championId": 412, "championLevel": 7, "championPoints": 250000}],
          "owned": [412, 89, 117, 222]},
}


class FakeLCU:
    def __init__(self):
        self.account = "A"          # conta logada ("A", "B" ou None para deslogado)
        self.phase = "ChampSelect"
        self.locked = False         # se o jogador local já travou a Syndra
        self.map_id = 11            # 11 = Summoner's Rift, 12 = ARAM
        self.game_id = 777
        self.posts, self.puts, self.deletes = [], [], []
        self.reco_calls, self.icon_calls = [], []
        self.srv = None

    @property
    def port(self):
        return self.srv.server_address[1]

    def start(self):
        lcu = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def j(self, o, code=200):
                d = json.dumps(o).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(d)))
                self.end_headers()
                self.wfile.write(d)

            def do_GET(self):
                return lcu._get(self)

            def do_PUT(self):
                n = int(self.headers.get("Content-Length", 0))
                b = json.loads(self.rfile.read(n))
                lcu.puts.append((self.path, b))
                self.j(b)

            def do_DELETE(self):
                lcu.deletes.append(self.path)
                self.send_response(204)
                self.end_headers()

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                b = json.loads(self.rfile.read(n))
                lcu.posts.append((self.path, b))
                self.j(b)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self.srv:
            self.srv.shutdown()
            self.srv.server_close()

    def _get(self, h):
        p = h.path
        acc = ACCOUNTS.get(self.account) if self.account else None
        if p == "/lol-gameflow/v1/gameflow-phase":
            return h.j(self.phase)
        if p == "/lol-game-data/assets/v1/items.json":
            return h.j([{"id": i, "name": n} for i, n in ITEMS])
        if p == "/lol-game-data/assets/v1/champion-summary.json":
            return h.j([{"id": -1, "alias": "None", "name": "Nenhum"}] + [{"id": i, "alias": a, "name": n,
                        "squarePortraitPath": f"/lol-game-data/assets/v1/champion-icons/{i}.png"} for i, a, n in CHAMPS])
        if p == "/lol-champ-select/v1/session":
            s = copy.deepcopy(SESSION)
            s["gameId"] = self.game_id
            if self.locked:
                for m in s["myTeam"]:
                    if m["cellId"] == 2:
                        m["championId"], m["championPickIntent"] = 134, 0
                s["actions"] = [[{"actorCellId": 2, "type": "pick", "isInProgress": False, "completed": True, "championId": 134}]]
            return h.j(s)
        if p == "/lol-perks/v1/perks":
            return h.j([{"id": i, "name": f"Runa {i}"} for i in PERKS])
        if p.startswith("/lol-perks/v1/recommended-pages/champion/"):
            self.reco_calls.append(p)
            if "/position/UTILITY/" not in p and "/position/BOTTOM/" not in p:
                return h.j([])
            return h.j([
                {"keystone": {"id": 8008, "name": "Ritmo Fatal"}, "primaryPerkStyleId": 8000, "secondaryPerkStyleId": 8400,
                 "perks": [{"id": i} for i in (8008, 8009, 9104, 8017, 8473, 8451)]},
                {"keystone": {"id": 8465, "name": "Guardião"}, "primaryPerkStyleId": 8400, "secondaryPerkStyleId": 8300,
                 "perks": [{"id": i} for i in (8465, 8463, 8473, 8451, 8304, 8345, 5008, 5008, 5001)]}])
        if p == "/lol-game-data/assets/v1/perks.json":
            return h.j([{"id": i, "iconPath": f"/lol-game-data/assets/v1/perk-images/Styles/Runa{i}.png"} for i in PERKS])
        if p.startswith("/lol-game-data/assets/") and p.endswith(".png"):
            self.icon_calls.append(p)
            d = b"\x89PNG\r\n\x1a\n" + p.encode()
            h.send_response(200)
            h.send_header("Content-Type", "image/png")
            h.send_header("Content-Length", str(len(d)))
            h.end_headers()
            h.wfile.write(d)
            return
        if p == "/lol-perks/v1/pages":
            return h.j([{"id": 7, "name": "DraftBot · Antiga", "isDeletable": True}, {"id": 8, "name": "Minha página", "isDeletable": True}])
        if p.startswith("/lol-summoner/v1/current-summoner"):
            return h.j(acc["summoner"]) if acc else h.j({"message": "not logged in"}, 404)
        if p.startswith("/lol-ranked/v1/current-ranked-stats"):
            return h.j({"queues": [{"queueType": "RANKED_SOLO_5x5", "tier": "GOLD", "division": "II", "leaguePoints": 47}]})
        if p.startswith("/lol-champions/v1/owned-champions-minimal"):
            return h.j([{"id": i, "ownership": {"owned": i in acc["owned"]}} for i, _, _ in CHAMPS])
        if p == "/lol-champ-select/v1/pickable-champion-ids":
            return h.j([i for i in acc["owned"] if i != 103])
        if p == "/lol-gameflow/v1/session":
            sr = self.map_id == 11
            return h.j({"gameData": {"queue": {"id": 420 if sr else 450, "mapId": self.map_id, "gameMode": "CLASSIC" if sr else "ARAM",
                                               "description": "Ranqueada Solo/Duo" if sr else "ARAM"}}})
        if p.startswith("/lol-champion-mastery"):
            return h.j(acc["mastery"])
        if p.startswith("/lol-match-history"):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(p).query))
            b, e = int(q["begIndex"]), int(q["endIndex"])
            return h.j({"games": {"games": acc["games"][b:e + 1]}})
        if p.startswith("/lol-item-sets"):
            return h.j({"accountId": 5, "itemSets": [{"title": "Meu set"}, {"title": "DraftBot · Antigo"}]})
        h.send_response(404)
        h.end_headers()

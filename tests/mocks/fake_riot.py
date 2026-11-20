"""API da Riot falsa para os testes: ligas Mestre+, lista de partidas, partidas e timelines geradas."""
import json
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

GOOD_KEY = "RGAPI-00000000-1111-2222-3333-444444444444"
PERKS_A = ([8008, 9111, 9104, 8014], [8473, 8451], [5005, 5008, 5011], 8000, 8400)   # Ritmo Fatal
PERKS_B = ([8021, 9111, 9104, 8014], [8473, 8451], [5005, 5008, 5011], 8000, 8400)   # Agilidade nos Pés
SUP = ([8465, 8463, 8473, 8451], [8304, 8345], [5008, 5008, 5001], 8400, 8300)


def participant(pid, team, champ, pos, win, perks, magic=1000, phys=9000):
    pr, sr, sh, ps, ss = perks
    return {"participantId": pid, "teamId": team, "championName": champ, "teamPosition": pos, "win": win,
            "summoner1Id": 4, "summoner2Id": 7 if pos == "BOTTOM" else 14,
            "magicDamageDealtToChampions": magic, "physicalDamageDealtToChampions": phys,
            "perks": {"statPerks": {"offense": sh[0], "flex": sh[1], "defense": sh[2]},
                      "styles": [{"description": "primaryStyle", "style": ps, "selections": [{"perk": x} for x in pr]},
                                 {"description": "subStyle", "style": ss, "selections": [{"perk": x} for x in sr]}]}}


def make_match(mid, patch="16.23", seed=0):
    """Jinx (BOTTOM, time 100) x Ezreal; Ritmo Fatal ganha mais que Agilidade; time inimigo às vezes AP."""
    r = random.Random(seed)
    use_a = r.random() < 0.7
    jinx_win = r.random() < (0.58 if use_a else 0.40)
    enemy_ap = r.random() < 0.5
    pos = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
    blue = ["Darius", "LeeSin", "Ahri", "Jinx", "Thresh"]
    red = ["Garen", "Viego", "Syndra" if enemy_ap else "Zed", "Ezreal", "Lulu" if enemy_ap else "Nautilus"]
    parts = []
    for i in range(5):
        perks = (PERKS_A if use_a else PERKS_B) if blue[i] == "Jinx" else SUP
        parts.append(participant(i + 1, 100, blue[i], pos[i], jinx_win, perks))
    for i in range(5):
        parts.append(participant(i + 6, 200, red[i], pos[i], not jinx_win, SUP,
                                 magic=9000 if enemy_ap else 1000, phys=1000 if enemy_ap else 9000))
    m = {"metadata": {"matchId": mid}, "info": {"queueId": 420, "gameVersion": f"{patch}.700.1234",
                                                  "participants": parts}}
    # Jinx: botas → Hexótica (6676?) — itens: 3006 berserker, 2523/3085/3031; contra AP compra 3156 (Maw)
    core = [3031, 3085, 3156] if enemy_ap and jinx_win else [3031, 3085, 3036]
    ev = [{"type": "ITEM_PURCHASED", "participantId": 4, "itemId": 1055, "timestamp": 1000},
          {"type": "ITEM_PURCHASED", "participantId": 4, "itemId": 2003, "timestamp": 1500},
          {"type": "ITEM_PURCHASED", "participantId": 4, "itemId": 3070, "timestamp": 300000},
          {"type": "ITEM_UNDO", "participantId": 4, "beforeId": 3070, "afterId": 0, "timestamp": 301000},
          {"type": "ITEM_PURCHASED", "participantId": 4, "itemId": 3006, "timestamp": 400000}]
    ev += [{"type": "ITEM_PURCHASED", "participantId": 4, "itemId": it, "timestamp": 600000 + i * 300000}
           for i, it in enumerate(core)]
    for lvl, slot in enumerate([1, 2, 3, 1, 1, 4, 1, 2, 1, 2, 4, 2, 2, 3, 3, 4, 3, 3]):
        ev.append({"type": "SKILL_LEVEL_UP", "participantId": 4, "skillSlot": slot, "levelUpType": "NORMAL",
                   "timestamp": 10000 * (lvl + 1)})
    tl = {"info": {"frames": [{"events": ev}]}}
    return m, tl


class FakeRiot:
    def __init__(self):
        self.calls = []
        self.fail_429 = 1
        self.matches = {}
        for i in range(60):
            self.matches[f"BR1_{1000 + i}"] = make_match(f"BR1_{1000 + i}", seed=i)
        for i in range(10):          # partidas do patch anterior (mais antigas)
            self.matches[f"BR1_{900 + i}"] = make_match(f"BR1_{900 + i}", patch="16.22", seed=100 + i)

    def start(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def j(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                if code == 429:
                    self.send_header("Retry-After", "1")
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                u = urlparse(self.path)
                p = u.path
                fake.calls.append(p)
                if self.headers.get("X-Riot-Token") != GOOD_KEY:
                    return self.j(403, {"status": {"message": "Forbidden"}})
                if p == "/lol/status/v4/platform-data":
                    return self.j(200, {"id": "BR1"})
                if p.startswith("/lol/league/v4/"):
                    tier = p.split("/")[4]
                    return self.j(200, {"entries": [{"puuid": f"{tier}-{i}"} for i in range(3)]})
                if p.endswith("/ids"):
                    if fake.fail_429 > 0:
                        fake.fail_429 -= 1
                        return self.j(429, {})
                    ids = sorted((k for k in fake.matches if k.startswith("BR1_1")), reverse=True)
                    who = int(p.split("/")[-2][-1]) % 3
                    ids = ids[who * 20: who * 20 + 20] + sorted((k for k in fake.matches if k.startswith("BR1_9")),
                                                                reverse=True)
                    return self.j(200, ids[:25])
                if p.startswith("/lol/match/v5/matches/"):
                    mid = p.split("/")[5]
                    if mid not in fake.matches:
                        return self.j(404, {})
                    m, tl = fake.matches[mid]
                    return self.j(200, tl if p.endswith("/timeline") else m)
                return self.j(404, {})

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self


ITEMS_JSON = {"data": {
    "1055": {"gold": {"total": 450}, "tags": ["Lane"], "maps": {"11": True}},
    "2003": {"gold": {"total": 50}, "tags": ["Consumable"], "maps": {"11": True}},
    "1001": {"gold": {"total": 300}, "tags": ["Boots"], "into": ["3006"], "maps": {"11": True}},
    "3006": {"gold": {"total": 1100}, "tags": ["Boots"], "from": ["1001"], "maps": {"11": True}},
    "3070": {"gold": {"total": 400}, "tags": ["Mana"], "into": ["3004"], "maps": {"11": True}},
    "3031": {"gold": {"total": 3450}, "tags": ["CriticalStrike"], "maps": {"11": True}},
    "3085": {"gold": {"total": 2650}, "tags": ["AttackSpeed"], "maps": {"11": True}},
    "3036": {"gold": {"total": 3000}, "tags": ["ArmorPenetration"], "maps": {"11": True}},
    "3156": {"gold": {"total": 3100}, "tags": ["SpellBlock"], "maps": {"11": True}},
}}

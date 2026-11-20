"""Coleta diária no GitHub: junta partidas Mestre+ do patch atual e publica o arquivo de estatísticas.

    RIOT_API_KEY=... python tools/collect.py --region BR --minutes 50 --prev anterior.json --out riot-BR-16.23.json

Retoma o arquivo anterior (--prev, se for do mesmo patch) e evita partidas repetidas.
"""
import argparse
import json
import os
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import riot as RIOT  # noqa: E402


def current_patch(ddragon):
    req = urllib.request.Request(ddragon + "/api/versions.json", headers={"User-Agent": "DraftBot-collector"})
    with urllib.request.urlopen(req, timeout=20) as r:
        v = json.loads(r.read().decode("utf-8"))[0]
    return v, RIOT.patch_of(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="BR")
    ap.add_argument("--minutes", type=float, default=50)
    ap.add_argument("--prev", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--ddragon", default=os.environ.get("DRAFTBOT_DDRAGON", "https://ddragon.leagueoflegends.com"))
    ap.add_argument("--api-base", default=os.environ.get("DRAFTBOT_RIOT_API"))
    a = ap.parse_args()
    key = os.environ.get("RIOT_API_KEY", "").strip()
    if not key:
        print("Sem RIOT_API_KEY: nada a fazer.")
        return 0
    version, patch = current_patch(a.ddragon)
    out = a.out or f"riot-{a.region.upper()}-{patch}.json"
    api = RIOT.RiotAPI(key, a.region, base=a.api_base, ua="DraftBot-collector")
    api.check()
    items = RIOT.ItemInfo.fetch(a.ddragon, version, ua="DraftBot-collector")
    # o arquivo anterior vira o ponto de partida (mesmo patch)
    if a.prev and os.path.exists(a.prev) and os.path.abspath(a.prev) != os.path.abspath(out):
        try:
            prev = json.load(open(a.prev, encoding="utf-8"))
            if prev.get("patch") == patch:
                json.dump(prev, open(out, "w", encoding="utf-8"))
        except ValueError:
            pass
    col = RIOT.Collector(api, patch, out, items, a.region, log=print)
    stop = threading.Event()
    end = time.time() + a.minutes * 60
    threading.Timer(a.minutes * 60, stop.set).start()      # para no meio de uma espera, se preciso
    t0, n0 = time.time(), col.stats["matches"]
    while time.time() < end and not stop.is_set():
        try:
            col.step(stop)
        except InterruptedError:
            break
        except RIOT.RiotError as e:
            print("Erro:", e)
            if e.status in (401, 403):
                break
            stop.wait(20)
        if col.dirty and int(time.time() - t0) % 300 < 5:
            col.save()
    col.save()
    print(f"Patch {patch}: {col.stats['matches']} partidas no arquivo ({col.stats['matches'] - n0} novas nesta rodada).")
    print(f"ARQUIVO={out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

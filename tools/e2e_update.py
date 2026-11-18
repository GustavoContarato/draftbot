"""Teste de ponta a ponta da atualização automática com o DraftBot.exe de verdade (roda no Windows, no GitHub).

    python tools/e2e_update.py build\\draftbot.dist

Copia o programa para uma pasta com acento, publica uma "versão 99.0.0" num servidor local,
pede a atualização pela API e confere: arquivos trocados, programa reaberto, resultado "ok".
"""

import hashlib, http.server, json, os, shutil, socket, subprocess, sys, tempfile, threading, time
import urllib.request, zipfile

exe_src = os.path.abspath(sys.argv[1])
root = tempfile.mkdtemp(prefix="draftbot-e2e-")
app = os.path.join(root, "Área de Trabalho", "DraftBot")
os.makedirs(app)
shutil.copy(exe_src, os.path.join(app, "DraftBot.exe"))
with open(os.path.join(app, "LEIA-ME.txt"), "w", encoding="utf-8") as f:
    f.write("leia-me antigo")
data = os.path.join(root, "dados")

# pacote "novo": o mesmo programa + um arquivo marcador
pub = os.path.join(root, "publicado")
os.makedirs(pub)
zpath = os.path.join(pub, "DraftBot-v99.0.0-windows.zip")
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(exe_src, "DraftBot/DraftBot.exe")
    z.writestr("DraftBot/LEIA-ME.txt", "leia-me novo")
    z.writestr("DraftBot/marcador-99.txt", "versão nova")
sha = hashlib.sha256(open(zpath, "rb").read()).hexdigest()


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


fport, aport = free_port(), free_port()
with open(os.path.join(pub, "version.json"), "w", encoding="utf-8") as f:
    json.dump({"version": "99.0.0", "notes": "teste", "sha256": sha,
               "url": f"http://127.0.0.1:{fport}/DraftBot-v99.0.0-windows.zip"}, f)
H = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=pub, **k)
files = http.server.ThreadingHTTPServer(("127.0.0.1", fport), H)
threading.Thread(target=files.serve_forever, daemon=True).start()

env = dict(os.environ, DRAFTBOT_UPDATE_URL=f"http://127.0.0.1:{fport}/version.json", DRAFTBOT_TEST_UPDATES="1",
           DRAFTBOT_PORT=str(aport), DRAFTBOT_DATA=data, DRAFTBOT_LCU="http://127.0.0.1:1|x")
exe = os.path.join(app, "DraftBot.exe")
subprocess.Popen([exe, "--no-browser"], cwd=app, env=env)
base = f"http://127.0.0.1:{aport}"


def get(path, method="GET", body=None):
    req = urllib.request.Request(base + path, method=method, data=body,
                                 headers={"X-DraftBot": "1", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def wait(cond, secs, what):
    t = time.time()
    while time.time() - t < secs:
        try:
            v = cond()
            if v:
                return v
        except Exception:
            pass
        time.sleep(0.5)
    raise SystemExit(f"FALHOU: {what}")


try:
    v = wait(lambda: (lambda x: x if x.get("update") else None)(get("/api/version")), 40, "aviso de versão nova")
    assert v["autoUpdate"], f"atualização automática indisponível: {v}"
    r = get("/api/update", "POST", b"{}")
    assert r.get("ok"), r
    print("atualização pedida:", r)
    time.sleep(3)
    v = wait(lambda: (lambda x: x if x.get("updated") else None)(get("/api/version")), 60, "programa reaberto")
    print("depois:", v["updated"])
    assert v["updated"] == {"result": "ok", "version": "99.0.0"}, v
    assert os.path.exists(os.path.join(app, "marcador-99.txt")), "arquivos não foram trocados"
    assert open(os.path.join(app, "LEIA-ME.txt"), encoding="utf-8").read() == "leia-me novo"
    print("pasta do programa:", sorted(os.listdir(app)))
    left = [f for f in os.listdir(app) if ".draftbot-antigo" in f]
    print("antigos que sobraram:", left)
    assert not left, "arquivos antigos não foram apagados"
    print("E2E OK: atualização baixada, conferida, instalada e programa reaberto")
finally:
    try:
        print("--- draftbot.log ---")
        print(open(os.path.join(data, "draftbot.log"), encoding="utf-8", errors="replace").read()[-4000:])
        print("--- pasta do programa ---", sorted(os.listdir(app))[:40])
        print("--- tarefas ---", subprocess.run(["tasklist", "/FI", "IMAGENAME eq DraftBot.exe"], capture_output=True, text=True).stdout)
    except Exception as e:
        print("sem registro:", e)
    subprocess.run(["taskkill", "/F", "/IM", "DraftBot.exe"], capture_output=True)
    files.shutdown()

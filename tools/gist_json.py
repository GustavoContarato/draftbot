"""Monta o conteúdo do version.json do gist (aviso de nova versão + atualização automática).

    python tools/gist_json.py 2.5.0 <sha256 do zip> [link do Drive]
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
version, sha = sys.argv[1], sys.argv[2].strip().lower()
url = sys.argv[3] if len(sys.argv) > 3 else "COLE_AQUI_O_LINK_DO_DRIVE"
notes = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "release_notes.py"), version],
                       capture_output=True, text=True, encoding="utf-8").stdout
first = " ".join(l.lstrip("- ").strip() for l in notes.splitlines()[:2])[:300]
print(json.dumps({"version": version, "url": url, "notes": first, "sha256": sha}, ensure_ascii=False, indent=2))

"""Imprime as notas da versão (seção do CHANGELOG.md) — usadas na release e no aviso de atualização."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
version = sys.argv[1]
text = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
m = re.search(rf"^## v{re.escape(version)}\b.*?$\n(.*?)(?=^## v|\Z)", text, re.M | re.S)
print((m.group(1) if m else "").strip())

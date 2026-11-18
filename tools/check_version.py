"""Confere se a tag do Git (ex.: v2.2.0) bate com a VERSION do draftbot.py."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "draftbot.py"), encoding="utf-8").read()
version = re.search(r'^VERSION = "([^"]+)"', src, re.M).group(1)
tag = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GITHUB_REF_NAME", "")
if tag and tag.startswith("v") and tag[1:] != version:
    sys.exit(f"A tag {tag} não bate com VERSION = {version} no draftbot.py")
if not re.search(rf"^## v{re.escape(version)}\b", open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read(), re.M):
    sys.exit(f"Falta a seção '## v{version}' no CHANGELOG.md")
print(version)

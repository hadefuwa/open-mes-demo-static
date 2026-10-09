"""Build the static (GitHub Pages) demo site from the generic dummy data.

    python scripts/build_static_site.py [output_dir]      # default: ./site

It uses a throwaway database and always loads the generic pack, so it never touches your own data and the
result never contains anything but dummy data. Open site/index.html in a browser, or publish the folder
to any static host (see Docs/STATIC-DEMO.md).
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root / "site"

with tempfile.TemporaryDirectory() as tmp:
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}  # never touch a real database
    env |= {"MES_DB": str(Path(tmp) / "static.sqlite3"), "MES_DATA_PACK": "generic", "MES_REQUIRE_LOGIN": "0"}
    manage = [sys.executable, str(root / "app" / "manage.py")]
    for args in (["migrate", "-v", "0"], ["seed", "--pack", "generic"],
                 ["build_static_site", "--out", str(out), "--clean"]):
        subprocess.run(manage + args, check=True, env=env)
print(f"\nStatic site ready: {out / 'index.html'}")

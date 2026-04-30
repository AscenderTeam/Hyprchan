import sys
from pathlib import Path


SRC_PATH = Path(__file__).resolve().parents[1] / "src"
PKG_PATH = SRC_PATH / "hyprchan"

for p in (str(PKG_PATH), str(SRC_PATH)):
    if p not in sys.path:
        sys.path.insert(0, p)

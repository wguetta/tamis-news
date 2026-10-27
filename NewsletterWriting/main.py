from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
src = ROOT / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from editorial.job import main

if __name__ == "__main__":
    raise SystemExit(main())

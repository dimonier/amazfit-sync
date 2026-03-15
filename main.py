import sys
from pathlib import Path

workspace_root = Path(__file__).resolve().parent
if str(workspace_root) not in sys.path:
    sys.path.insert(0, str(workspace_root))

from amazfit_sync.pipeline import main


if __name__ == "__main__":
    raise SystemExit(main())

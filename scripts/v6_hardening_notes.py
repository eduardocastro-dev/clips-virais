"""Repository-local v6 maintenance/diagnostic entry point (no data mutation)."""
from __future__ import annotations
import json
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    needed = ['backend/redator.py','backend/evaluation.py','agents/redator/system.md',
              'agents/pessoa/system.md','frontend/app/cast-panel.tsx']
    out = {name:(root/name).is_file() for name in needed}
    print(json.dumps({'v6_modules':out,'all_present':all(out.values())},indent=2))
    return 0 if all(out.values()) else 1


if __name__=='__main__':sys.exit(main())

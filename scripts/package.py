"""Zip each skill for upload to Claude.ai (Settings > Capabilities > Skills) or the Claude API.

  python scripts/package.py                  # every skill -> dist/<name>.zip
  python scripts/package.py editatlas-sfx    # one skill

The zip holds one folder named after the skill. Test cases (evals/) and caches are left out: they are for
development, not for the agent that uses the skill.
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"evals", "__pycache__", ".pytest_cache", "node_modules"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}


def pack(folder, dist):
    out = dist / f"{folder.name}.zip"
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(folder.rglob("*")):
            rel = f.relative_to(folder)
            if f.is_dir() or SKIP_DIRS & set(rel.parts) or f.name in SKIP_FILES:
                continue
            z.write(f, Path(folder.name) / rel)
            n += 1
    print(f"{out.relative_to(ROOT).as_posix()}: {n} files, {out.stat().st_size // 1024} KB")


def main():
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    names = sys.argv[1:] or [d.name for d in sorted((ROOT / "skills").iterdir()) if (d / "SKILL.md").is_file()]
    for name in names:
        folder = ROOT / "skills" / name
        if not (folder / "SKILL.md").is_file():
            sys.exit(f"no skill at skills/{name}")
        pack(folder, dist)


if __name__ == "__main__":
    main()

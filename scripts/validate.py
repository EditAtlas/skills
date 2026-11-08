"""Check every skill in skills/ against the Agent Skills spec and the EditAtlas rules, and optionally write
skills/index.json, the public list the EditAtlas website reads to show each skill beside its library.

  python scripts/validate.py                 # check; exit 1 on any error
  python scripts/validate.py --write-index   # check, then write skills/index.json

Needs PyYAML (pip install pyyaml).
"""
import argparse
import json
import py_compile
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/EditAtlas/skills"
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
STATUSES = {"draft", "beta", "stable"}
LIBRARIES = {"techniques", "templates", "styles", "sfx"}
MCP_TOOLS = {"get_workflow", "search_techniques", "get_technique", "search_templates", "get_template",
             "get_template_bundle", "list_styles", "get_style", "search_sfx", "get_sfx", "get_skill", "none"}
REQUIRED_META = ("author", "version", "status", "library", "mcp-tools")
# Private catalog fields and personal paths must never reach this public repo.
FORBIDDEN = [
    (re.compile(r"\boriginal_name\b"), "private catalog field original_name"),
    (re.compile(r"\"pack\"\s*:"), "private catalog field pack"),
    (re.compile(r"\blicense_url\b|\breview_flag\b"), "private rights field"),
    (re.compile(r"[A-Za-z]:\\\\?Users\\\\?[A-Za-z]|/Users/[a-z]|/home/[a-z]", re.I), "a personal absolute path"),
    (re.compile(r"[\w.+-]+@(gmail|yahoo|outlook|hotmail)\.com", re.I), "a personal email address"),
]
TEXT_EXT = {".md", ".py", ".js", ".cjs", ".mjs", ".ts", ".sh", ".json", ".yaml", ".yml", ".txt", ".csv", ".html", ".css"}
BINARY_MEDIA = {".mp4", ".mov", ".webm", ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
MAX_FILE_BYTES = 5 * 1024 * 1024


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", text, re.S)
    if not m:
        return None, text
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def check_skill(folder, errors, warnings, is_template=False):
    where = folder.relative_to(ROOT).as_posix()
    md = folder / "SKILL.md"
    if not md.is_file():
        errors.append(f"{where}: no SKILL.md")
        return None
    fm, body = frontmatter(md)
    if fm is None:
        errors.append(f"{where}/SKILL.md: no YAML frontmatter between --- lines")
        return None
    name, desc = fm.get("name"), fm.get("description")
    if not isinstance(name, str) or not (1 <= len(name) <= 64) or not NAME_RE.match(name):
        errors.append(f"{where}: name {name!r} must be 1-64 chars of a-z, 0-9 and single hyphens")
    elif not is_template and name != folder.name:
        errors.append(f"{where}: name {name!r} must equal the folder name {folder.name!r}")
    elif name.startswith("editatlas"):
        errors.append(f"{where}: name {name!r} repeats the brand; the repo and marketplace already say EditAtlas. "
                      "Name the job instead (sound-design, template-builder)")
    if not isinstance(desc, str) or not (1 <= len(desc) <= 1024):
        errors.append(f"{where}: description must be 1-1024 characters (has {len(desc) if isinstance(desc, str) else 0})")
    comp = fm.get("compatibility")
    if comp is not None and (not isinstance(comp, str) or not (1 <= len(comp) <= 500)):
        errors.append(f"{where}: compatibility must be 1-500 characters")
    if "allowed-tools" in fm and not isinstance(fm["allowed-tools"], str):
        errors.append(f"{where}: allowed-tools must be a space-separated string")
    unknown = set(fm) - {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
    if unknown:
        errors.append(f"{where}: unknown frontmatter fields {sorted(unknown)}")
    meta = fm.get("metadata") or {}
    if not isinstance(meta, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in meta.items()):
        errors.append(f"{where}: metadata must map strings to strings (quote versions: version: \"0.1.0\")")
        meta = {}
    for k in REQUIRED_META:
        if k not in meta:
            errors.append(f"{where}: metadata.{k} is missing")
    if not is_template:
        if meta.get("status") and meta["status"] not in STATUSES:
            errors.append(f"{where}: metadata.status must be one of {sorted(STATUSES)}")
        if meta.get("version") and not re.match(r"^\d+\.\d+\.\d+$", meta["version"]):
            errors.append(f"{where}: metadata.version must look like 1.2.3")
        libs = set((meta.get("library") or "").split())
        if libs - LIBRARIES:
            errors.append(f"{where}: unknown library {sorted(libs - LIBRARIES)}")
        tools = set((meta.get("mcp-tools") or "").split())
        if tools - MCP_TOOLS:
            errors.append(f"{where}: unknown mcp-tools {sorted(tools - MCP_TOOLS)}")
        if "license" not in fm and not any((folder / n).is_file() for n in ("LICENSE", "LICENSE.txt", "LICENSE.md")):
            warnings.append(f"{where}: no license field and no LICENSE file")
    lines = body.count("\n")
    if lines > 500:
        warnings.append(f"{where}/SKILL.md: body has {lines} lines; move detail into references/")
    for ref in re.findall(r"`((?:references|scripts|assets)/[^`\s]+)`", body):
        if not is_template and not (folder / ref).exists():
            errors.append(f"{where}/SKILL.md: mentions {ref}, which does not exist")
    for f in folder.rglob("*"):
        if not f.is_file() or "__pycache__" in f.parts:
            continue
        rel = f.relative_to(ROOT).as_posix()
        if f.stat().st_size > MAX_FILE_BYTES:
            errors.append(f"{rel}: {f.stat().st_size // 1024} KB is over the 5 MB limit")
        if f.suffix.lower() in BINARY_MEDIA:
            errors.append(f"{rel}: media files do not belong here; download them in place-files.sh or link to the site")
        if f.suffix.lower() in TEXT_EXT:
            text = f.read_text(encoding="utf-8", errors="replace")
            for rx, why in FORBIDDEN:
                if rx.search(text):
                    errors.append(f"{rel}: contains {why}")
        if f.suffix == ".py":
            try:
                py_compile.compile(str(f), doraise=True, cfile=str(ROOT / ".pyc_check"))
            except py_compile.PyCompileError as e:
                errors.append(f"{rel}: does not compile: {e.msg.strip()[:200]}")
    evals = folder / "evals"
    if evals.is_dir():
        for case in sorted(p for p in evals.iterdir() if p.is_dir()):
            for need in ("prompt.md", "case.yaml"):
                if not (case / need).is_file():
                    errors.append(f"{case.relative_to(ROOT).as_posix()}: no {need}")
            if not list((case / "graders").glob("*.md")):
                errors.append(f"{case.relative_to(ROOT).as_posix()}: no graders/*.md")
    elif not is_template:
        warnings.append(f"{where}: no evals/ test cases")
    return {"name": name, "description": desc, "meta": meta, "compatibility": comp, "license": fm.get("license"),
            "path": where, "evals": len([p for p in evals.iterdir() if p.is_dir()]) if evals.is_dir() else 0}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--write-index", action="store_true")
    a = p.parse_args()
    errors, warnings, skills = [], [], []
    for folder in sorted(d for d in (ROOT / "skills").iterdir() if d.is_dir()):
        s = check_skill(folder, errors, warnings)
        if s:
            skills.append(s)
    check_skill(ROOT / "template", errors, warnings, is_template=True)
    (ROOT / ".pyc_check").unlink(missing_ok=True)

    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    listed = {}
    for plugin in market.get("plugins", []):
        for path in plugin.get("skills", []):
            listed[Path(path).name] = plugin["name"]
            if not (ROOT / path / "SKILL.md").is_file():
                errors.append(f"marketplace.json: plugin {plugin['name']} lists {path}, which has no SKILL.md")
    for s in skills:
        if s["name"] not in listed:
            errors.append(f"marketplace.json: skill {s['name']} is in no plugin")

    # The README table is written by hand; its status column must follow each SKILL.md.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for s in skills:
        row = re.search(rf"^\|\s*\[{re.escape(s['name'])}\]\(.*\|\s*(\w+)\s*\|\s*$", readme, re.M)
        if not row:
            errors.append(f"README.md: skill {s['name']} has no row in the skills table")
        elif row.group(1) != s["meta"].get("status"):
            errors.append(f"README.md: {s['name']} is {row.group(1)} in the table but "
                          f"{s['meta'].get('status')} in SKILL.md")

    for w in warnings:
        print("warning:", w)
    for e in errors:
        print("error:  ", e)
    print(f"{len(skills)} skill(s), {len(errors)} error(s), {len(warnings)} warning(s)")
    if errors:
        sys.exit(1)
    if a.write_index:
        index = {
            "repo": REPO_URL,
            "marketplace": market["name"],
            "skills": [{
                "name": s["name"],
                "description": s["description"],
                "version": s["meta"].get("version"),
                "status": s["meta"].get("status"),
                "libraries": (s["meta"].get("library") or "").split(),
                "mcp_tools": [t for t in (s["meta"].get("mcp-tools") or "").split() if t != "none"],
                "compatibility": s["compatibility"],
                "license": s["license"],
                "path": s["path"],
                "url": f"{REPO_URL}/tree/main/{s['path']}",
                "plugin": listed.get(s["name"]),
                "install_claude_code": f"/plugin install {listed.get(s['name'])}@{market['name']}",
                "download_zip": f"{REPO_URL}/releases/latest/download/{s['name']}.zip",
                "eval_cases": s["evals"],
            } for s in skills],
        }
        out = ROOT / "skills" / "index.json"
        out.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("->", out.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()

"""Tells EditAtlas that a skill's main script ran: four things and nothing else.

    {"skill": "sound-design", "version": "0.4.2", "result": "ok", "seconds": 37}

The skill's name and version come from the SKILL.md next to this folder. result is "ok" when the script ends
normally or exits with code 0, "error" when it raises or exits with another code; a script stopped with Ctrl+C sends
nothing. No ID, no path, no file name, no text, no media, no system details. EditAtlas keeps only daily totals per
skill, version and result (https://edit.trysometh.ing/privacy).

Off when EDITATLAS_TELEMETRY is 0, false, off or no, and when CI is set (GitHub Actions and other CI). The send runs
in a daemon thread that the script waits on for at most 2 seconds; any error is ignored, so the skill never fails or
hangs because of it, even when a name lookup hangs. Prints nothing.

Use in a skill's main script, in place of a bare main(), with the script's folder on sys.path so it loads under
python -I too; if the helper cannot be imported, the script runs exactly as before:

    sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under python -I
    ...
    if __name__ == "__main__":
        try:
            from editatlas_signal import run
        except ImportError:
            run = None
        if run is None:  # outside the except, so an error in main() is not shown as part of the ImportError
            main()
        else:
            run(main)

Every skill keeps an identical copy in its scripts/ folder; scripts/validate.py checks they match this one.
"""
import json
import os
import re
import sys
import threading
import time
import urllib.request
from pathlib import Path

ENDPOINT = "https://edit.trysometh.ing/api/v1/skill-runs"
WAIT_SECONDS = 2.0
OFF = {"0", "false", "off", "no"}


def enabled(environ=None):
    environ = os.environ if environ is None else environ
    if environ.get("EDITATLAS_TELEMETRY", "").strip().lower() in OFF:
        return False
    ci = environ.get("CI", "").strip().lower()
    return ci in ("", "0", "false")


def skill_of(skill_md=None):
    """(name, version) from the SKILL.md frontmatter, or None when it cannot be read."""
    path = Path(skill_md) if skill_md else Path(__file__).resolve().parent.parent / "SKILL.md"
    try:
        head = path.read_text(encoding="utf-8").split("\n---", 1)[0]
    except (OSError, UnicodeDecodeError):
        return None
    name = re.search(r"^name:\s*['\"]?([a-z0-9-]{1,64})['\"]?\s*$", head, re.M)
    version = re.search(r"^\s+version:\s*['\"]?(\d{1,3}\.\d{1,3}\.\d{1,3})['\"]?\s*$", head, re.M)
    return (name.group(1), version.group(1) if version else "other") if name else None


def _post(body, url):
    try:
        request = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": "application/json", "User-Agent": "editatlas-skill"})
        with urllib.request.urlopen(request, timeout=WAIT_SECONDS) as answer:
            answer.read(0)
    except Exception:
        pass


def send(result, seconds, skill=None, url=None, wait=WAIT_SECONDS):
    """Sends one run in the background and waits for it at most `wait` seconds. False when nothing was sent."""
    try:
        if not enabled() or result not in ("ok", "error"):
            return False
        skill = skill or skill_of()
        if not skill:
            return False
        body = json.dumps({"skill": skill[0], "version": skill[1], "result": result,
                           "seconds": int(round(min(max(seconds, 0), 86400)))}).encode("utf-8")
        thread = threading.Thread(target=_post, args=(body, url or ENDPOINT), daemon=True)
        thread.start()
        thread.join(wait)
        return True
    except Exception:
        return False


def run(main, skill=None, url=None):
    """Runs main() and sends how it ended. The script then ends as main() made it: its exception or exit code.
    Asking a script for its help (-h, --help) is not a run, and sends nothing."""
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        return main()
    started, result = time.monotonic(), "error"
    try:
        value = main()
        result = "ok"
        return value
    except SystemExit as stop:
        result = "ok" if stop.code in (0, None) else "error"
        raise
    except KeyboardInterrupt:
        result = None
        raise
    finally:
        if result:
            send(result, time.monotonic() - started, skill=skill, url=url)

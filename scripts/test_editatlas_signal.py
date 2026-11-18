"""Tests for scripts/editatlas_signal.py, the run signal every skill's main script sends. Standard library only.

  python scripts/test_editatlas_signal.py

Each case runs a small script in a child Python, the way a skill runs, against a stand-in server on 127.0.0.1, and
checks what arrived, the exit code, the output and how long it took. Nothing reaches edit.trysometh.ing.
"""
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "scripts" / "editatlas_signal.py"
sys.path.insert(0, str(ROOT / "scripts"))
import editatlas_signal  # noqa: E402

SKILL_MD = """---
name: demo-skill
description: A skill for the tests.
metadata:
  author: EditAtlas
  version: "1.2.3"
  status: beta
---
# demo-skill
"""


class Server:
    """Keeps every body POSTed to it. hang=True accepts and never answers."""

    def __init__(self, hang=False):
        self.bodies, self.hang = [], hang
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_CONNECT(self):
                # Used as an HTTPS proxy: note where the request was going, and open no tunnel.
                outer.bodies.append({"connect": self.path})
                self.send_response(502)
                self.end_headers()

            def do_POST(self):
                if outer.hang:
                    time.sleep(30)
                    return
                length = int(self.headers.get("Content-Length") or 0)
                outer.bodies.append({"body": json.loads(self.rfile.read(length)), "path": self.path,
                                     "agent": self.headers.get("User-Agent"), "query": "?" in self.path})
                self.send_response(204)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/api/v1/skill-runs"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def skill_folder():
    folder = Path(tempfile.mkdtemp(prefix="signal-test-"))
    (folder / "scripts").mkdir()
    (folder / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    shutil.copy(HELPER, folder / "scripts" / "editatlas_signal.py")
    return folder


def run_script(body, url, env=None, prelude="", args=()):
    """Runs a main script whose main() is `body`, through run(main, url=url). Gives (exit code, output, seconds)."""
    folder = skill_folder()
    script = folder / "scripts" / "main.py"
    script.write_text(f"""import sys, time, socket
{prelude}
def main():
{body}
if __name__ == "__main__":
    from editatlas_signal import run
    run(main, url={url!r})
""", encoding="utf-8")
    clean = {k: v for k, v in os.environ.items() if k not in ("CI", "EDITATLAS_TELEMETRY")}
    started = time.monotonic()
    done = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, env={**clean, **(env or {})}, timeout=60)
    seconds = time.monotonic() - started
    shutil.rmtree(folder, ignore_errors=True)
    return done.returncode, done.stdout + done.stderr, seconds


def results(server):
    return [b["body"]["result"] for b in server.bodies]


def test_how_a_script_ends_is_its_result():
    server = Server()
    try:
        cases = [
            ('    print("working")', 0, "ok"),
            ("    return None", 0, "ok"),
            ("    sys.exit(0)", 0, "ok"),
            ("    sys.exit()", 0, "ok"),
            ("    sys.exit(1)", 1, "error"),
            ('    sys.exit("demo-skill: the file is missing")', 1, "error"),
            ('    raise ValueError("broken")', 1, "error"),
            ("    raise KeyboardInterrupt", None, None),
        ]
        for body, code, result in cases:
            before = len(server.bodies)
            returncode, output, _ = run_script(body, server.url)
            if code is not None:
                assert returncode == code, (body, returncode, output)
            else:
                assert returncode != 0, (body, returncode)
            sent = results(server)[before:]
            assert sent == ([result] if result else []), (body, sent)
        assert "working" in run_script('    print("working")', server.url)[1]
        assert "ValueError: broken" in run_script('    raise ValueError("broken")', server.url)[1], "the traceback is kept"
    finally:
        server.close()


def test_exactly_four_fields_and_nothing_printed():
    server = Server()
    try:
        returncode, output, _ = run_script("    time.sleep(1.2)", server.url)
        assert returncode == 0 and output == "", repr(output)
        (sent,) = server.bodies
        assert sent["body"] == {"skill": "demo-skill", "version": "1.2.3", "result": "ok", "seconds": 1}, sent
        assert not sent["query"] and sent["agent"] == "editatlas-skill", sent
    finally:
        server.close()


def test_turned_off_by_the_variable_and_under_ci():
    server = Server()
    try:
        for env in ({"EDITATLAS_TELEMETRY": "0"}, {"EDITATLAS_TELEMETRY": "false"}, {"EDITATLAS_TELEMETRY": "OFF"},
                    {"EDITATLAS_TELEMETRY": " no "}, {"CI": "true"}, {"CI": "1"}):
            run_script("    return 0", server.url, env)
            run_script("    raise ValueError", server.url, env)
        assert server.bodies == [], server.bodies
        run_script("    return 0", server.url, {"EDITATLAS_TELEMETRY": "1", "CI": "false"})
        assert results(server) == ["ok"]
    finally:
        server.close()
    assert editatlas_signal.enabled({}) and not editatlas_signal.enabled({"CI": "true"})


def test_a_server_that_is_down_or_hangs_never_holds_the_script():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed = f"http://127.0.0.1:{probe.getsockname()[1]}/api/v1/skill-runs"
    returncode, output, seconds = run_script("    return 0", closed)
    assert returncode == 0 and output == "" and seconds < 5, (returncode, output, seconds)
    hanging = Server(hang=True)
    try:
        returncode, output, seconds = run_script('    print("done")', hanging.url)
        assert returncode == 0 and output.strip() == "done", (returncode, output)
        assert seconds < 3.5, f"waited {seconds:.1f} s on a server that never answers"
    finally:
        hanging.close()


def test_a_name_lookup_that_hangs_never_holds_the_script():
    # urllib's timeout does not cover the DNS lookup; the daemon thread and the 2-second wait do.
    slow_dns = "import socket, time\n_real = socket.getaddrinfo\nsocket.getaddrinfo = lambda *a, **k: (time.sleep(30), _real(*a, **k))[1]"
    for body, code in (('    print("done")', 0), ("    sys.exit(3)", 3)):
        returncode, output, seconds = run_script(body, "https://dns-hangs.example/api/v1/skill-runs", prelude=slow_dns)
        assert returncode == code, (returncode, output)
        assert seconds < 3.5, f"waited {seconds:.1f} s on a name lookup that hangs"
        assert "Traceback" not in output, output


def test_the_name_and_version_come_from_each_skills_own_skill_md():
    for md in sorted((ROOT / "skills").glob("*/SKILL.md")):
        text = md.read_text(encoding="utf-8")
        name, version = editatlas_signal.skill_of(md)
        assert f"name: {name}\n" in text.replace("\r\n", "\n"), md
        assert f'version: "{version}"' in text, (md, version)
        assert f"This is {name} {version}." in text, (md, "the version line under the title")
    folder = skill_folder()
    try:
        (folder / "SKILL.md").write_text(SKILL_MD.replace('version: "1.2.3"', "version: soon"), encoding="utf-8")
        assert editatlas_signal.skill_of(folder / "SKILL.md") == ("demo-skill", "other")
        assert editatlas_signal.skill_of(folder / "missing.md") is None
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_asking_for_help_is_not_a_run():
    server = Server()
    try:
        for flag in ("--help", "-h"):
            returncode, _, _ = run_script("    return 0", server.url, args=(flag,))
            assert returncode == 0
        assert server.bodies == [], server.bodies
        run_script("    return 0", server.url, args=("input.mp4",))
        assert results(server) == ["ok"]
    finally:
        server.close()


def proxied_env(proxy, **extra):
    """The environment with every HTTP(S) request sent through `proxy`, which keeps a note of it and opens nothing."""
    drop = {"CI", "EDITATLAS_TELEMETRY", "NO_PROXY", "no_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"}
    env = {k: v for k, v in os.environ.items() if k not in drop}
    address = proxy.url.split("/api/")[0]
    return {**env, "HTTPS_PROXY": address, "HTTP_PROXY": address, **extra}


def test_main_scripts_run_under_isolated_python_and_send_nothing_for_help():
    # python -I leaves the script's folder off sys.path. Each main script puts it back and imports the helper inside
    # try/except ImportError, so a skill never fails because of the signal (owner, 2026-11-18).
    import importlib.util
    from_main = dict(_main_scripts())
    proxy = Server()
    try:
        # The check is real: the same isolated Python, sending a run, is caught by the proxy.
        folder = skill_folder()
        probe = folder / "scripts" / "probe.py"
        probe.write_text("import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parent))\n"
                         "from editatlas_signal import run\nrun(lambda: None)\n", encoding="utf-8")
        assert subprocess.run([sys.executable, "-I", str(probe)], env=proxied_env(proxy), timeout=60).returncode == 0
        shutil.rmtree(folder, ignore_errors=True)
        assert proxy.bodies == [{"connect": "edit.trysometh.ing:443"}], proxy.bodies
        proxy.bodies.clear()
        skipped = []
        for skill, script in sorted(from_main.items()):
            path = ROOT / "skills" / skill / "scripts" / script
            source = "".join(f.read_text(encoding="utf-8") for f in path.parent.glob("*.py"))  # its own modules too
            missing = [m for m, needle in (("numpy", "import numpy"), ("PIL", "from PIL")) if needle in source and not importlib.util.find_spec(m)]
            if missing:
                skipped.append(f"{skill} ({', '.join(missing)} not installed)")
                continue
            for extra in ({}, {"EDITATLAS_TELEMETRY": "0"}):
                done = subprocess.run([sys.executable, "-I", str(path), "--help"], capture_output=True, encoding="utf-8", errors="replace", env=proxied_env(proxy, **extra), timeout=120)
                assert done.returncode == 0, (skill, extra, done.stderr[-400:])
                assert "usage:" in done.stdout.lower(), (skill, done.stdout[:200])
        assert proxy.bodies == [], proxy.bodies
        if skipped:
            print("  skipped:", "; ".join(skipped))
    finally:
        proxy.close()


def test_a_skill_without_the_helper_runs_as_before():
    # A copy of a skill made by hand may lack editatlas_signal.py; its main script must still run, help and errors alike.
    folder = Path(tempfile.mkdtemp(prefix="no-helper-"))
    try:
        shutil.copytree(ROOT / "skills" / "editable-export", folder / "editable-export", ignore=shutil.ignore_patterns("__pycache__", "editatlas_signal.py"))
        script = folder / "editable-export" / "scripts" / "package.py"
        env = {k: v for k, v in os.environ.items() if k not in ("CI", "EDITATLAS_TELEMETRY")}
        for isolated in ([], ["-I"]):
            done = subprocess.run([sys.executable, *isolated, str(script), "build", "--help"], capture_output=True, encoding="utf-8", errors="replace", env=env, timeout=60)
            assert done.returncode == 0 and "usage:" in done.stdout, (isolated, done.stderr[-300:])
            done = subprocess.run([sys.executable, *isolated, str(script), "build", str(folder / "missing.json"), "--out", str(folder / "out.edit")],
                                  capture_output=True, encoding="utf-8", errors="replace", env=env, timeout=60)
            # The script's own error, as before (package.py raises on a missing file), and nothing about the helper.
            assert done.returncode != 0 and "missing.json" in done.stderr, (isolated, done.stderr[-300:])
            assert "editatlas_signal" not in done.stderr and "ImportError" not in done.stderr, done.stderr[-300:]
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _main_scripts():
    # Read from validate.py without importing it, which needs PyYAML; these tests need nothing outside the standard library.
    import ast
    tree = ast.parse((ROOT / "scripts" / "validate.py").read_text(encoding="utf-8"))
    return next(ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "MAIN_SCRIPTS")


def test_every_skill_has_this_helper_and_its_main_script_uses_it():
    MAIN_SCRIPTS = _main_scripts()
    helper = HELPER.read_bytes().replace(b"\r\n", b"\n")
    skills = sorted(p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md"))
    assert sorted(MAIN_SCRIPTS) == skills, (sorted(MAIN_SCRIPTS), skills)
    for skill, script in MAIN_SCRIPTS.items():
        copy = ROOT / "skills" / skill / "scripts" / "editatlas_signal.py"
        assert copy.read_bytes().replace(b"\r\n", b"\n") == helper, copy
        source = (ROOT / "skills" / skill / "scripts" / script).read_text(encoding="utf-8")
        assert "from editatlas_signal import run" in source and "except ImportError:" in source, script


if __name__ == "__main__":
    print(f"Python {sys.version.split()[0]}")
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print("ok", test.__name__)
    print(f"{len(tests)} checks passed")

"""Scaffold for continue-from-link: Claude's package goes on a real studio link (version 1), then a person opens it,
makes the title bigger and the click later, and presses Continue with Claude (version 2). Writes message.txt, the
message the studio gives the person to paste back. EDITATLAS_INTERNAL, when set, keeps these calls out of EditAtlas's
numbers."""
import json, os, subprocess, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

SCRIPTS = Path(sys.argv[1])
SITE = os.environ.get("EDITATLAS_SITE", "https://edit.trysometh.ing")
run = lambda *a: subprocess.run([sys.executable, *map(str, a)], check=True, capture_output=True, text=True, encoding="utf-8").stdout
run(SCRIPTS / "package.py", "build", "work/project.json", "--out", "tweak.edit")
out = run(SCRIPTS / "share.py", "send", "tweak.edit", "--site", SITE, "--name", "Claude")
link = out.strip().splitlines()[-1].split("-> ")[-1]
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context()
    if os.environ.get("EDITATLAS_INTERNAL"):
        ctx.add_init_script("localStorage.setItem('editatlas-internal', " + json.dumps(os.environ["EDITATLAS_INTERNAL"]) + ")")
    pg = ctx.new_page()
    pg.goto(link)
    pg.wait_for_function("() => window.EA && window.EA.ready", timeout=120000)
    pg.evaluate("() => { snapshot(); P.styles.hook.size = 96; const c = P.tracks.find(t => t.kind === 'audio').items[0]; c.at = r3(c.at + 0.1); changed(); }")
    pg.locator("#share").click()
    pg.locator("#s-note").fill("title bigger, click a little later")
    pg.locator("#s-go").click()
    pg.wait_for_selector("#s-agent", timeout=120000)
    Path("message.txt").write_text(pg.locator("#s-agent").input_value(), encoding="utf-8")
    b.close()

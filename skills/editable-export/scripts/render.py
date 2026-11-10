"""Render a package's video with the EditAtlas studio, so what the person sees there is what you deliver.

  render.py result/my-video.edit                      # -> result/my-video.edit/<title>.mp4
  render.py result/my-video.edit --out result/final.mp4

Opens the studio page in Chrome or Edge without a window (Playwright), gives it the package from this machine,
runs its Export and saves the MP4. The page is loaded from the site; the project and its files are read by the
browser here and are not sent anywhere. Needs `pip install playwright`, Chrome or Edge installed (or
`python -m playwright install chromium`) and network access to the site. Prints frames, seconds taken and size;
then measure the file with ffprobe before you hand it over.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SITE = "https://edit.trysometh.ing"


def die(msg):
    sys.exit("editable-export: " + msg)


EXPORT_JS = """async (rate) => {
  await window.EA.ready;
  if (rate) window.EA_EXPORT_RATE = rate;
  const missing = missingFiles();
  if (missing.length) return {missing};
  const r = await window.EA.exportMp4(() => {});
  const a = document.createElement('a'); a.href = URL.createObjectURL(r.blob); a.download = 'export.mp4';
  document.body.appendChild(a); a.click();
  return {frames: r.frames, seconds: r.seconds, size: r.blob.size, peak: r.peak, stats: r.stats};
}"""


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("package", help="the package folder (with project.json and media/)")
    ap.add_argument("--out")
    ap.add_argument("--site", default=SITE, help="where the studio is (default: %(default)s)")
    ap.add_argument("--browser", default="auto", help="chrome, msedge, chromium or auto")
    ap.add_argument("--timeout", type=float, default=1800, help="seconds")
    ap.add_argument("--rate", type=float, help="playback speed while reading frames (default 1.5)")
    a = ap.parse_args()
    pkg = Path(a.package).resolve()
    pj = pkg / "project.json"
    if not pj.is_file():
        die(f"no project.json in {pkg}; run package.py build first")
    proj = json.loads(pj.read_text(encoding="utf-8"))
    files = [pj] + [pkg / m["path"] for m in proj.get("media", {}).values()]
    gone = [str(f) for f in files if not f.is_file()]
    if gone:
        die("missing from the package: " + ", ".join(gone) + "; run package.py build again")
    out = Path(a.out) if a.out else pkg / (((proj.get("title") or pkg.stem).strip().replace(" ", "-").lower() or "video") + ".mp4")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        die(f"Playwright is not installed: pip install playwright. Or open {a.site}/studio in Chrome, choose the "
            "package folder and press Export MP4.")
    errors = []
    t0 = time.time()
    with sync_playwright() as p:
        browser = None
        for ch in ([a.browser] if a.browser != "auto" else ["chrome", "msedge", "chromium"]):
            try:
                kw = {} if ch == "chromium" else {"channel": ch}
                browser = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required"], **kw)
                break
            except Exception as e:                       # that browser is not installed
                errors.append(f"{ch}: {str(e).splitlines()[0]}")
        if not browser:
            die("no Chrome, Edge or Playwright Chromium found (" + "; ".join(errors) + ")")
        ctx = browser.new_context(accept_downloads=True, viewport={"width": 1400, "height": 900})
        pg = ctx.new_page()
        logs = []
        pg.on("pageerror", lambda e: logs.append("page error: " + str(e)))
        pg.on("console", lambda m: logs.append(f"console {m.type}: {m.text}") if m.type == "error" else None)
        try:
            r = pg.goto(a.site.rstrip("/") + "/studio", timeout=60000)
        except Exception as e:
            die(f"could not open {a.site}/studio: {str(e).splitlines()[0]}")
        if not r or not r.ok:
            die(f"{a.site}/studio answered {r.status if r else 'nothing'}")
        pg.locator("#open-fileinput").set_input_files([str(f) for f in files])
        try:
            pg.wait_for_function("() => window.EA && window.EA.ready", timeout=60000)
        except Exception:
            die("the studio did not open the package: " + (pg.locator("#open-msg").inner_text() or "; ".join(logs) or "no message"))
        with pg.expect_download(timeout=a.timeout * 1000) as dl:
            info = pg.evaluate(EXPORT_JS, a.rate)
            if info.get("missing"):
                die("the studio could not match these media ids to files: " + ", ".join(info["missing"])
                    + ". Two files in media/ may share a name; run package.py build again.")
        out.parent.mkdir(parents=True, exist_ok=True)
        dl.value.save_as(str(out))
        print(f"{browser.version}: {info['frames']} frames in {info['seconds']:.1f} s "
              f"({info['frames'] / max(info['seconds'], 1e-3):.1f} frames/s), {info['size'] / 1e6:.2f} MB"
              f" (frames read while playing: {info['stats']['played']}, by seeking: {info['stats']['sought']})"
              + (f"; sound peaked at {info['peak']:.2f} and was turned down to 0.98" if info["peak"] > 0.98 else ""))
        for line in logs:
            print(line)
        browser.close()
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height,r_frame_rate,nb_frames"
                        ":format=duration", "-of", "compact", str(out)], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    print("->", out, f"({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()

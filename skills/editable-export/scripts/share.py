"""Pass a package back and forth with the person through one EditAtlas studio link.

  share.py send result/my-video.edit                        # a new link: version 1, printed for the person
  share.py pull result/my-video.edit                        # their newest version, into the same folder
  share.py push result/my-video.edit --note "what I did"    # your next version, on the same link
  share.py versions result/my-video.edit                    # who saved which version, and their notes
  share.py pull "https://edit.trysometh.ing/studio#ID.KEY" --out result/my-video.edit   # a link you were given
  share.py send result/my-video.edit --site http://127.0.0.1:8799                     # a local studio

A link holds every version of one project. The person opens it, changes things and presses Save; you pull
that version, keep working from it, and push the next one; their open studio tells them it is there. Nothing
already saved changes: each save adds a version, and only files that are new are sent.

Everything is encrypted on this machine (AES-256-GCM, a random key made by `send`) before it is sent: project.json
and every file it uses, the footage as you processed it included. The key is only in the link, after the #, which
browsers never send to a server, so EditAtlas stores bytes it cannot read. The link and all its versions stop
working 30 days after `send` and the files are deleted. Anyone who has the link can open and add versions, so give
it only to the person.

`send` and `pull` write the link and the version you have into PACKAGE/.studio-link. It holds the key: do not put
it in a repository or a message. `push` refuses when the person saved a newer version than the one you started
from; pull it first and make your change again on top of it (or --force to replace their work with yours).

Needs `pip install cryptography`. A link holds up to 300 MB with all its versions; if the package is larger, make
the footage smaller first (the message says how) or hand over the folder instead.

The format, also read and written by the studio page:
  object = 12-byte nonce + ciphertext + 16-byte tag, with "editatlas-share/1|<share id>|<object name>" as
           additional data;
  version n = object "v<n>" = {format, made, version, parent, by: "studio" | "agent", name (the agent's), note, project,
              files: {<media id>: {objects: [names], bytes, type, sha256}}};
  files are cut into 8 MiB pieces, one object each, named f<version>x<file>.<piece>; a file that did not change
  keeps the objects of the version that sent it;
  write token = HKDF-SHA256(key, no salt, info "editatlas-share/1 write"), 32 bytes, base64url, sent as a Bearer
  token; the server keeps its hash and accepts v<n> only when n is one more than the latest version.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

FORMAT, PROJECT = "editatlas-share/1", "editatlas-project/1"
PIECE, OVERHEAD, LIMIT = 8 * 1024 * 1024, 28, 300 * 1024 * 1024
SITE = "https://edit.trysometh.ing"
AGENT = "editatlas-skills/editable-export"
STATE = ".studio-link"
LINK = re.compile(r"(https?://[^/#\s]+)/studio#([A-Za-z0-9_-]{22})\.([A-Za-z0-9_-]{43})(?:\.([1-9][0-9]{0,4}))?")
OBJECT = re.compile(r"[a-z0-9][a-z0-9.]{0,31}")
TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".m4v": "video/mp4",
         ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".flac": "audio/flac",
         ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
         ".svg": "image/svg+xml", ".ttf": "font/ttf", ".otf": "font/otf", ".woff": "font/woff", ".woff2": "font/woff2"}
BY = {"studio": "the person, in the studio", "agent": "an agent"}


def who(m):
    return m.get("name") or BY.get(m.get("by"), "someone") if m.get("by") == "agent" else BY.get(m.get("by"), "someone")


def die(msg):
    sys.exit("editable-export: " + msg)


def b64u(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def call(method, url, body=None, headers=None, tries=3):
    """One request; a refusal (4xx) is final, a dropped connection or a busy server is tried again."""
    head = {"User-Agent": AGENT, **(headers or {})}
    internal = os.environ.get("EDITATLAS_INTERNAL")          # EditAtlas's own checks: kept out of its numbers
    if internal:
        head["X-EditAtlas-Internal"] = internal
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=body, method=method, headers=head), timeout=120) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            text = e.read()
            if e.code < 500 or attempt == tries:
                try:
                    text = json.loads(text)["error"]
                except Exception:
                    text = text.decode("utf-8", "replace")[:300]
                return e.code, text
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == tries:
                die(f"could not reach {url.split('/api/')[0]}: {getattr(e, 'reason', e)}")
        time.sleep(0.8 * attempt)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class Link:
    """One studio link: its site, id and key, and the calls that read and add versions."""

    def __init__(self, site, sid, key):
        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        except ImportError:
            die("the cryptography package is not installed: pip install cryptography. Or give the person the folder: "
                "they open it at " + site + "/studio with Choose the folder.")
        self.site, self.sid, self.key = site.rstrip("/"), sid, key
        self.api = self.site + "/api/v1/studio/shares"
        self.aes = AESGCM(key) if key else None
        self.write = b64u(HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=f"{FORMAT} write".encode()).derive(key)) if key else None

    @classmethod
    def parse(cls, text):
        m = LINK.fullmatch(text.strip())
        if not m:
            die("that is not a whole studio link: it looks like https://edit.trysometh.ing/studio#<id>.<key>")
        return cls(m.group(1), m.group(2), base64.urlsafe_b64decode(m.group(3) + "=")), (int(m.group(4)) if m.group(4) else None)

    @property
    def url(self):
        return f"{self.site}/studio#{self.sid}.{b64u(self.key)}"

    def seal(self, name, data):
        nonce = os.urandom(12)
        return nonce + self.aes.encrypt(nonce, data, f"{FORMAT}|{self.sid}|{name}".encode("utf-8"))

    def fetch(self, name):
        if not OBJECT.fullmatch(name):
            die("the link names an object this script will not fetch")
        code, body = call("GET", f"{self.api}/{self.sid}/objects/{name}")
        if code == 404:
            die("this link has expired or does not exist (links stop working 30 days after they are made)")
        if code != 200:
            die(f"the studio answered {code} for {name}: {body}")
        try:
            return self.aes.decrypt(body[:12], body[12:], f"{FORMAT}|{self.sid}|{name}".encode("utf-8"))
        except Exception:
            die("the key in this link does not open it; ask for the whole link again, with the part after the #")

    def latest(self):
        code, body = call("GET", f"{self.api}/{self.sid}")
        if code == 404:
            die("this link has expired or does not exist (links stop working 30 days after they are made)")
        if code != 200:
            die(f"the studio answered {code}: {body}")
        return json.loads(body)

    def version(self, n):
        m = json.loads(self.fetch(f"v{n}"))
        if m.get("format") != FORMAT or (m.get("project") or {}).get("format") != PROJECT:
            die("this link holds something this script cannot read")
        return m

    def put(self, name, data):
        code, body = call("PUT", f"{self.api}/{self.sid}/objects/{name}", self.seal(name, data),
                          {"Authorization": "Bearer " + self.write, "Content-Type": "application/octet-stream"})
        if code == 409 and name.startswith("v"):
            return code, body
        if code not in (201, 409):                 # 409 for a piece: stored by a try whose answer was lost
            raise RuntimeError(f"{name}: {code} {body}")
        return code, body


# ------------------------------------------------------------------ what changed, in words
def summary(a, b):
    """Lines that say what changed from project a to project b, by element id."""
    out = []

    def val(v):
        if isinstance(v, float):
            return f"{v:.3f}".rstrip("0").rstrip(".")
        if isinstance(v, str):
            return json.dumps(v if len(v) <= 48 else v[:48] + "…", ensure_ascii=False)
        return "none" if v is None else json.dumps(v, ensure_ascii=False)[:60]

    def label(kind, it):
        if kind == "text":
            return f"text {val(it.get('text', ''))} ({it['id']})"
        if kind == "audio":
            return f"sound {it.get('label') or it.get('media')} ({it['id']})"
        if kind == "video":
            return f"clip {it['id']}"
        return f"graphic {it.get('media')} ({it['id']})"

    sa, sb = a.get("styles") or {}, b.get("styles") or {}
    for k in dict.fromkeys([*sa, *sb]):
        if k not in sa:
            out.append(f"style {k}: added")
        elif k not in sb:
            out.append(f"style {k}: removed")
        else:
            for f in dict.fromkeys([*sa[k], *sb[k]]):
                if sa[k].get(f) != sb[k].get(f):
                    out.append(f"style {k} (every element that uses it): {f} {val(sa[k].get(f))} -> {val(sb[k].get(f))}")
    ta = {t["id"]: t for t in a.get("tracks", [])}
    for tb in b.get("tracks", []):
        t0 = ta.get(tb["id"])
        name = tb.get("name") or tb["id"]
        if not t0:
            out.append(f"track {name}: added")
            continue
        for flag, on, off in (("hidden", "hidden", "shown"), ("muted", "muted", "unmuted")):
            if bool(t0.get(flag)) != bool(tb.get(flag)):
                out.append(f"track {name}: {on if tb.get(flag) else off}")
        ia = {x["id"]: x for x in t0.get("clips") or t0.get("items") or []}
        ib = {x["id"]: x for x in tb.get("clips") or tb.get("items") or []}
        for i, it in ia.items():
            if i not in ib:
                out.append(f"{label(tb['kind'], it)}: removed")
        for i, it in ib.items():
            was = ia.get(i)
            if not was:
                out.append(f"{label(tb['kind'], it)}: added")
                continue
            for f in dict.fromkeys([*was, *it]):
                if was.get(f) != it.get(f):
                    out.append(f"{label(tb['kind'], was)}: word timings" if f == "words" else
                               f"{label(tb['kind'], was)}: {f} {val(was.get(f))} -> {val(it.get(f))}")
    for i, t0 in ta.items():
        if i not in {t["id"] for t in b.get("tracks", [])}:
            out.append(f"track {t0.get('name') or i}: removed")
    return out


# ------------------------------------------------------------------ the package and its link
def read_package(pkg):
    pj = pkg / "project.json"
    if not pj.is_file():
        die(f"no project.json in {pkg}; run package.py build first")
    project = json.loads(pj.read_text(encoding="utf-8"))
    if project.get("format") != PROJECT:
        die(f"{pj} is not an {PROJECT} file")
    return project


def read_state(pkg):
    f = pkg / STATE
    if not f.is_file():
        die(f"{pkg} has no studio link yet: run share.py send {pkg} first, or pull a link into it")
    st = json.loads(f.read_text(encoding="utf-8"))
    link, _ = Link.parse(st["link"])
    return link, st


def write_state(pkg, link, version, files, project):
    (pkg / STATE).write_text(json.dumps({"link": link.url, "version": version, "files": files, "project": project},
                                        ensure_ascii=False, separators=(",", ":")), encoding="utf-8", newline="\n")


def save_version(link, pkg, project, n, parent, note, known, name="Claude"):
    """Send the files the link does not hold yet, then version n. `known`: {sha256: file entry} already stored."""
    listed, pieces = {}, []
    for k, (mid, m) in enumerate(project.get("media", {}).items()):
        f = pkg / m["path"]
        if not f.is_file():
            die(f"{m['path']} is missing from the package; run package.py build again")
        digest = sha256_file(f)
        if digest in known:
            listed[mid] = known[digest]
            continue
        size = f.stat().st_size
        names = [f"f{n}x{k}.{p}" for p in range(max(1, -(-size // PIECE)))]
        listed[mid] = known[digest] = {"objects": names, "bytes": size, "type": TYPES.get(f.suffix.lower(), ""), "sha256": digest}
        pieces += [(names[p], f, p * PIECE, min(PIECE, size - p * PIECE)) for p in range(len(names))]
    manifest = json.dumps({"format": FORMAT, "made": datetime.now(timezone.utc).isoformat(timespec="seconds"), "version": n,
                           "parent": parent, "by": "agent", "name": name[:40], "note": note[:500], "project": project, "files": listed},
                          ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    total = sum(p[3] + OVERHEAD for p in pieces) + len(manifest) + OVERHEAD
    if total > LIMIT:
        big = max(listed.items(), key=lambda kv: kv[1]["bytes"])
        die(f"this is {total / 1e6:.0f} MB to send and a link holds {LIMIT / 1e6:.0f} MB. The largest file is "
            f"{project['media'][big[0]]['path']} ({big[1]['bytes'] / 1e6:.0f} MB). Make the footage smaller and build "
            "again, for example: ffmpeg -i IN -c:v libx264 -crf 20 -preset medium -c:a aac -b:a 192k OUT.mp4 "
            "(keep the frame rate and the frame size at least the canvas size), or give the person the folder.")
    return listed, pieces, manifest, total


def upload(link, pieces):
    def send(piece):
        name, f, start, length = piece
        with open(f, "rb") as fh:
            fh.seek(start)
            link.put(name, fh.read(length))
        return length + OVERHEAD
    with ThreadPoolExecutor(max_workers=4) as pool:
        return sum(pool.map(send, pieces))


def cmd_send(a):
    pkg = Path(a.package).resolve()
    project = read_package(pkg)
    link = Link(a.site, "", os.urandom(32))
    listed, pieces, manifest, total = save_version(link, pkg, project, 1, None, a.note or "", {}, a.name)
    code, body = call("POST", link.api, json.dumps({"bytes": total, "objects": len(pieces) + 1, "write": link.write}).encode(),
                      {"Content-Type": "application/json"})
    if code != 201:
        die(f"the studio did not make a link ({code}): {body}")
    made = json.loads(body)
    link.sid = made["id"]
    t0 = time.time()
    try:
        upload(link, pieces)
        code, body = link.put("v1", manifest)        # last: a version that is there has all its files
        if code != 201:
            raise RuntimeError(f"v1: {code} {body}")
    except Exception as e:
        call("DELETE", f"{link.api}/{link.sid}", None, {"Authorization": "Bearer " + link.write}, tries=1)
        die(f"sending stopped and the link was removed: {e}")
    write_state(pkg, link, 1, listed, project)
    print(f"sent {total / 1e6:.1f} MB encrypted in {len(pieces) + 1} objects, {time.time() - t0:.0f} s")
    print(f"version 1; expires {made['expires']} (30 days, with every later version); then the files are deleted")
    print("the key is the part of the link after the #. It is stored nowhere else: keep the link whole.")
    print("->", link.url)


def cmd_push(a):
    pkg = Path(a.package).resolve()
    project = read_package(pkg)
    link, st = read_state(pkg)
    latest = link.latest()["version"]
    if latest != st["version"] and not a.force:
        m = link.version(latest)
        die(f"version {latest} was saved on this link by {who(m)} after version {st['version']}, "
            f"which you started from{': ' + json.dumps(m['note'], ensure_ascii=False) if m.get('note') else ''}. "
            f"Run share.py pull {pkg} and make your change again on top of it. --force would replace their work with yours.")
    last = link.version(latest)
    if latest == st["version"] and project == st.get("project"):
        print(f"nothing changed since version {latest}; nothing sent")
        print("->", link.url)
        return
    known = {f["sha256"]: f for f in (last.get("files") or {}).values() if f.get("sha256")}
    n = latest + 1
    listed, pieces, manifest, total = save_version(link, pkg, project, n, st["version"], a.note or "", known, a.name)
    code, body = call("POST", f"{link.api}/{link.sid}/reserve", json.dumps({"bytes": total, "objects": len(pieces) + 1}).encode(),
                      {"Content-Type": "application/json", "Authorization": "Bearer " + link.write})
    if code != 200:
        die(f"the studio did not take a new version ({code}): {body}")
    t0 = time.time()
    upload(link, pieces)
    code, body = link.put(f"v{n}", manifest)
    if code == 409:
        die(f"someone saved version {n} at the same moment. Run share.py pull {pkg}, make your change again and push.")
    write_state(pkg, link, n, listed, project)
    lines = summary(st.get("project") or last["project"], project)
    print(f"version {n} saved: {len(lines)} change(s) from version {st['version']}; {total / 1e6:.2f} MB sent in {time.time() - t0:.0f} s"
          f" ({len(pieces)} new file piece(s))")
    for line in lines[:40]:
        print("  -", line)
    print("the person's open studio shows that version", n, "is there; the link is the same:")
    print("->", link.url)


def cmd_pull(a):
    if Path(a.source).is_dir() and (Path(a.source) / STATE).is_file():
        out = Path(a.out or a.source).resolve()
        link, st = read_state(Path(a.source).resolve())
        pinned = a.version
    else:
        if not a.out:
            die("say where to write it: --out result/NAME.edit")
        out = Path(a.out).resolve()
        link, pinned = Link.parse(a.source)
        pinned = a.version or pinned
    latest = link.latest()["version"]
    if not latest:
        die("this link has no version yet; it may still be uploading")
    n = min(pinned or latest, latest)
    m = link.version(n)
    project = m["project"]
    before = None
    if (out / "project.json").is_file():
        try:
            before = json.loads((out / "project.json").read_text(encoding="utf-8"))
        except Exception:
            before = None
    (out / "media").mkdir(parents=True, exist_ok=True)
    got = kept = 0
    for mid, f in (m.get("files") or {}).items():
        media = project.get("media", {}).get(mid)
        if not media:
            continue
        name = Path(str(media.get("path", mid)).replace("\\", "/")).name          # never outside media/
        media["path"] = "media/" + name
        dst = out / "media" / name
        if dst.is_file() and dst.stat().st_size == f["bytes"] and (not f.get("sha256") or sha256_file(dst) == f["sha256"]):
            kept += 1
            continue
        tmp = dst.with_name(dst.name + ".part")
        with open(tmp, "wb") as fh:
            for obj in f["objects"]:
                fh.write(link.fetch(obj))
        os.replace(tmp, dst)
        got += 1
    (out / "project.json").write_text(json.dumps(project, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
    write_state(out, link, n, m.get("files") or {}, project)
    print(f"version {n} of {latest}, saved by {who(m)} at {m.get('made')}"
          + (f" from version {m['parent']}" if m.get("parent") else "") + f"; {got} file(s) fetched, {kept} already here")
    if m.get("note"):
        print("note:", m["note"])
    if before is not None:
        lines = summary(before, project)
        print(f"{len(lines)} change(s) from the project.json that was in {out.name}:" if lines else f"same as the project.json that was in {out.name}")
        for line in lines[:60]:
            print("  -", line)
        if len(lines) > 60:
            print(f"  - and {len(lines) - 60} more")
    print("->", out / "project.json")
    print("edit this project.json for your next change (not an older copy), then render.py and share.py push.")


def cmd_versions(a):
    if Path(a.source).is_dir():
        link, st = read_state(Path(a.source).resolve())
        mine = st["version"]
    else:
        link, _ = Link.parse(a.source)
        mine = None
    about = link.latest()
    print(f"{about['version']} version(s); the link expires {about['expires']}")
    for n in range(about["version"], 0, -1):
        m = link.version(n)
        print(f"  v{n}  {m.get('made')}  {who(m)}" + (f"  from v{m['parent']}" if m.get("parent") else "")
              + ("  <- the one in this folder" if n == mine else "") + (f"\n       {m['note']}" if m.get("note") else ""))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("send", help="make a new link with the package as version 1")
    s.add_argument("package", help="the package folder (with project.json and media/)")
    s.add_argument("--site", default=SITE, help="the studio to send to (default: %(default)s)")
    s.add_argument("--note", default="", help="a line for the person, shown with the version")
    s.add_argument("--name", default="Claude", help="who you are, shown to the person in the studio (default: %(default)s)")
    p = sub.add_parser("push", help="save the package as the next version on its link")
    p.add_argument("package")
    p.add_argument("--note", default="", help="what you changed, shown to the person in the studio")
    p.add_argument("--name", default="Claude", help="who you are, shown to the person in the studio (default: %(default)s)")
    p.add_argument("--force", action="store_true", help="save even when a newer version is on the link (theirs is then not in yours)")
    for name in ("pull", "get"):
        g = sub.add_parser(name, help="write the newest version (or --version N) of a link into a package folder")
        g.add_argument("source", help="a package folder that has a link, or the whole link in quotes")
        g.add_argument("--out", help="the package folder to write (default: the folder given)")
        g.add_argument("--version", type=int, help="a version other than the newest")
    v = sub.add_parser("versions", help="list the versions on a link")
    v.add_argument("source", help="a package folder that has a link, or the whole link in quotes")
    a = ap.parse_args()
    {"send": cmd_send, "push": cmd_push, "pull": cmd_pull, "get": cmd_pull, "versions": cmd_versions}[a.cmd](a)


if __name__ == "__main__":
    main()

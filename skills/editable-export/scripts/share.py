"""A light studio link for a package folder: the project's versions only, encrypted. Media never leave the folder.

  share.py send result/my-video.edit                  # a new link holding the folder's versions; prints the link
  share.py push result/my-video.edit                  # your newer versions (package.py save) onto the link
  share.py pull result/my-video.edit                  # the person's newer versions from the link, into the folder
  share.py pull "https://edit.trysometh.ing/studio#ID.KEY" --out result/my-video.edit   # a link you were given
  share.py versions result/my-video.edit              # the versions on the link (or give the link itself)
  share.py send result/my-video.edit --site http://127.0.0.1:8799                       # a local studio

The folder stays the real thing: project.json, media/ and versions/v<n>.json (package.py). A link only carries the
versions, so the person and you can pass the project back and forth without passing the folder each time. A version
has the same number in the folder and on the link. Links have no end date for now (EditAtlas may set one later,
and says so in its answers); the folder keeps every version either way.

Each version is gzip of its JSON, encrypted on this machine with AES-256-GCM and a random key made by `send`. The key
is only in the link, after the #, which browsers never send to a server, so EditAtlas stores bytes it cannot read.
Anyone who has the link can read and add versions: give it only to the person. FOLDER/.studio-link holds the link and
the newest version both have; it contains the key, so never put it in a repository or a message other than to them.

Format "editatlas-share/2", also read and written by the studio page:
  object v<n> = 12-byte nonce + AES-256-GCM(gzip(UTF-8 JSON)) + 16-byte tag,
                additional data "editatlas-share/2|<share id>|v<n>";
  JSON = {format, version, parent, by, name, note, made, project, media: {<id>: {path, bytes}}};
  write token = HKDF-SHA256(key, no salt, info "editatlas-share/2 write"), 32 bytes, base64url, a Bearer token.
Limits: a version at most 256 KiB sealed; a link at most 2 MiB and 64 versions; no end date for now.

Needs `pip install cryptography`. EDITATLAS_INTERNAL, when set, goes out as the X-EditAtlas-Internal header.
"""
import argparse
import base64
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import package as pk  # noqa: E402  (version files, change_summary)

FORMAT = "editatlas-share/2"
SITE = "https://edit.trysometh.ing"
AGENT = "editatlas-skills/editable-export"
STATE = ".studio-link"
OVERHEAD = 28                                    # nonce + tag
MAX_OBJECT, MAX_LINK, MAX_OBJECTS = 256 * 1024, 2 * 1024 * 1024, 64
LINK = re.compile(r"(https?://[^/#\s]+)/studio#([A-Za-z0-9_-]{22})\.([A-Za-z0-9_-]{43})(?:\.([1-9][0-9]{0,4}))?")


def die(msg):
    sys.exit("editable-export: " + msg)


def b64u(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def call(method, url, body=None, headers=None, tries=3):
    """One request -> (status, body bytes or the server's error message). A refusal (4xx) is final; a dropped
    connection or a busy server is tried again."""
    head = {"User-Agent": AGENT, **(headers or {})}
    internal = os.environ.get("EDITATLAS_INTERNAL")          # EditAtlas's own checks: kept out of its numbers
    if internal:
        head["X-EditAtlas-Internal"] = internal
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=body, method=method, headers=head), timeout=60) as r:
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


def refused(code, body, what):
    """The server's own message (413, 400 and 410 come as JSON {error}), and what to do about an expired link."""
    if code in (404, 410):
        msg = body if code == 410 and body else "this link was taken down or does not exist."
        die(f"{what}: {msg} The folder still has every version: make a new link with share.py send FOLDER --new.")
    die(f"the studio refused {what} ({code}): {body}")


class Link:
    """One studio link: site, id and key; sealing, and the calls that read and add versions."""

    def __init__(self, site, sid, key):
        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        except ImportError:
            die("the cryptography package is not installed: pip install cryptography. The folder works without a "
                "link: the person opens it at " + site + "/studio with Choose the folder.")
        self.site, self.sid, self.key = site.rstrip("/"), sid, key
        self.api = self.site + "/api/v1/studio/shares"
        self.aes = AESGCM(key)
        self.write = b64u(HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                               info=f"{FORMAT} write".encode()).derive(key))

    @classmethod
    def parse(cls, text):
        m = LINK.fullmatch(text.strip())
        if not m:
            die("that is not a whole studio link: it looks like https://edit.trysometh.ing/studio#<id>.<key>")
        return cls(m.group(1), m.group(2), base64.urlsafe_b64decode(m.group(3) + "=")), (int(m.group(4)) if m.group(4) else None)

    @property
    def url(self):
        return f"{self.site}/studio#{self.sid}.{b64u(self.key)}"

    def aad(self, name):
        return f"{FORMAT}|{self.sid}|{name}".encode("utf-8")

    def seal(self, name, data):
        nonce = os.urandom(12)
        return nonce + self.aes.encrypt(nonce, data, self.aad(name))

    def unseal(self, name, blob):
        return self.aes.decrypt(blob[:12], blob[12:], self.aad(name))

    def seal_version(self, obj):
        return self.seal(f"v{obj['version']}", pack(obj))

    def open_version(self, n, blob):
        try:
            obj = json.loads(gzip.decompress(self.unseal(f"v{n}", blob)).decode("utf-8"))
        except Exception:
            die("the key in this link does not open it; ask for the whole link again, with the part after the #")
        if obj.get("format") != FORMAT or obj.get("version") != n or (obj.get("project") or {}).get("format") != pk.FORMAT:
            die(f"version {n} on this link is not something this script can read (format {obj.get('format')!r})")
        return obj

    def info(self):
        code, body = call("GET", f"{self.api}/{self.sid}")
        if code != 200:
            refused(code, body, "reading the link")
        return json.loads(body)

    def version(self, n):
        code, body = call("GET", f"{self.api}/{self.sid}/objects/v{n}")
        if code != 200:
            refused(code, body, f"reading version {n}")
        return self.open_version(n, body)

    def auth(self, extra=None):
        return {"Authorization": "Bearer " + self.write, **(extra or {})}

    def put_version(self, obj, reserve=True):
        """Room for one version, then the version. Returns 201, or 409 when that number was taken meanwhile."""
        sealed = self.seal_version(obj)
        if reserve:
            code, body = call("POST", f"{self.api}/{self.sid}/reserve",
                              json.dumps({"bytes": len(sealed), "objects": 1}).encode(), self.auth({"Content-Type": "application/json"}))
            if code == 409:
                return 409
            if code not in (200, 201):
                refused(code, body, f"room for version {obj['version']}")
        code, body = call("PUT", f"{self.api}/{self.sid}/objects/v{obj['version']}", sealed,
                          self.auth({"Content-Type": "application/octet-stream"}))
        if code == 409:
            return 409
        if code != 201:
            refused(code, body, f"version {obj['version']}")
        return 201


def pack(obj):
    return gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0)


# ------------------------------------------------------------------ folder <-> link versions
def to_link(folder, v):
    """A folder version -> the link's object: the same fields, plus the size of every media file it uses."""
    media = {}
    for mid, m in (v["project"].get("media") or {}).items():
        f = folder / m["path"]
        if not f.is_file():
            die(f"version {v['version']} uses {m['path']}, which is not in {folder}; run package.py check {folder}")
        media[mid] = {"path": m["path"], "bytes": f.stat().st_size}
    return {"format": FORMAT, **{k: v.get(k) for k in ("version", "parent", "by", "name", "note", "made", "project")},
            "media": media}


def to_folder(obj):
    return {"format": pk.VERSION_FORMAT, **{k: obj.get(k) for k in ("version", "parent", "by", "name", "note", "made", "project")}}


def sealed_size(obj):
    return len(pack(obj)) + OVERHEAD


def check_size(obj):
    n = sealed_size(obj)
    if n > MAX_OBJECT:
        die(f"version {obj['version']} is {n / 1024:.0f} KiB encrypted and a link takes at most {MAX_OBJECT // 1024} KiB "
            "per version. The folder works without the link.")
    return n


def read_state(folder):
    f = folder / STATE
    if not f.is_file():
        return None, 0
    st = json.loads(f.read_text(encoding="utf-8"))
    return Link.parse(st["link"])[0], int(st.get("version") or 0)


def write_state(folder, link, version):
    pk.write_json(folder / STATE, {"link": link.url, "version": version})
    # .studio-link holds the key: keep it out of any Git repository the folder ends up in.
    ignore = folder / ".gitignore"
    lines = ignore.read_text(encoding="utf-8").splitlines() if ignore.is_file() else []
    if STATE not in lines and f"/{STATE}" not in lines:
        ignore.write_text("\n".join([*lines, STATE]) + "\n", encoding="utf-8")


def folder_versions(folder):
    have = pk.version_files(folder)
    if not have:
        if (folder / "project.json").is_file():
            die(f"{folder} has no versions/ yet. Run package.py check {folder}; a folder made before versions gets its "
                "version 1 from package.py save.")
        die(f"no package in {folder}; run package.py build first")
    if list(have) != list(range(1, len(have) + 1)):
        die(f"the versions in {folder} have gaps; run package.py check {folder}")
    return have


def fetch_studio_fonts(folder, obj, site):
    """Fonts the person picked from the studio's own set: the studio puts them at media/fonts/<Family>-<weight>.woff2,
    and, like the studio, this fetches them from the site when the folder lacks them (a link never carries media)."""
    want = {mid: m for mid, m in (obj.get("media") or {}).items()
            if m.get("kind") == "font" and str(m.get("path", "")).startswith("media/fonts/") and not (folder / m["path"]).is_file()}
    if not want:
        return
    code, body = call("GET", site + "/studio-fonts/fonts.json", tries=2)
    if code != 200:
        return
    files = {name for f in json.loads(body).get("fonts", []) for name in f.get("files", {}).values()}
    for mid, m in want.items():
        name = m["path"].split("/")[-1]
        if name not in files or m["path"] != "media/fonts/" + name:
            continue
        code, data = call("GET", site + "/studio-fonts/" + name, tries=2)
        if code == 200 and data[:4] == b"wOF2":
            (folder / "media/fonts").mkdir(parents=True, exist_ok=True)
            (folder / m["path"]).write_bytes(data)
            print(f"fetched the studio font {m.get('family')} {m.get('weight', 400)}: {m['path']}")


def print_media_gaps(folder, obj):
    """Media the newest version uses that the folder does not hold with the same size."""
    gaps = []
    for mid, m in (obj.get("media") or {}).items():
        f = folder / str(m.get("path", ""))
        if not f.is_file():
            gaps.append(f"{mid}: {m.get('path')} ({m.get('bytes')} bytes) is not in the folder")
        elif m.get("bytes") is not None and f.stat().st_size != m["bytes"]:
            gaps.append(f"{mid}: {m.get('path')} is {f.stat().st_size} bytes here, {m['bytes']} on the link")
    if gaps:
        print("media this version needs and the folder lacks (a link never carries media; add these files to the "
              "folder before you render):")
        for g in gaps:
            print("  -", g)
    return gaps


# ------------------------------------------------------------------ commands
def cmd_send(a):
    folder = Path(a.folder).resolve()
    have = folder_versions(folder)
    old, _ = read_state(folder)
    if old and not a.new:
        die(f"{folder} already has a link. Put your newer versions on it with share.py push {folder}; use --new only "
            "for a new link (for example when the old one expired).")
    key = os.urandom(32)
    link = Link(a.site, "", key)
    objs = [to_link(folder, pk.read_version(f)) for f in have.values()]
    if a.name:
        for o in objs:
            if o["by"] == "agent" and not o.get("name"):
                o["name"] = a.name[:40]
    sizes = [check_size(o) for o in objs]
    if len(objs) > MAX_OBJECTS or sum(sizes) > MAX_LINK:
        die(f"{len(objs)} versions, {sum(sizes) / 1024:.0f} KiB encrypted: a link holds at most {MAX_OBJECTS} versions "
            f"and {MAX_LINK // 1024} KiB. The folder works without a link.")
    code, body = call("POST", link.api, json.dumps({"bytes": sizes[0], "objects": 1, "write": link.write}).encode(),
                      {"Content-Type": "application/json"})
    if code != 201:
        refused(code, body, "a new link")
    made = json.loads(body)
    link.sid = made["id"]
    for k, o in enumerate(objs):
        if link.put_version(o, reserve=k > 0) != 201:
            call("DELETE", f"{link.api}/{link.sid}", None, link.auth(), tries=1)
            die(f"version {o['version']} was refused while sending; the new link was removed")
    write_state(folder, link, len(objs))
    print(f"{len(objs)} version(s), {sum(sizes) / 1024:.1f} KiB encrypted; no media sent")
    print(f"expires {made.get('expires')}; the folder keeps every version after that" if made.get("expires") else "no end date for now; the folder keeps every version anyway")
    print("the key is the part after the #. It is stored nowhere else: keep the link whole. Written to", folder / STATE)
    print("->", link.url)


def cmd_push(a):
    folder = Path(a.folder).resolve()
    have = folder_versions(folder)
    link, mine = read_state(folder)
    if not link:
        die(f"{folder} has no link yet: share.py send {folder} makes one")
    newest = max(have)
    if newest <= mine:
        print(f"the link already has version {mine}, the folder's newest; nothing sent")
        print("->", link.url)
        return
    info = link.info()
    if info["version"] > mine:
        v = link.version(info["version"])
        die(f"version {info['version']} was saved on the link by {pk.who(v)} at {v.get('made')}, after version {mine}"
            + (f' (note: "{v["note"]}")' if v.get("note") else "") + f". Nothing sent. Run share.py pull {folder} first.")
    objs = [to_link(folder, pk.read_version(have[n])) for n in range(mine + 1, newest + 1)]
    sizes = [check_size(o) for o in objs]
    if info.get("objects", 0) + len(objs) > MAX_OBJECTS or info.get("bytes", 0) + sum(sizes) > MAX_LINK:
        die(f"the link is full ({MAX_OBJECTS} versions or {MAX_LINK // 1024} KiB). Make a new one with share.py send "
            f"{folder} --new and give the person the new link.")
    for o in objs:
        if link.put_version(o) == 409:
            die(f"someone saved version {o['version']} on the link at the same moment. Nothing more sent. Run "
                f"share.py pull {folder} first.")
        write_state(folder, link, o["version"])
        print(f"v{o['version']} sent ({pk.who(o)}" + (f', "{o["note"]}"' if o.get("note") else "") + ")")
    print(f"the link now has version {newest}; the person's studio picks it up from the same link")
    print("->", link.url)


def cmd_pull(a):
    src = Path(a.source)
    if src.is_dir() and (src / STATE).is_file():
        folder = Path(a.out or a.source).resolve()
        link, mine = read_state(src.resolve())
        pinned = a.version
    else:
        if src.is_dir():
            die(f"{src} has no link; give the link itself: share.py pull \"LINK\" --out {src}")
        if not a.out:
            die("say which folder to write into: --out result/NAME.edit")
        folder = Path(a.out).resolve()
        link, pinned = Link.parse(a.source)
        pinned = a.version or pinned
        other, mine = read_state(folder)
        if other and other.sid != link.sid:
            die(f"{folder} belongs to another link; choose another --out folder")
    info = link.info()
    if not info.get("version"):
        die("this link has no version yet")
    target = min(pinned or info["version"], info["version"])
    have = pk.version_files(folder)
    if not have and (folder / "project.json").is_file():
        die(f"{folder} has a project.json but no versions/; pull into a new folder and copy the media into it")
    fetched, clash = {}, []
    for n in range(mine + 1, target + 1):
        fetched[n] = link.version(n)
        if n in have and pk.read_version(have[n]) != to_folder(fetched[n]):
            clash.append(n)
    for n in have:                                   # folder versions the link does not know: also in the way
        if n > target and n > mine:
            clash.append(n)
    clash = sorted(set(clash))
    if clash:
        if not a.set_aside:
            die(f"the folder's version(s) {', '.join(map(str, clash))} are not the link's (saved here and never pushed, "
                f"while the link got its own). Nothing written. Run again with --set-aside: they move to "
                f"{folder / 'set-aside'} and the link's versions come in; then make your change again on top of the "
                "newest with package.py save, and push.")
        (folder / "set-aside").mkdir(exist_ok=True)
        for n in clash:
            dst = folder / "set-aside" / f"v{n}-{int(time.time())}.json"
            os.replace(have[n], dst)
            print(f"your v{n} moved to {dst}")
        have = pk.version_files(folder)
    (folder / "versions").mkdir(parents=True, exist_ok=True)
    wrote = []
    for n in range(1, target + 1):
        if n in have:
            continue
        obj = fetched.get(n) or link.version(n)
        fetched[n] = obj
        pk.write_json(folder / "versions" / f"v{n}.json", to_folder(obj), new=True)
        wrote.append(n)
    newest = fetched.get(target) or link.version(target)
    pk.write_json(folder / "project.json", newest["project"])
    write_state(folder, link, target)
    for n in wrote:
        o = fetched[n]
        print(f"v{n} by {pk.who(o)}, {o.get('made')}" + (f", from v{o['parent']}" if o.get("parent") else "")
              + (f', note: "{o["note"]}"' if o.get("note") else ""))
    print(f"wrote {len(wrote)} version(s); the folder and the link both have version {target}"
          + (f" (the link has {info['version']})" if info["version"] > target else ""))
    if newest.get("parent") and wrote:
        par = folder / "versions" / f"v{newest['parent']}.json"
        if par.is_file():
            lines = pk.change_summary(pk.read_version(par)["project"], newest["project"])
            print(f"changes from v{newest['parent']} to v{target}:" if lines else f"no changes from v{newest['parent']}")
            for line in lines:
                print("  -", line)
    fetch_studio_fonts(folder, newest["project"], link.site)
    print_media_gaps(folder, newest)
    print("->", folder / "project.json")
    print(f"edit a copy of it, then package.py save COPY --to {folder} --from {target}, render.py, share.py push.")


def cmd_versions(a):
    src = Path(a.source)
    if src.is_dir():
        link, mine = read_state(src.resolve())
        if not link:
            die(f"{src} has no link; package.py versions {src} lists the folder's versions")
    else:
        link, _ = Link.parse(a.source)
        mine = None
    info = link.info()
    print(f"{info['version']} version(s) on the link; " + (f"it expires {info['expires']}" if info.get("expires") else "no end date for now"))
    for n in range(info["version"], 0, -1):
        v = link.version(n)
        print(f"  v{n}  {pk.who(v)}  {v.get('made')}  " + (f"from v{v['parent']}" if v.get("parent") else "first")
              + (f'  "{v["note"]}"' if v.get("note") else "") + ("  <- the folder's link version" if n == mine else ""))


def main():
    pk.utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("send", help="make a new link holding the folder's versions")
    s.add_argument("folder", help="the package folder (NAME.edit)")
    s.add_argument("--site", default=SITE, help="the studio to use (default: %(default)s)")
    s.add_argument("--name", default="Claude", help="your name on agent versions that have none (default: %(default)s)")
    s.add_argument("--new", action="store_true", help="make a new link even though the folder has one")
    p = sub.add_parser("push", help="put the folder's versions newer than the link's onto the link")
    p.add_argument("folder")
    g = sub.add_parser("pull", help="write the link's newer versions into the folder (never media)")
    g.add_argument("source", help="a package folder that has a link, or the whole link in quotes")
    g.add_argument("--out", help="the folder to write into (default: the folder given)")
    g.add_argument("--version", type=int, help="stop at this version instead of the newest")
    g.add_argument("--set-aside", action="store_true",
                   help="move the folder's versions that the link does not have to set-aside/, then pull")
    v = sub.add_parser("versions", help="list the versions on a link")
    v.add_argument("source", help="a package folder that has a link, or the whole link in quotes")
    a = ap.parse_args()
    {"send": cmd_send, "push": cmd_push, "pull": cmd_pull, "versions": cmd_versions}[a.cmd](a)


if __name__ == "__main__":
    main()

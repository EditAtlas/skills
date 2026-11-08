"""Correct words in transcript.json without breaking the times, then rewrite the subtitle files.

  fix.py work/transcript/transcript.json show 40-60            # words with their numbers and times
  fix.py work/transcript/transcript.json set 45 "400 ms"       # one word, its times kept
  fix.py work/transcript/transcript.json set 12-13 "EditAtlas" # two heard words become one, first start to last end
  fix.py work/transcript/transcript.json delete 97-110         # words nobody said (an invented line)
  fix.py work/transcript/transcript.json names                 # apply every "looks like the name" suggestion
  fix.py work/transcript/transcript.json checked               # the person confirmed it: templates may use it

Every change is logged in the file's "edits" list. Review items that touched a changed word are dropped.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also under python -I
from captions import text_of, write_all
from common import clock, die, read_json, utf8_stdout, write_json


def span(text, n):
    a, _, b = text.partition("-")
    i, j = int(a), int(b or a)
    if not (0 <= i <= j < n):
        die(f"word numbers {text} are outside 0-{n - 1}")
    return i, j


def replace(t, i, j, new_words, note):
    words = t["words"]
    removed = j - i + 1
    words[i:j + 1] = new_words
    shift = len(new_words) - removed
    m = len(new_words)
    for s in t["segments"]:
        # a segment edge inside the changed span moves to the edge of the new words
        if s["first"] > j:
            s["first"] += shift
        elif s["first"] >= i:
            s["first"] = i
        if s["last"] > j:
            s["last"] += shift
        elif s["last"] >= i:
            s["last"] = i + m - 1
        if s["last"] < s["first"]:
            s["text"] = ""
        else:
            s["text"] = text_of(words[s["first"]:s["last"] + 1])
    t["segments"] = [s for s in t["segments"] if s["text"]]
    kept = []
    for r in t.get("review", []):
        a, b = r["i"], r.get("to", r["i"])
        if b < i or a > j:
            if a > j:
                r["i"] = a + shift
                if "to" in r:
                    r["to"] = b + shift
            kept.append(r)
    t["review"] = kept
    t.setdefault("edits", []).append(note)
    t["checked"] = False


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("transcript")
    p.add_argument("action", choices=["show", "set", "delete", "names", "checked"])
    p.add_argument("args", nargs="*")
    a = p.parse_args()
    t = read_json(a.transcript)
    words = t["words"]

    if a.action == "show":
        i, j = span(a.args[0], len(words)) if a.args else (0, len(words) - 1)
        for k in range(i, j + 1):
            w = words[k]
            print(f"{k:5d}  {clock(w['start']):>7} {w['start']:8.3f}-{w['end']:8.3f}  p {w['p']:.2f}  {w['w']}")
        return
    if a.action == "set":
        if len(a.args) != 2:
            die('set needs the word numbers and the new text: set 12-13 "EditAtlas"')
        i, j = span(a.args[0], len(words))
        old = text_of(words[i:j + 1])
        parts = a.args[1].split()
        if not parts:
            die("the new text is empty; use delete")
        if len(parts) == j - i + 1:
            new = [dict(words[i + k], w=parts[k], p=1.0) for k in range(len(parts))]
        else:
            # A different number of words: spread them over the old span by length, so word times stay usable.
            start, end = words[i]["start"], words[j]["end"]
            total = sum(len(x) for x in parts)
            new, at = [], start
            for x in parts:
                d = (end - start) * len(x) / total
                new.append({"w": x, "start": round(at, 3), "end": round(at + d, 3), "p": 1.0})
                at += d
        replace(t, i, j, new, {"set": [i, j], "from": old, "to": a.args[1]})
        print(f"{i}-{j}: {old!r} -> {a.args[1]!r}")
    elif a.action == "delete":
        i, j = span(a.args[0], len(words))
        old = text_of(words[i:j + 1])
        replace(t, i, j, [], {"delete": [i, j], "from": old})
        print(f"deleted {i}-{j}: {old!r}")
    elif a.action == "names":
        todo = sorted((r for r in t.get("review", []) if r.get("fix")), key=lambda r: -r["i"])
        if not todo:
            print("no name suggestions to apply")
        for r in todo:                                   # from the end, so earlier numbers stay right
            i, j = r["i"], r.get("to", r["i"])
            old = text_of(t["words"][i:j + 1])
            new = [{"w": r["fix"], "start": t["words"][i]["start"], "end": t["words"][j]["end"], "p": 1.0}]
            replace(t, i, j, new, {"set": [i, j], "from": old, "to": r["fix"], "by": "names"})
            print(f"{i}-{j}: {old!r} -> {r['fix']!r}")
    elif a.action == "checked":
        left = len(t.get("review", []))
        t["checked"] = True
        t.setdefault("edits", []).append({"checked": True, "review_left": left})
        print(f"marked checked ({left} review items were left as they are)")
    write_json(a.transcript, t)
    cues, _, _ = write_all(t, str(Path(a.transcript).with_suffix("")))
    print(f"{len(t['words'])} words, {len(cues)} captions rewritten")


if __name__ == "__main__":
    main()

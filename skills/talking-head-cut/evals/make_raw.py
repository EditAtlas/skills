"""Make a raw talking-head take with known mistakes, for the test cases (Microsoft Edge voices, via edge-tts).

  python make_raw.py en_audio_tips                 # writes en_audio_tips.mp4 in the current folder
  python make_raw.py vi_rice --truth work/truth    # also keeps every spoken piece and what should stay

Each line of a script is said on its own and joined with a known pause, so the test knows exactly which words are
a false start, a retake, a note to the editor or a filler, and which must stay. The picture is a drawn face whose
mouth follows the voice, with the source frame number written in a strip of black and white squares along the top,
so a test can read which source frame ended up where after the cut.

Needs: pip install edge-tts numpy, FFmpeg, network access to Microsoft's speech service. No media is stored in this
repository; the takes are made fresh for each run.
"""
import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

# (kind, text, pause after in seconds). keep = the speaker meant it; cut = false start, failed or replaced take, note
# to the editor; filler = um / uh / ờ.
SCRIPTS = {
    "en_audio_tips": ("en-US-AndrewNeural", 1.4, [
        ("keep", "Hi, I'm Sam, and this is how I record clean audio at home.", 0.9),
        ("filler", "Um,", 0.3),
        ("keep", "the first thing is the room.", 1.8),
        ("cut", "Soft things like curtains and a sofa soak up the", 0.6),
        ("cut", "no, wait.", 0.5),
        ("keep", "Soft things like curtains, a rug and a sofa soak up the echo.", 0.7),
        ("keep", "So a bedroom often sounds better than a kitchen.", 2.5),
        ("keep", "The second thing is distance.", 0.4),
        ("keep", "Keep the microphone close.", 0.5),
        ("cut", "About thirty centimetres from your", 0.4),
        ("cut", "let me say that again.", 1.2),
        ("keep", "About fifteen centimetres from your mouth is plenty.", 0.6),
        ("cut", "And the third", 0.15),
        ("keep", "and the third thing is levels.", 0.5),
        ("filler", "Uh,", 0.25),
        ("keep", "keep your peaks around minus twelve decibels.", 0.8),
        ("keep", "Never record too hot.", 0.35),
        ("keep", "Never.", 0.4),
        ("keep", "You cannot fix clipping later.", 1.0),
        ("cut", "That's all for today, see you next week.", 1.5),
        ("cut", "Okay, one more time.", 1.0),
        ("keep", "That's it for today. See you next time.", 2.0),
    ]),
    "en_app_demo": ("en-US-AvaNeural", 1.0, [
        ("keep", "Hey everyone, today I'm showing you the new export panel.", 0.8),
        ("keep", "Open the editor first.", 0.5),
        ("cut", "Then press the blue button in the corner and", 0.7),
        ("cut", "hmm, hang on, scrap that.", 1.1),
        ("keep", "Then press the green button at the top.", 0.6),
        ("filler", "Uh,", 0.3),
        ("keep", "it works like a checklist,", 0.25),
        ("keep", "so you can tick each format you need.", 1.9),
        ("cut", "The best thing is", 0.12),
        ("keep", "the best thing is it runs in the background.", 0.6),
        ("keep", "Really. Really fast.", 0.9),
        ("cut", "You can export to four formats at", 0.5),
        ("cut", "wait, wrong number.", 1.0),
        ("keep", "You can export to five formats at once.", 0.7),
        ("cut", "This saves me about an hour every week.", 1.3),
        ("keep", "This saves me about an hour every single week.", 0.8),
        ("keep", "Thanks for watching, and I'll see you in the next one.", 1.5),
    ]),
    "vi_rice": ("vi-VN-HoaiMyNeural", 1.2, [
        ("keep", "Xin chào, mình là Linh, hôm nay mình chia sẻ cách nấu cơm ngon bằng nồi cơm điện.", 0.8),
        ("filler", "Ờ,", 0.3),
        ("keep", "đầu tiên là vo gạo.", 1.6),
        ("cut", "Bạn vo gạo khoảng ba lần rồi đổ", 0.5),
        ("cut", "à không, làm lại nhé.", 1.0),
        ("keep", "Bạn vo gạo nhẹ tay khoảng hai lần, đừng chà mạnh.", 0.7),
        ("keep", "Vì chà mạnh sẽ làm mất chất dinh dưỡng.", 2.2),
        ("keep", "Bước thứ hai là đong nước.", 0.5),
        ("cut", "Tỉ lệ nước là", 0.15),
        ("keep", "tỉ lệ nước là một gạo một rưỡi nước.", 0.6),
        ("filler", "Ừm,", 0.3),
        ("keep", "sau đó bạn ngâm gạo khoảng mười lăm phút.", 0.9),
        ("keep", "Rất, rất quan trọng: đừng mở nắp khi đang nấu.", 1.4),
        ("cut", "Vậy là xong rồi, chúc các bạn nấu ngon.", 1.4),
        ("cut", "Cắt đoạn này, nói lại.", 1.0),
        ("keep", "Vậy là xong rồi. Chúc các bạn nấu cơm thật ngon nhé.", 2.0),
    ]),
}
SR = 48000
FPS = 30
W, H = 960, 540
BITS = 14            # frame number in squares along the top: up to 16383 frames (9 minutes at 30 fps)
SQ = 40


async def say(voice, text, path):
    import edge_tts
    for k in range(12):
        try:
            await edge_tts.Communicate(text, voice).save(str(path))
            return
        except Exception as e:
            err = e
            await asyncio.sleep(2 + 2 * k)
    sys.exit(f"edge-tts did not answer for {text!r}: {err}")


def to_wav(src):
    r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(src), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                       capture_output=True, check=True)
    x = np.frombuffer(r.stdout, np.float32)
    # edge-tts adds its own quiet at both ends; trim it to the voice so the pauses are the script's.
    lvl = np.abs(x) > 10 ** (-50 / 20)
    if lvl.any():
        a, b = np.argmax(lvl), len(x) - np.argmax(lvl[::-1])
        x = x[max(0, a - int(0.01 * SR)):min(len(x), b + int(0.03 * SR))]
    return x.copy()


def face_frames(audio, n_frames):
    """A drawn face on a plain wall, mouth opening with the voice, frame number in squares along the top."""
    yy, xx = np.mgrid[0:H, 0:W]
    bg = np.empty((H, W, 3), np.uint8)
    bg[:] = (70, 82, 96)
    bg[int(H * 0.78):] = (52, 60, 70)
    head = ((xx - W / 2) / 150) ** 2 + ((yy - H * 0.52) / 190) ** 2 <= 1
    body = ((xx - W / 2) / 260) ** 2 + ((yy - H * 1.15) / 260) ** 2 <= 1
    eyes = (((xx - W / 2 + 55) / 16) ** 2 + ((yy - H * 0.45) / 10) ** 2 <= 1) | \
           (((xx - W / 2 - 55) / 16) ** 2 + ((yy - H * 0.45) / 10) ** 2 <= 1)
    base = bg.copy()
    base[body] = (40, 70, 120)
    base[head] = (224, 186, 160)
    base[eyes] = (40, 30, 30)
    hop = SR // FPS
    level = np.array([np.sqrt(np.mean(audio[i * hop:(i + 1) * hop] ** 2) + 1e-12) for i in range(n_frames)])
    open_ = np.clip((20 * np.log10(level + 1e-9) + 50) / 30, 0, 1)
    mouths = [(((xx - W / 2) / 45) ** 2 + ((yy - H * 0.64) / max(2, 4 + 26 * k / 5)) ** 2 <= 1) for k in range(6)]
    for f in range(n_frames):
        img = base.copy()
        sway = int(6 * np.sin(f / 23))
        if sway:
            img[:, max(0, sway):W + min(0, sway)] = base[:, max(0, -sway):W - max(0, sway)]
        img[mouths[int(round(open_[f] * 5))]] = (120, 40, 50)
        img[:SQ + 8] = (128, 128, 128)
        for b in range(BITS):
            v = 255 if (f >> (BITS - 1 - b)) & 1 else 0
            img[4:4 + SQ, 8 + b * (SQ + 8):8 + b * (SQ + 8) + SQ] = v
        yield img.tobytes()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("name", choices=sorted(SCRIPTS))
    p.add_argument("--truth", help="folder for the answer: every piece as WAV plus truth.json (never give it to the agent)")
    a = p.parse_args()
    voice, lead, lines = SCRIPTS[a.name]
    tmp = Path(tempfile.mkdtemp())
    parts, pieces, t = [np.zeros(int(lead * SR), np.float32)], [], lead
    for i, (kind, text, pause) in enumerate(lines):
        asyncio.run(say(voice, text, tmp / f"{i}.mp3"))
        x = to_wav(tmp / f"{i}.mp3")
        pieces.append({"i": i, "kind": kind, "text": text, "start": round(t, 3), "end": round(t + len(x) / SR, 3), "audio": x})
        parts += [x, np.zeros(int(pause * SR), np.float32)]
        t += len(x) / SR + pause
    audio = np.concatenate(parts)
    audio = (audio / max(1e-6, np.abs(audio).max()) * 10 ** (-3 / 20)).astype(np.float32)   # peak -3 dBFS
    audio = np.concatenate([audio, np.zeros(SR // FPS * 2, np.float32)])
    n_frames = int(len(audio) / SR * FPS)
    wav = tmp / "voice.f32"
    audio.tofile(wav)
    out = Path(f"{a.name}.mp4")
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", str(wav),
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)], stdin=subprocess.PIPE)
    for frame in face_frames(audio, n_frames):
        enc.stdin.write(frame)
    enc.stdin.close()
    if enc.wait():
        sys.exit("ffmpeg failed")
    if a.truth:
        d = Path(a.truth)
        d.mkdir(parents=True, exist_ok=True)
        scale = 10 ** (-3 / 20) / max(1e-6, np.abs(np.concatenate(parts)).max())
        for pc in pieces:
            (pc.pop("audio") * scale).astype(np.float32).tofile(d / f"piece{pc['i']:02d}.f32")
        (d / "truth.json").write_text(json.dumps({"name": a.name, "sr": SR, "fps": FPS, "bits": BITS, "sq": SQ,
                                                  "duration": round(len(audio) / SR, 3), "pieces": pieces},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{out}: {len(audio) / SR:.1f} s, {sum(p['kind'] == 'keep' for p in pieces)} lines to keep, "
          f"{sum(p['kind'] != 'keep' for p in pieces)} to cut")


if __name__ == "__main__":
    main()

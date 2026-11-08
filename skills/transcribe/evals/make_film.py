"""Make a test film with known words and known pauses (Microsoft Edge voices, via the edge-tts package).

  python make_film.py vi_tips    # or en_tips; writes <name>.mp4 in the current folder

Needs: pip install edge-tts, FFmpeg, network access to Microsoft's speech service. No media is stored in this
repository; the films are made fresh for each run.
"""
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

import edge_tts

FILMS = {
    "vi_tips": ("vi-VN-HoaiMyNeural", [
        ("Xin chào, mình là Minh Anh. Hôm nay mình chia sẻ ba cách tiết kiệm thời gian khi dựng video.", 1.2),
        ("Ờ, cách thứ nhất là cắt bỏ những khoảng lặng dài hơn bốn trăm mi li giây.", 0.8),
        ("Cách thứ hai, ừm, là dùng phụ đề có thời gian của từng từ.", 1.5),
        ("Cách thứ ba là chọn đoạn quay tốt nhất.", 0.6),
        ("Cách thứ ba là chọn đoạn quay tốt nhất khi bạn nói lại một câu.", 0.9),
        ("Video này dài khoảng bốn mươi lăm giây và được dựng bằng Edit Atlas.", 0.0),
    ]),
    "en_tips": ("en-US-GuyNeural", [
        ("Hi, I'm Priya Raman, and today I'll show you three ways to edit faster.", 1.0),
        ("Um, the first one is cutting every pause longer than four hundred milliseconds.", 0.7),
        ("The second, uh, is captions with a time for every single word.", 1.6),
        ("The third is picking the best take.", 0.5),
        ("The third is picking the best take when you say a line twice.", 0.8),
        ("This video saved our team about 2,500 dollars last quarter.", 0.0),
    ]),
}


async def say(voice, text, path):
    for _ in range(5):
        try:
            await edge_tts.Communicate(text, voice).save(str(path))
            return
        except Exception:
            await asyncio.sleep(3)
    sys.exit("edge-tts did not answer")


def main():
    name = sys.argv[1]
    voice, parts = FILMS[name]
    tmp = Path(tempfile.mkdtemp())
    pieces, total = [], 0.0
    for i, (text, pause) in enumerate(parts):
        mp3, wav = tmp / f"{i}.mp3", tmp / f"{i}.wav"
        asyncio.run(say(voice, text, mp3))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", mp3, "-ar", "48000", "-ac", "1", wav], check=True)
        pieces.append(wav)
        total += float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", wav],
                                      capture_output=True, text=True).stdout)
        if pause:
            sil = tmp / f"{i}s.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", str(pause), sil], check=True)
            pieces.append(sil)
            total += pause
    (tmp / "list.txt").write_text("".join(f"file '{p.as_posix()}'\n" for p in pieces), encoding="utf-8")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", tmp / "list.txt", "-c", "copy", tmp / "voice.wav"], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x223344:s=1080x1920:r=30:d={total:.3f}",
                    "-i", tmp / "voice.wav", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest",
                    f"{name}.mp4"], check=True)
    print(f"{name}.mp4: {total:.1f} s")


if __name__ == "__main__":
    main()

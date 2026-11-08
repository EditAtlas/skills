"""Check what transcription needs on this machine, and install it only when told to.

  doctor.py                    # report: Python, FFmpeg, faster-whisper, GPU, models already downloaded
  doctor.py --install          # pip install faster-whisper (ask the person first: about 300 MB on disk)
  doctor.py --fetch turbo      # download a model now instead of on first use (sizes below)

Exit code 0 when transcribe.py can run, 1 when something is missing.
"""
import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

# huggingface_hub warns on Windows that it cannot make symlinks; the download still works, and the warning
# read as a failure to a fresh-machine tester.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# No import from common.py: it needs numpy, which only arrives with faster-whisper, and this script must run on a
# Python that has neither (found by a fresh-machine install test).


def utf8_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

# Name -> (Hugging Face repo, download size). faster-whisper downloads on first use into the Hugging Face cache.
MODELS = {
    "small": ("Systran/faster-whisper-small", "about 0.5 GB"),
    "medium": ("Systran/faster-whisper-medium", "about 1.5 GB"),
    "turbo": ("mobiuslabsgmbh/faster-whisper-large-v3-turbo", "about 1.6 GB"),
    "large-v3": ("Systran/faster-whisper-large-v3", "about 3.1 GB"),
}


def hf_cache():
    base = os.environ.get("HF_HUB_CACHE") or os.path.join(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface", "hub")
    return Path(base)


def cached_models():
    root = hf_cache()
    found = []
    for name, (repo, _) in MODELS.items():
        folder = root / ("models--" + repo.replace("/", "--"))
        if any(folder.glob("snapshots/*/model.bin")):
            found.append(name)
    return found


def gpu_count():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count()
    except Exception:
        return 0


def main():
    utf8_stdout()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--install", action="store_true", help="pip install faster-whisper into this Python")
    p.add_argument("--fetch", choices=list(MODELS), help="download this model now")
    a = p.parse_args()

    ok = True
    print(f"python: {sys.version.split()[0]} at {sys.executable}")
    if sys.version_info < (3, 9):
        print("  needs Python 3.9 or newer"); ok = False
    for tool in ("ffmpeg", "ffprobe"):
        where = shutil.which(tool)
        print(f"{tool}: {where or 'MISSING: install FFmpeg and open a new terminal'}")
        ok = ok and bool(where)

    have = importlib.util.find_spec("faster_whisper") is not None
    if not have and a.install:
        print("installing faster-whisper ...")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "faster-whisper"], capture_output=True, text=True)
        print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip()[-500:])
        have = importlib.util.find_spec("faster_whisper") is not None
    if have:
        import faster_whisper
        print(f"faster-whisper: {faster_whisper.__version__}")
    else:
        print("faster-whisper: MISSING. Ask the person, then run doctor.py --install (pip, about 300 MB on disk, under a minute on a fast line). "
              "It runs Whisper on this machine; no audio leaves it.")
        ok = False

    gpus = gpu_count() if have else 0
    print(f"NVIDIA GPU for Whisper: {gpus or 'none (CPU, int8)'}; CPU threads: {os.cpu_count()}")
    cached = cached_models()
    print("models downloaded: " + (", ".join(cached) if cached else "none yet"))
    for name, (repo, size) in MODELS.items():
        print(f"  {name:<9} {size:<13} {repo}")
    print("recommended: " + ("turbo (GPU)" if gpus else "turbo for Vietnamese and short films; small for long English on a slow CPU"))

    if a.fetch:
        if not have:
            sys.exit("install faster-whisper first")
        from faster_whisper.utils import download_model
        repo, size = MODELS[a.fetch]
        print(f"downloading {a.fetch} ({size}) ...")
        print("->", download_model(repo))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()

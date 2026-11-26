# Third-party notices

## Ideas and measurements

`skills/sound-design` restates, in its own words, measurements and rules published with the
[real-sfx](https://github.com/Clipwing/skills/tree/main/skills/real-sfx) skill by Alexander Korbanov at Clipwing:
the pace of finished SFX-only reels, the level of a background bed, and the practice of a numeric self-check with a
list of moments to listen to. No code from real-sfx is included in this repository.

`skills/video-check` restates, in its own words, two rules from the text audit of
[take-one](https://github.com/talsiach/take-one) (MIT): text under about 6.7 px on a phone 360 px wide is too small,
and a text needs about 0.4 s plus 0.2 s a word on screen. Its checks of claimed fixes, judging by kind of video
and frame strips around cuts follow ideas from take-one and [uncut](https://github.com/blazejkustra/uncut) (MIT).
No code from either project is included in this repository.

`skills/media-picker/scripts/place.py` follows ideas from the B-roll planner and colour match of
[Yap Studio](https://github.com/cathrynlavery/yap-studio) by Cathryn Lavery (Apache License 2.0): starting a clip
just before the word that names it, keeping it between a shortest and a longest length, ending it at a phrase end,
moving a clip's colour only part of the way (0.7) toward the speaker's shot, and keeping overlays and captions off a
head box made larger than the face. The code and the numbers chosen are our own; no code from Yap Studio is included
in this repository.

`skills/media-picker/scripts/highlights.py` and `look.py` follow ideas from
[Editroom](https://github.com/robbietilton/Editroom) by Robbie Tilton (MIT): scoring frame samples for focus,
exposure, colour and steadiness and taking the best windows round-robin across clips in the order they were filmed,
shots of whole beats in a long and short pattern that end on a bar with the song starting on a bar where it lifts,
frames of a clip in a grid marked with their times, and short notes of what an agent saw in a file kept so it need
not look again. The code and the numbers chosen are our own; no code from Editroom is included in this repository.

`skills/talking-head-cut/scripts/takes.py` and `cut.py` follow the multi-take idea of
[video-use](https://github.com/browser-use/video-use) (MIT): lines from every take listed together, and a cut
plan that quotes each take it keeps with the reason. No code from video-use is included in this repository.
Its speech detector for music under the voice is the Silero VAD model (MIT) that faster-whisper already
installs; the skill does not bundle it.

`skills/sound-design/scripts/realsfx_library.py` writes a library folder that real-sfx can read. Using real-sfx
itself is subject to its own terms.

`skills/transcribe/scripts/align.py` follows the approach of
[WhisperX](https://github.com/m-bain/whisperX) (`whisperx/alignment.py`): Whisper's text is laid on the frames of a
wav2vec2 CTC model one Whisper segment at a time, characters the model does not know go to a wildcard, and words
without alignable characters take their time from their neighbours. The CTC alignment in align.py is a separate numpy
implementation, not a copy of WhisperX code. WhisperX is distributed under this license:

> BSD 2-Clause License
>
> Copyright (c) 2024, Max Bain
>
> Redistribution and use in source and binary forms, with or without modification, are permitted provided that the
> following conditions are met:
>
> 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following
>    disclaimer.
> 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the
>    following disclaimer in the documentation and/or other materials provided with the distribution.
>
> THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
> INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
> DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
> SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
> SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
> WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
> OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

## Models

Skills download models at run time and store none here. `skills/transcribe` downloads Whisper models through
faster-whisper, and, for word alignment in English, `Xenova/wav2vec2-base-960h` from Hugging Face (an ONNX copy of
`facebook/wav2vec2-base-960h`, Apache-2.0), pinned to one revision.

## Sounds

Skills download sounds at run time from the public
[EditAtlas/sfx](https://github.com/EditAtlas/sfx) repository. No sound files are stored here.

## Runtime dependencies

Skills call, but do not bundle: Python, numpy, Pillow, PyYAML (validation only), Playwright, cryptography, OpenCV (optional, only if already installed), FFmpeg, and
faster-whisper with onnxruntime and huggingface_hub. Each is used under its
own license.

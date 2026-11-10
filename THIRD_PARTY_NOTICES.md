# Third-party notices

## Ideas and measurements

`skills/sound-design` restates, in its own words, measurements and rules published with the
[real-sfx](https://github.com/Clipwing/skills/tree/main/skills/real-sfx) skill by Alexander Korbanov at Clipwing:
the pace of finished SFX-only reels, the level of a background bed, and the practice of a numeric self-check with a
list of moments to listen to. No code from real-sfx is included in this repository.

`skills/sound-design/scripts/realsfx_library.py` writes a library folder that real-sfx can read. Using real-sfx
itself is subject to its own terms.

## Sounds

Skills download sounds at run time from the public
[EditAtlas/sfx](https://github.com/EditAtlas/sfx) repository. No sound files are stored here.

## Runtime dependencies

Skills call, but do not bundle: Python, numpy, Pillow, PyYAML (validation only), Playwright, cryptography and FFmpeg. Each is used under its
own license.

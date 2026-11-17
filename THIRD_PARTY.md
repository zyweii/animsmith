# Third-party code

animsmith is MIT-licensed (see `LICENSE`). It includes the following files from another project, used under its
licence.

## vfxmith 0.1.6, by Frxctured (MIT)

| File | What it does here |
|---|---|
| `kit/scripts/rbxdump.py` | Decodes Roblox `.rbxm`/`.rbxl` (binary) and `.rbxmx`/`.rbxlx` (XML) files offline, without Studio; nothing in the file runs. animsmith reads KeyframeSequences out of animation files with it. |
| `kit/scripts/rbxcut.py` | Cuts one subtree out of a Roblox file into a clean `.rbxmx` with every script removed. |

Each file carries a header line naming its source. Changes made for animsmith, if any, are marked in the file.

Licence text (vfxmith's `LICENSE`):

```
MIT License

Copyright (c) 2026 Frxctured

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Not included

No reference media, animation data, models or places from any game are in this repository. References the user
studies stay in their private vault; keys decoded from a third-party file are study material only and are never
exported or shipped.

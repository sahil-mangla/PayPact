# Third-party notices

PayPact is licensed under the Apache License 2.0 (see `LICENSE`). It includes or depends on
the following third-party material that carries its own notice.

## webgl-noise (simplex noise shader)

`frontend/src/components/ui/ParticleMorphOrb.tsx` contains a GLSL 3D simplex noise function
(`permute`, `taylorInvSqrt`, `snoise`) that follows the `webgl-noise` library by Ashima Arts
and Ian McEwan, <https://github.com/ashima/webgl-noise>.

```
Copyright (C) 2011 Ashima Arts. All rights reserved.
Authors: Ian McEwan, Ashima Arts.

Distributed under the MIT License.

Permission is hereby granted, free of charge, to any person obtaining a copy of this software
and associated documentation files (the "Software"), to deal in the Software without
restriction, including without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING
BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## npm and PyPI dependencies

Runtime dependencies are installed from their registries under their own licenses (permissive
licenses and MPL-2.0 at the time of writing). Run `npm ls` and `pip list` for the full set.

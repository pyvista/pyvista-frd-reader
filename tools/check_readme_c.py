#!/usr/bin/env python3
"""Compile and link the C example in the README against the real library.

A README that shows a C API is making a claim about that API's spelling, and
prose does not go stale loudly. Renaming ``pvfrd_array_data`` would redden the
gtest tier and leave the README quietly wrong -- which is worse than no
example, because someone would copy it.

The block is a fragment, so it is wrapped in a ``main`` before compiling.
Compiled *and linked*, not merely parsed: a declaration the header carries but
the library never defines would pass a syntax check and fail the first person
to build against it.

Usage: check_readme_c.py INCLUDE_DIR LIBRARY
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def extract() -> str:
    """Return the single ``.. code:: c`` block in the README."""
    text = (ROOT / 'README.rst').read_text()
    blocks = re.findall(r'\.\. code:: c\n\n((?:(?:   .*)?\n)+)', text)
    if len(blocks) != 1:
        msg = (
            f'expected exactly one C block in README.rst, found {len(blocks)}. '
            f'If a second example was added, teach this script to check both '
            f'rather than letting it check only the first.'
        )
        raise SystemExit(msg)
    return '\n'.join(line[3:] for line in blocks[0].splitlines())


def main() -> int:
    try:
        include_dir, library = sys.argv[1:]
    except ValueError:
        raise SystemExit(__doc__) from None

    body = extract()
    includes = [ln for ln in body.splitlines() if ln.startswith('#include')]
    rest = [ln for ln in body.splitlines() if not ln.startswith('#include')]
    source = (
        '\n'.join(includes)
        + '\n\nint main(void) {\n'
        + '\n'.join('  ' + ln if ln.strip() else ln for ln in rest)
        + '\n  return 0;\n}\n'
    )

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'readme_example.c'
        src.write_text(source)
        cmd = [
            'cc',
            '-std=c11',
            '-Wall',
            '-Wextra',
            # The example declares values to show what the calls return and
            # then, being an excerpt, does nothing with them.
            '-Wno-unused-variable',
            '-Wno-unused-but-set-variable',
            f'-I{include_dir}',
            str(src),
            library,
            # A static libpvfrd carries no link dependencies of its own, so a
            # C consumer has to name them: the C++ runtime, and libm for the
            # square roots in the derived quantities. The README says so, and
            # this is where that sentence is checked.
            '-lstdc++',
            '-lm',
            '-o',
            str(Path(tmp) / 'readme_example'),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            sys.stderr.write(source)
            sys.stderr.write('\n' + result.stdout + result.stderr)
            print("::error::the README's C example no longer builds")
            return 1

    print("the README's C example compiles and links against the built library")
    return 0


if __name__ == '__main__':
    sys.exit(main())

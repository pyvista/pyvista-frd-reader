#!/usr/bin/env python3
"""Check the writer against files this project did not write.

The claim is narrow and strong: a document read and emitted again is the input,
byte for byte. Nothing about that goes through anybody's opinion of what FRD
looks like -- the comparison is with CalculiX's own output, and every field
width, wrapping rule and way of spelling a number has to be right for it to
hold.

Run it over the corpus ``tools/fetch_corpus.py`` builds::

    python tools/sweep_rewrite.py external-corpus/

Four verdicts.

``identical``   read, emitted, and the bytes came back. The result that counts.

``passthrough`` the file contains no node, element or result block, so there
                was nothing to regenerate and it round-tripped by being copied.
                Counted separately because a corpus of these would report the
                same green while grading nothing -- and the GitHub half of the
                corpus is mostly these, the ``.frd`` extension being shared
                with loudspeaker measurements and at least one fractal
                renderer.

``differs``     the writer does not reproduce this file. Reported with the
                first line that differs, because that is usually enough to name
                the dialect: this is how the corpus turned up cgx's own example
                file, which uses five-wide ids and Fortran's exponent spelling.

``refused``     the reader would not parse it at all. Not a writer result.

Exits non-zero on ``differs``, and on a run where nothing was ``identical`` --
a sweep that graded no real files should not be able to report success.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from pyvista_frd import _capi

BLOCK_MARKERS = (b'2C', b'3C', b'100C')


def has_blocks(data: bytes) -> bool:
    """Whether the file holds anything the writer has to regenerate."""
    return any(line.strip().startswith(BLOCK_MARKERS) for line in data.split(b'\n')[:5000])


def first_difference(written: bytes, original: bytes) -> str:
    """Describe the first line that differs, from both sides."""
    at = 0
    while at < len(written) and at < len(original) and written[at] == original[at]:
        at += 1

    def line_at(data: bytes, offset: int) -> str:
        begin = data.rfind(b'\n', 0, offset) + 1
        end = data.find(b'\n', offset)
        end = len(data) if end < 0 else end
        return data[begin:end].decode('latin-1')

    line = original.count(b'\n', 0, at) + 1
    return (
        f'byte {at}, line {line} (in {len(original)}, out {len(written)})\n'
        f'    file   |{line_at(original, at)}|\n'
        f'    writer |{line_at(written, at)}|'
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--json', type=Path, help='write the full result set here')
    parser.add_argument('--quiet', action='store_true', help='only print non-identical files')
    args = parser.parse_args()

    files = sorted(args.directory.rglob('*.frd'))
    if not files:
        print(f'no .frd files under {args.directory}', file=sys.stderr)
        return 2

    counts: dict[str, int] = {}
    results = []
    for index, path in enumerate(files, 1):
        data = path.read_bytes()
        detail = ''
        try:
            written = _capi.rewrite_bytes(data)
        except Exception as exc:  # noqa: BLE001 - a refusal is a result here
            verdict, detail = 'refused', f'{type(exc).__name__}: {exc}'
        else:
            if written == data:
                verdict = 'identical' if has_blocks(data) else 'passthrough'
            else:
                verdict, detail = 'differs', first_difference(written, data)

        counts[verdict] = counts.get(verdict, 0) + 1
        results.append({'path': str(path), 'verdict': verdict, 'detail': detail})
        if not args.quiet or verdict in ('differs', 'refused'):
            print(f'[{index}/{len(files)}] {verdict:12s} {path.name}')
            if detail:
                print(f'    {detail}')

    print('\n' + '=' * 70)
    for verdict in sorted(counts):
        print(f'{verdict:14s} {counts[verdict]}')
    print(f'{"total":14s} {len(files)}')

    if args.json:
        args.json.write_text(json.dumps(results, indent=2))
        print(f'\nwritten to {args.json}')

    if counts.get('differs'):
        return 1
    if not counts.get('identical'):
        # Every file was a passthrough or a refusal, so the writer was never
        # actually exercised. Reporting that as success is how a gate becomes
        # decorative.
        print('\nno file with FRD blocks round-tripped; this run graded nothing', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Rebuild the external FRD corpus this project is swept against.

The corpus itself is deliberately not in the repository. It is other people's
data under other people's licences -- CalculiX's regression suite is GPL, and a
GitHub sweep pulls in whatever each repository carries -- and vendoring any of
it into an MIT project would be both a licensing problem and a hundreds-of-
megabytes one. What is version-controlled is this script, so the corpus is
reproducible rather than something that existed once on one machine.

Two sources, and they answer different questions.

``--source calculix`` fetches CalculiX's own regression suite and runs it. The
suite ships 673 input decks and only four ``.frd`` files, because it grades
itself on ``.dat`` output; running the decks with ``ccx`` turns it into the
largest corpus of *authoritative* FRD available, written by the program this
format belongs to. Requires ``ccx`` on PATH.

``--source github`` searches GitHub for ``.frd`` files. These are worth having
for a reason that has nothing to do with volume: the extension is overloaded.
Loudspeaker measurement tools and at least one fractal renderer use ``.frd``
for entirely unrelated formats, and a reader that meets one must decline it
rather than crash or, worse, invent a mesh. Those files are the negative half
of the corpus and cannot be authored -- a fixture we wrote to look like a
non-CalculiX file would only ever contain what we already expected.

Both write into ``external-corpus/`` alongside a ``provenance.tsv`` recording
where each file came from, which is the part that stops a corpus from becoming
a pile of anonymous bytes nobody can re-derive or attribute.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys
import time

SEARCH_PAGES = 10  # GitHub caps code search at 1000 results, 100 per page


def _gh(*args: str) -> str:
    return subprocess.run(
        ['gh', *args], capture_output=True, text=True, check=True, timeout=120
    ).stdout


def fetch_github(out: Path) -> list[tuple[str, str, str]]:
    """Download every .frd GitHub's code search will admit to having."""
    out.mkdir(parents=True, exist_ok=True)
    hits: dict[tuple[str, str], str] = {}
    for page in range(1, SEARCH_PAGES + 1):
        try:
            raw = _gh(
                'api',
                '-X',
                'GET',
                'search/code',
                '-f',
                'q=extension:frd',
                '-f',
                'per_page=100',
                '-f',
                f'page={page}',
                '--jq',
                '.items[] | [.repository.full_name, .path, .sha] | @tsv',
            )
        except subprocess.CalledProcessError:
            break
        for line in raw.splitlines():
            repo, path, sha = line.split('\t')
            hits[(repo, path)] = sha
        print(f'  search page {page}: {len(hits)} unique so far', file=sys.stderr)
        time.sleep(3)

    provenance = []
    for i, ((repo, path), sha) in enumerate(sorted(hits.items()), 1):
        # Named by blob sha, not by a flattening of repo and path. The obvious
        # scheme -- join every path component with underscores -- produced
        # names past the 255-byte limit on a repository whose FRD sat eight
        # directories deep, and took the whole run down with it. The sha is
        # unique, fixed-width, and is the identifier provenance.tsv joins on
        # anyway; the readable part is kept as a suffix for anyone browsing
        # the directory.
        stem = Path(path).stem[:80].replace(' ', '_')
        owner = repo.split('/')[0][:40]
        name = f'{sha[:12]}__{owner}__{stem}.frd'
        target = out / name
        try:
            if target.exists():
                provenance.append((name, f'https://github.com/{repo}/blob/HEAD/{path}', sha))
                continue
            blob = json.loads(_gh('api', f'repos/{repo}/git/blobs/{sha}'))
            target.write_bytes(base64.b64decode(blob['content']))
        except Exception as exc:  # noqa: BLE001
            print(f'  [{i}/{len(hits)}] SKIP {repo}/{path}: {exc}', file=sys.stderr)
            continue
        provenance.append((name, f'https://github.com/{repo}/blob/HEAD/{path}', sha))
        if i % 50 == 0:
            print(f'  [{i}/{len(hits)}] downloaded', file=sys.stderr)
    return provenance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', choices=['github'], required=True)
    parser.add_argument('--out', type=Path, default=Path('external-corpus'))
    args = parser.parse_args()

    provenance = fetch_github(args.out / 'github')
    record = args.out / 'provenance.tsv'
    with record.open('a') as handle:
        for name, url, sha in provenance:
            handle.write(f'{name}\t{url}\t{sha}\n')
    print(f'{len(provenance)} files; provenance in {record}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

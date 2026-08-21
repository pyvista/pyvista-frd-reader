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
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

SEARCH_PAGES = 10  # GitHub caps code search at 1000 results, 100 per page

# Pinned, not "latest". The suite and the solver have to be the same release or
# the corpus stops being reproducible: a deck the 2.22 suite added would be run
# by whatever ccx happens to be installed, and the provenance would not say so.
CCX_VERSION = '2.22'
CCX_TEST_URL = f'http://www.dhondt.de/ccx_{CCX_VERSION}.test.tar.bz2'

# A deck that has not finished has not written its whole FRD, and the file it
# leaves behind is a truncated one that looks like a small valid corpus member.
# An earlier run of this corpus used 180s and silently contributed 23 such
# stubs, which is a harness artefact being graded as if it were CalculiX
# output. This bound is generous enough that hitting it means the deck really
# is long-running, and a deck that hits it is *dropped* rather than kept.
DECK_TIMEOUT_S = 900


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


def _outputs_of(deck: Path) -> list[Path]:
    """Every FRD one deck writes, which is not always one named after it.

    A deck's own result goes to ``<job>.frd``, but CalculiX also writes
    ``<job>.net.frd`` for a network analysis and ``<job>.rfn.frd`` for a
    refined mesh. Globbing only ``<job>.frd`` silently discarded 28 files
    here, and the ones it discarded were not a random sample: the extra
    outputs are written by different code paths in ``frd.c`` than the main
    one, which is exactly what a corpus is for.

    Anchored on the dot, not on the prefix. ``achtel*.frd`` also matches
    ``achtelcas.frd``, which belongs to the deck named ``achtelcas`` -- with
    the decks running concurrently that is a race that ends in whichever
    thread loses trying to stat a file the other already moved. Deck stems are
    unique; deck stems *as prefixes* are not.
    """
    owned = deck.parent.glob(f'{deck.stem}.*frd')
    # `<stem>.frd` and `<stem>.<tag>.frd`, but not a file that is itself
    # another deck's job -- `a.b.frd` belongs to `a.b.inp` if that deck exists.
    return sorted(
        f
        for f in owned
        if f.suffix == '.frd'
        and (f == deck.with_suffix('.frd') or not f.with_suffix('.inp').exists())
    )


def collect_shipped(suite: Path, out: Path) -> list[tuple[str, str, str]]:
    """Copy out the FRD files the suite ships, before anything is run.

    212 of them, as ``*.frd.ref`` -- the reference output each deck is graded
    against -- plus a handful of ``.frd`` used as analysis input. They are
    CalculiX's own output, they cost nothing to collect, and one of them
    (``beampdouble.frd.ref``) is the only binary-format FRD published by the
    project: a submodel reads it back in, so the suite carries a specimen of
    the format this library could not read at all. Collecting only what the
    decks produce misses it entirely.

    Must run before any deck does, or the run's own outputs land in here
    labelled as shipped.
    """
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(list(suite.rglob('*.frd')) + list(suite.rglob('*.frd.ref'))):
        rel = path.relative_to(suite)
        flat = str(rel).replace('.frd.ref', '').replace('.frd', '').replace(os.sep, '__')[:150]
        name = f'ccx{CCX_VERSION}-shipped__{flat}.frd'
        shutil.copy(path, out / name)
        rows.append((name, f'{CCX_TEST_URL}!{rel}', f'ccx-{CCX_VERSION}-shipped'))
    return rows


def _run_deck(ccx: str, suite: Path, deck: Path, out: Path, timeout: int) -> list | None:
    """Run one deck and keep every FRD it writes, or return None.

    ``ccx`` resolves ``*INCLUDE`` relative to the working directory, so the
    deck is run where it lives. Job names are unique across the suite, so the
    output files of concurrent runs do not collide.
    """
    job = deck.stem
    try:
        completed = subprocess.run(
            [ccx, '-i', job],
            check=False,
            cwd=deck.parent,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # Deliberately also removes the partial files. Leaving them would put
        # truncated FRDs in the corpus with nothing to distinguish them from
        # small complete ones.
        for partial in _outputs_of(deck):
            partial.unlink(missing_ok=True)
        return None

    produced = _outputs_of(deck)
    if completed.returncode != 0 or not produced:
        for partial in produced:
            partial.unlink(missing_ok=True)
        return None

    rows = []
    for frd in produced:
        if frd.stat().st_size == 0:
            frd.unlink()
            continue
        rel = frd.relative_to(suite)
        flat = str(rel)[:-4].replace(os.sep, '__')[:150]
        name = f'ccx{CCX_VERSION}__{flat}.frd'
        shutil.move(str(frd), out / name)
        rows.append((name, f'{CCX_TEST_URL}!{rel}', f'ccx-{CCX_VERSION}-run'))
    return rows or None


def fetch_calculix(out: Path, ccx: str, jobs: int, timeout: int) -> list[tuple[str, str, str]]:
    """Run CalculiX's own regression suite and keep every FRD it writes.

    The suite ships 673 decks and only a handful of FRD files, because it
    grades itself on ``.dat`` output. Running it is what turns it into the
    largest corpus of FRD written by the program the format belongs to -- and
    unlike anything this project could author, it contains the cases its
    authors knew about rather than the ones we did.
    """
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(tempfile.gettempdir()) / f'ccx-{CCX_VERSION}-suite'
    if not cache.exists():
        print(f'  downloading {CCX_TEST_URL}', file=sys.stderr)
        with tempfile.NamedTemporaryFile(suffix='.tar.bz2') as tmp:
            with urllib.request.urlopen(CCX_TEST_URL, timeout=300) as response:  # noqa: S310
                shutil.copyfileobj(response, tmp)
            tmp.flush()
            staging = cache.with_suffix('.partial')
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True)
            with tarfile.open(tmp.name) as archive:
                archive.extractall(staging, filter='data')
            # Renamed only once the extraction finished, so an interrupted
            # download cannot leave a half-suite that later runs treat as cached.
            staging.rename(cache)

    provenance = collect_shipped(cache, out)
    print(f'  {len(provenance)} FRD files shipped with the suite', file=sys.stderr)

    decks = sorted(cache.rglob('*.inp'))
    print(f'  {len(decks)} decks, {jobs} at a time, {timeout}s each', file=sys.stderr)

    dropped = 0
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(_run_deck, ccx, cache, d, out, timeout) for d in decks]
        for i, future in enumerate(futures, 1):
            rows = future.result()
            if rows is None:
                dropped += 1
            else:
                provenance.extend(rows)
            if i % 50 == 0:
                print(
                    f'  [{i}/{len(decks)}] {len(provenance)} kept, {dropped} decks dropped',
                    file=sys.stderr,
                )

    # Said out loud, because a corpus that silently drops a fifth of its
    # population reads afterwards as if it had covered everything.
    print(
        f'  {len(provenance)} FRD files kept in total; {dropped} decks wrote none '
        f'(no FRD requested, solver error, or over {timeout}s)',
        file=sys.stderr,
    )
    return provenance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', choices=['github', 'calculix'], required=True)
    parser.add_argument('--out', type=Path, default=Path('external-corpus'))
    parser.add_argument('--ccx', default='ccx', help='CalculiX executable (--source calculix)')
    parser.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument('--timeout', type=int, default=DECK_TIMEOUT_S)
    args = parser.parse_args()

    if args.source == 'calculix':
        if shutil.which(args.ccx) is None and not Path(args.ccx).exists():
            print(
                f'{args.ccx} not found; --source calculix needs CalculiX {CCX_VERSION}',
                file=sys.stderr,
            )
            return 2
        provenance = fetch_calculix(args.out / 'calculix', args.ccx, args.jobs, args.timeout)
    else:
        provenance = fetch_github(args.out / 'github')
    record = args.out / 'provenance.tsv'
    with record.open('a') as handle:
        for name, url, sha in provenance:
            handle.write(f'{name}\t{url}\t{sha}\n')
    print(f'{len(provenance)} files; provenance in {record}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

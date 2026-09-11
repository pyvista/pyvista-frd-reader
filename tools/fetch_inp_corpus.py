#!/usr/bin/env python3
"""Fetch public INP decks and FRD references for file-interoperability tests.

Keep companion paths intact so INCLUDE works. No solver is run. External data
retains its upstream license and stays outside the committed test fixtures.
Requires the GitHub CLI for public repository tree listings. The generated
manifest records URLs, revisions, hashes, byte counts, and download failures.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import urllib.parse
import urllib.request

SOURCES = [
    ('calculix/gmsh2ccx', '50f9c32283a02a6205e7e6acda7824de8a34b09a', ''),
    ('cristobaltapia/pybaqus', '0bb362856910855ee4e6fc997b1dfc1153020e18', ''),
    ('gbroques/ccxmeshreader', '1ba48c3c6404849962301cf0aca5c76ff45536dc', ''),
    ('precice/tutorials', 'fb266dd9b8bc9caad940921fa43236c600ed9e7e', ''),
    ('precice/community-training', '4238040aa73315e5fe31554b81c71e03fea21230', ''),
    ('calculix/examples', 'a079253398c05f96b019e8c07ce076e370ddeb75', ''),
    ('calculix/CalculiX-Examples', '316273e9105e44ce7e3ee05059dac1bc3f256a69', ''),
    ('FreeCAD/FreeCAD', '0919323548ddab8d6d8607f02ee5da7faa234fc5', 'src/Mod/Fem/femtest/'),
]
ARCHIVE_HASHES = {
    '2.22': '804c1ab099f5694b67955ddd72ad4708061019298c5d1d1788bf404d900b86fc',
    '2.23': 'be2259fd9a7b990d0453b30708e1b05f2cd4b6df4a90fa96f0e4abd1ae7beaa0',
}
EXTENSIONS = {
    '.inp',
    '.frd',
    '.ref',
    '.nam',
    '.msh',
    '.sur',
    '.inc',
    '.equ',
    '.bou',
    '.dlo',
    '.dfl',
    '.clo',
    '.flm',
}


def download(out, relative, url, source):
    target = out / relative
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310
                data = response.read()
            temporary = target.with_name(target.name + '.download')
            temporary.write_bytes(data)
            temporary.replace(target)
        data = target.read_bytes()
        return {
            'path': relative,
            'url': url,
            'source': source,
            'sha256': hashlib.sha256(data).hexdigest(),
            'bytes': len(data),
        }
    except (OSError, ValueError) as exc:
        return {'path': relative, 'url': url, 'error': str(exc)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('external-corpus'))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for repo, revision, prefix in SOURCES:
        tree = json.loads(
            subprocess.run(
                ['gh', 'api', f'repos/{repo}/git/trees/{revision}?recursive=1'],
                capture_output=True,
                text=True,
                check=True,
                timeout=120,
            ).stdout
        )
        if tree.get('truncated'):
            msg = f'{repo}: GitHub truncated the tree; refusing an incomplete inventory'
            raise RuntimeError(msg)
        hits = [
            entry['path']
            for entry in tree['tree']
            if entry['type'] == 'blob'
            and entry['path'].startswith(prefix)
            and (
                Path(entry['path']).suffix.lower() in EXTENSIONS
                or Path(entry['path']).name.lower().startswith(('license', 'copying'))
            )
        ]
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = [
                pool.submit(
                    download,
                    args.out,
                    repo.replace('/', '__') + '/' + path,
                    f'https://raw.githubusercontent.com/{repo}/{revision}/{urllib.parse.quote(path)}',
                    revision,
                )
                for path in hits
            ]
            manifest.extend(future.result() for future in futures)
        print(f'{repo}: {len(hits)} files', flush=True)

    for version in ('2.22', '2.23'):
        name = f'ccx_{version}.test.tar.bz2'
        row = download(args.out, name, f'https://www.dhondt.de/{name}', version)
        manifest.append(row)
        if 'error' not in row and row['sha256'] != ARCHIVE_HASHES[version]:
            row['error'] = 'Archive checksum mismatch; not extracted'
        if 'error' not in row:
            destination = args.out / f'ccx-{version}'
            with tarfile.open(args.out / name) as archive:
                archive.extractall(destination, filter='data')
            for path in sorted(destination.rglob('*')):
                if path.is_file():
                    data = path.read_bytes()
                    manifest.append(
                        {
                            'path': str(path.relative_to(args.out)),
                            'url': row['url'] + '!' + str(path.relative_to(destination)),
                            'source': row['sha256'],
                            'sha256': hashlib.sha256(data).hexdigest(),
                            'bytes': len(data),
                        }
                    )
        print(f'CalculiX {version}: {row.get("bytes", row.get("error"))}', flush=True)
    record = args.out / 'inp-download-manifest.json'
    record.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    failures = sum('error' in row for row in manifest)
    print(f'{len(manifest)} records; {failures} download failures; {record}')
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Discover surface datasets on GitHub and fetch their companion files.

Search is bounded by GitHub's 1,000-result cap per query. The manifest records
query totals, incomplete responses, pinned repository revisions, URLs and file
hashes. Matching directories (including subdirectories) are fetched so INP,
FRD and include files stay together. Duplicate Git blobs share a download cache.
No downloaded code or solver is executed.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.parse
import urllib.request

from fetch_inp_corpus import EXTENSIONS

QUERIES = ['extension:inp SURFACE calculix', 'extension:sur SURFACE', 'extension:inp SPOS ccx']


def gh(endpoint):
    return json.loads(
        subprocess.run(
            ['gh', 'api', endpoint], check=True, capture_output=True, text=True, timeout=120
        ).stdout
    )


def fetch(out, repo, revision, entry):
    relative = repo.replace('/', '__') + '/' + entry['path']
    url = f'https://raw.githubusercontent.com/{repo}/{revision}/{urllib.parse.quote(entry["path"])}'
    target = out / relative
    cache = out / '.blobs' / entry['sha']
    try:
        if not cache.exists():
            with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310
                data = response.read()
            digest = hashlib.sha1(
                f'blob {len(data)}\0'.encode() + data, usedforsecurity=False
            ).hexdigest()
            if digest != entry['sha']:
                msg = 'Downloaded bytes do not match the Git tree blob'
                raise ValueError(msg)  # noqa: TRY301 - record download failures
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(data)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            os.link(cache, target)
        data = target.read_bytes()
        digest = hashlib.sha1(
            f'blob {len(data)}\0'.encode() + data, usedforsecurity=False
        ).hexdigest()
        if digest != entry['sha']:
            msg = 'Cached or existing bytes do not match the Git tree blob'
            raise ValueError(msg)  # noqa: TRY301 - retain corruption in the manifest
        return {
            'path': relative,
            'url': url,
            'revision': revision,
            'blob': entry['sha'],
            'sha256': hashlib.sha256(data).hexdigest(),
            'bytes': len(data),
        }
    except (OSError, ValueError) as exc:
        return {'path': relative, 'url': url, 'error': str(exc)}


def replay(out, path):
    data = gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()
    entries = json.loads(data)
    groups = {}
    for entry in entries:
        groups.setdefault(entry['blob'], []).append(entry)

    def fetch_group(group):
        rows = []
        for item in group:
            owner, repo, revision, relative = (
                urllib.parse.urlsplit(item['url']).path.lstrip('/').split('/', 3)
            )
            rows.append(
                fetch(
                    out,
                    f'{owner}/{repo}',
                    revision,
                    {'path': urllib.parse.unquote(relative), 'sha': item['blob']},
                )
            )
        return rows

    records = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        for rows in pool.map(fetch_group, groups.values()):
            records.extend(rows)
    (out / 'manifest.json').write_text(json.dumps(records, indent=2) + '\n')
    errors = sum('error' in row for row in records)
    print(len(records), 'files;', errors, 'errors')
    return int(bool(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('external-corpus/surface-search'))
    parser.add_argument('--replay', type=Path, help='replay a pinned JSON or JSON.gz manifest')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.replay:
        return replay(args.out, args.replay)
    cache_path = args.out / 'search.json'
    if cache_path.exists():
        searches = json.loads(cache_path.read_text())
    else:
        searches = []
        for query in QUERIES:
            items = []
            pages = []
            for page in range(1, 11):
                data = gh(f'search/code?q={urllib.parse.quote(query)}&per_page=100&page={page}')
                items.extend(
                    {
                        'repo': item['repository']['full_name'],
                        'path': item['path'],
                        'blob': item['sha'],
                    }
                    for item in data['items']
                )
                pages.append(
                    {'total': data['total_count'], 'incomplete': data['incomplete_results']}
                )
                print(query, page, len(items), flush=True)
                time.sleep(7)
                if len(items) >= min(data['total_count'], 1000) or not data['items']:
                    break
            searches.append({'query': query, 'pages': pages, 'items': items})
        cache_path.write_text(json.dumps(searches, indent=2) + '\n')
    repositories = {}
    for search in searches:
        for item in search['items']:
            repositories.setdefault(item['repo'], set()).add(str(Path(item['path']).parent) + '/')
    records = []
    for repo, directories in sorted(repositories.items()):
        revision = gh(f'repos/{repo}/commits/HEAD')['sha']
        tree = gh(f'repos/{repo}/git/trees/{revision}?recursive=1')
        if tree.get('truncated'):
            msg = f'{repo}: truncated tree; refusing to imply complete coverage'
            raise RuntimeError(msg)
        entries = [
            e
            for e in tree['tree']
            if e['type'] == 'blob'
            and any(e['path'].startswith(d) or d == './' for d in directories)
            and Path(e['path']).suffix.lower() in EXTENSIONS
        ]
        # Submit a blob only once per repository to avoid concurrent cache writes.
        groups = {}
        for entry in entries:
            groups.setdefault(entry['sha'], []).append(entry)

        def fetch_group(group, repo=repo, revision=revision):
            return [fetch(args.out, repo, revision, entry) for entry in group]

        with ThreadPoolExecutor(max_workers=12) as pool:
            for rows in pool.map(fetch_group, groups.values()):
                records.extend(rows)
        print(repo, len(entries), 'files', flush=True)
        (args.out / 'manifest.json').write_text(json.dumps(records, indent=2) + '\n')
    errors = sum('error' in r for r in records)
    print(len(records), 'files,', errors, 'download errors')
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())

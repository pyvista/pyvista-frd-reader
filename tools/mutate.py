#!/usr/bin/env python3
"""Break the C++ core on purpose and check that the tests notice.

A green suite has two explanations: the code is right, or the suite cannot
see. This tells them apart. Each mutant below is a plausible mistake -- the
thing a careful reimplementation would get wrong -- applied to the source,
built, and run against both test tiers. A mutant that survives names a hole.

Usage::

    python tools/mutate.py                 # every mutant
    python tools/mutate.py --list          # names only
    python tools/mutate.py fixed-width-always-short

The sources are restored on exit, including on Ctrl-C. Do not commit while a
sweep is running: a commit in another shell would un-mutate the tree mid-run
and every remaining mutant would report as killed for the wrong reason.

One result worth knowing before reading the output: ``empty-block-kept``
removes a guard whose absence is undefined behaviour, so it is killed by the
test binary crashing rather than by an assertion. That is a kill, but a poor
one -- the sanitiser lane is what turns it into a named report. Every other
mutant here is killed by a test that says what went wrong.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Mutant:
    """One planted defect, and what is supposed to catch it."""

    name: str
    path: str
    old: str
    new: str
    expected_catcher: str
    """Which gate should redden. Recorded so a mutant killed by an unexpected
    test is visible as such -- being killed by the wrong gate usually means
    the intended one is not looking where it claims."""


MUTANTS = [
    Mutant(
        name='wedge-order-ignored',
        path='cpp/src/parse.cpp',
        old='} else if (code == PVFRD_PE6 && wedge_order == PVFRD_WEDGE_SWAP) {',
        new='} else if (false && code == PVFRD_PE6 && wedge_order == PVFRD_WEDGE_SWAP) {',
        expected_catcher='test_wedge_order_option_actually_changes_the_wedge',
    ),
    Mutant(
        name='fixed-width-always-short',
        path='cpp/src/parse.cpp',
        old='is_long_format_ = rstrip(data).size() > 50;',
        new='is_long_format_ = false;',
        expected_catcher='test_mesh_matches_reference[long_format.frd]',
    ),
    Mutant(
        name='fixed-width-always-long',
        path='cpp/src/parse.cpp',
        old='is_long_format_ = rstrip(data).size() > 50;',
        new='is_long_format_ = true;',
        expected_catcher='ParseTest.ShortFormatIdsWithNoSeparatorAreSplitAtFive',
    ),
    Mutant(
        name='element-line-off-by-one',
        path='cpp/src/parse.cpp',
        old='      element_line = reader.line_number();',
        new='      element_line = reader.line_number() + 1;',
        expected_catcher='test_warning_text_is_exact',
    ),
    Mutant(
        name='fix-scientific-disabled',
        path='cpp/src/text.h',
        old="      bool exponent = (prev == 'E' || prev == 'e' || prev == 'D' || prev == 'd');",
        new='      bool exponent = true;',
        expected_catcher='test_mesh_matches_reference[glued.frd]',
    ),
    Mutant(
        name='no-whitespace-fallback',
        path='cpp/src/parse.cpp',
        old='      if (!chunk_fixed_width(data, width, &node_ids)) {',
        new='      if (chunk_fixed_width(data, width, &node_ids) && false) {',
        expected_catcher='ParseTest.WhitespaceFallbackRescuesAPaddedWideRecord',
    ),
    Mutant(
        name='mises-reassociated',
        path='cpp/src/derived.cpp',
        old='  return sq(xx - yy) + sq(yy - zz) + sq(zz - xx) + 6.0 * (sq(xy) + sq(yz) + sq(zx));',
        new=(
            '  return sq(xx - yy) + (sq(yy - zz) + '
            '(sq(zz - xx) + 6.0 * (sq(xy) + sq(yz) + sq(zx))));'
        ),
        expected_catcher='test_arrays_match_reference[mesh.frd]',
    ),
    Mutant(
        name='strain-constant-folded',
        path='cpp/src/derived.cpp',
        old='  const double k = std::sqrt(2.0) / 3.0;',
        new='  const double k = 0.4714045207910317;',
        expected_catcher='test_arrays_match_reference[mock.frd]',
    ),
    Mutant(
        name='too-many-points-unreported',
        path='cpp/src/parse.cpp',
        old=(
            '        diagnostics_.push_back({PVFRD_DIAG_TOO_MANY_POINTS, '
            'static_cast<int32_t>(code),'
        ),
        new=(
            '        if (false) diagnostics_.push_back({PVFRD_DIAG_TOO_MANY_POINTS, '
            'static_cast<int32_t>(code),'
        ),
        expected_catcher='test_warning_text_is_exact',
    ),
    Mutant(
        name='nodes-not-sorted',
        path='cpp/src/parse.cpp',
        old='  std::sort(node_ids_.begin(), node_ids_.end());',
        new='  /* mutant: left in first-seen order */',
        expected_catcher='test_mesh_matches_reference[unsorted_nodes.frd]',
    ),
    Mutant(
        name='he20-permutation-dropped',
        path='cpp/src/parse.cpp',
        old='  if (code == PVFRD_HE20) {',
        new='  if (false && code == PVFRD_HE20) {',
        expected_catcher='test_mesh_matches_reference[elements/HE20.frd]',
    ),
    Mutant(
        name='pe15-permutation-dropped',
        path='cpp/src/parse.cpp',
        old='  } else if (code == PVFRD_PE15) {',
        new='  } else if (false && code == PVFRD_PE15) {',
        expected_catcher='test_mesh_matches_reference[elements/PE15.frd]',
    ),
    Mutant(
        name='broadcast-row-rejected',
        path='cpp/src/parse.cpp',
        old='      } else if (v.size() == 1) {',
        new='      } else if (false && v.size() == 1) {',
        expected_catcher='test_broadcast_row_matches_numpy',
    ),
    Mutant(
        name='lone-cr-not-a-newline',
        path='cpp/src/text.h',
        old="    while (i < buffer_.size() && buffer_[i] != '\\n' && buffer_[i] != '\\r') ++i;",
        new="    while (i < buffer_.size() && buffer_[i] != '\\n') ++i;",
        expected_catcher='test_newline_variants_read_identically',
    ),
    Mutant(
        name='empty-block-kept',
        path='cpp/src/parse.cpp',
        old=('    if (values.ids.empty()) continue; /* an empty block contributes no array */'),
        new='    /* mutant: empty blocks become arrays */',
        expected_catcher='ParseTest.ABlockWhoseRecordsAllFailContributesNoArray',
    ),
    Mutant(
        name='duplicate-name-appends',
        path='cpp/src/parse.cpp',
        old='      collapsed[it->second] = std::move(values);',
        new='      position.erase(it); position.emplace(block.name, collapsed.size());'
        ' order.push_back(block.name); collapsed.push_back(std::move(values));',
        expected_catcher='test_arrays_match_reference[duplicate_names.frd]',
    ),
    Mutant(
        name='partial-record-kept',
        path='cpp/src/parse.cpp',
        old='    if (!ok || values.empty()) continue;',
        new='    if (values.empty()) continue;',
        expected_catcher='test_arrays_match_reference[coverage_edge_cases.frd]',
    ),
    Mutant(
        name='unknown-element-silent',
        path='cpp/src/parse.cpp',
        old='        diagnostics_.push_back(\n            {PVFRD_DIAG_UNSUPPORTED_ELEMENT,',
        new=(
            '        if (false) diagnostics_.push_back(\n'
            '            {PVFRD_DIAG_UNSUPPORTED_ELEMENT,'
        ),
        expected_catcher='test_warning_text_is_exact',
    ),
    Mutant(
        name='materialisation-is-eager',
        path='cpp/src/parse.cpp',
        old='  materialised_.resize(steps_.size());',
        new=(
            '  materialised_.resize(steps_.size());\n'
            '  for (uint64_t s = 0; s < steps_.size(); ++s) step_arrays(s);'
        ),
        expected_catcher='ParseTest.StepsAreMaterialisedOnDemandAndOnlyOnce',
    ),
    Mutant(
        name='repeat-read-reparses',
        path='cpp/src/parse.cpp',
        old='  if (!slot) {',
        new='  if (true) {',
        expected_catcher='ParseTest.StepsAreMaterialisedOnDemandAndOnlyOnce',
    ),
    Mutant(
        name='missing-node-drops-nothing',
        path='cpp/src/parse.cpp',
        old='    if (!complete) continue;',
        new='    if (false) continue;',
        expected_catcher='test_mesh_matches_reference[comprehensive.frd]',
    ),
]


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False, **kwargs)


def build(build_dir: Path) -> tuple[bool, str]:
    configure = run(
        [
            'cmake',
            '-S',
            'cpp',
            '-B',
            str(build_dir),
            '-DCMAKE_BUILD_TYPE=Release',
            '-DPVFRD_BUILD_TESTS=ON',
        ]
    )
    if configure.returncode != 0:
        return False, configure.stderr
    compiled = run(['cmake', '--build', str(build_dir), '--parallel'])
    return compiled.returncode == 0, compiled.stderr


def run_tests(build_dir: Path) -> tuple[bool, list[str]]:
    """Run both tiers. Returns (all green, every failing test name)."""
    library = next(build_dir.rglob('libpvfrd.so'), None) or next(
        build_dir.rglob('libpvfrd.dylib'), None
    )
    env = {
        'PVFRD_LIBRARY': str(library) if library else '',
        'PYTHONPATH': f'{ROOT / "src"}:{ROOT}',
    }
    import os

    environ = {**os.environ, **env}

    # Both tiers run to completion rather than stopping at the first red.
    # Which gate catches a mutant is the interesting part, and -x would only
    # ever report whichever tier happens to run first.
    gtest = subprocess.run(
        [str(build_dir / 'pvfrd_tests'), '--gtest_brief=1'],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=environ,
    )
    pytest = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests', '-q', '--no-header'],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=environ,
    )

    if gtest.returncode == 0 and pytest.returncode == 0:
        return True, []

    culprits = []
    if gtest.returncode < 0 or gtest.returncode > 1:
        # Negative is a signal, above 1 is an abort: the binary died rather
        # than reporting failures, so no individual test can be named.
        culprits.append(f'<gtest binary crashed, exit {gtest.returncode}>')
    for line in (gtest.stdout + pytest.stdout).splitlines():
        stripped = line.strip()
        if stripped.startswith('FAILED '):
            culprits.append(stripped.split(' ', 1)[1].split(' ')[0])
        elif stripped.startswith('[  FAILED  ]') and '(' in stripped:
            culprits.append(stripped.replace('[  FAILED  ]', '').split('(')[0].strip())
    return False, culprits or ['(failed, culprit not identified)']


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('names', nargs='*', help='mutants to run (default: all)')
    parser.add_argument('--list', action='store_true', help='list mutant names and exit')
    args = parser.parse_args()

    if args.list:
        for mutant in MUTANTS:
            print(f'{mutant.name:32s} {mutant.path}')
        return 0

    selected = [m for m in MUTANTS if not args.names or m.name in args.names]
    unknown = set(args.names) - {m.name for m in MUTANTS}
    if unknown:
        print(f'unknown mutant(s): {", ".join(sorted(unknown))}', file=sys.stderr)
        return 2

    build_dir = Path(tempfile.mkdtemp(prefix='pvfrd-mutate-'))
    survivors = []
    misattributed = []

    try:
        ok, error = build(build_dir)
        if not ok:
            print('the unmutated tree does not build:\n' + error, file=sys.stderr)
            return 1
        green, culprits = run_tests(build_dir)
        if not green:
            # Without this the whole sweep is meaningless: every mutant would
            # be reported killed by a failure that was there before it.
            print(
                f'the unmutated tree is already red ({culprits[:3]}); fix that first',
                file=sys.stderr,
            )
            return 1
        print(f'baseline green, {len(selected)} mutant(s) to run\n')

        for mutant in selected:
            source = ROOT / mutant.path
            original = source.read_text()
            if mutant.old not in original:
                print(f'{mutant.name:32s} STALE  (its anchor is no longer in {mutant.path})')
                survivors.append(mutant.name)
                continue
            source.write_text(original.replace(mutant.old, mutant.new, 1))
            try:
                built, error = build(build_dir)
                if not built:
                    # A mutant that will not compile has not been tested. It
                    # is not evidence either way, so it is not a kill.
                    print(f'{mutant.name:32s} UNBUILT (compile error)')
                    survivors.append(mutant.name)
                    continue
                green, culprits = run_tests(build_dir)
                if green:
                    print(f'{mutant.name:32s} SURVIVED  <- nothing detects this')
                    survivors.append(mutant.name)
                else:
                    wanted = mutant.expected_catcher
                    hit = any(wanted in c or c in wanted for c in culprits)
                    flag = '' if hit else f'  (expected {wanted}, which stayed green)'
                    if not hit:
                        misattributed.append(mutant.name)
                    print(
                        f'{mutant.name:32s} killed by {len(culprits)} test(s), '
                        f'first {culprits[0]}{flag}'
                    )
            finally:
                source.write_text(original)
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)
        # Rebuild the working tree's own build dir so a sweep does not leave
        # a stale library behind for the next command to grade against.
        run(['cmake', '--build', 'cpp/build', '--parallel'])

    print()
    if survivors:
        print(f'{len(survivors)} survivor(s): {", ".join(survivors)}')
    if misattributed:
        print(f'{len(misattributed)} killed by an unexpected gate: {", ".join(misattributed)}')
    if not survivors:
        print(f'all {len(selected)} mutants killed')
    return 1 if survivors else 0


if __name__ == '__main__':
    raise SystemExit(main())

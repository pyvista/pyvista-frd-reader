"""Read set membership from CalculiX input decks, without solving the model."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
import re
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Iterator
    import os

# Commas inside a quoted include filename are not field separators.
_COMMA = re.compile(r',(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)')
_MAX_ID = np.iinfo(np.int64).max


@dataclass
class INPSets:
    """Original IDs belonging to the node and element sets in an input deck.

    Names are normalized to uppercase. Arrays contain sorted, unique int64
    IDs, including IDs absent from an FRD output mesh. Node and element sets
    have separate namespaces. Ordering such as ``UNSORTED`` is not preserved:
    these sets describe membership, not constraint or equation ordering.
    """

    node_sets: dict[str, np.ndarray] = field(default_factory=dict)
    element_sets: dict[str, np.ndarray] = field(default_factory=dict)


def _fields(line: str) -> list[str]:
    return [part.strip() for part in _COMMA.split(line)]


def _name(value: str) -> str:
    return value.strip().strip('"').upper()


def _keyword(line: str) -> tuple[str, dict[str, str]]:
    fields = _fields(line)
    options = {}
    for item in fields[1:]:
        if item:
            key, _, value = item.partition('=')
            options[key.strip().upper()] = value.strip().strip('"')
    return fields[0].upper(), options


def _records(path: Path) -> Iterator[tuple[str, str]]:
    """Join keyword continuations, allowing a harmless trailing comma."""
    with path.open(encoding='utf-8-sig', errors='surrogateescape') as handle:
        pending = ''
        location = ''
        for number, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line or line.startswith('**'):
                continue
            # A continued parameter contains '=' or is a known bare flag.
            # A numeric data row or another keyword ends the previous header
            # even if it has a trailing comma (seen in published CCX decks).
            if pending:
                if not line.startswith('*') and (
                    '=' in line or _fields(line)[0].upper() in {'GENERATE', 'UNSORTED'}
                ):
                    line = pending + line
                else:
                    yield pending, location
                    location = f'{path}:{number}'
            else:
                location = f'{path}:{number}'
            pending = ''
            if line.startswith('*') and line.endswith(','):
                pending = line
            else:
                yield line, location
        if pending:
            yield pending, location


def _lines(path: Path, root: Path, stack: tuple[Path, ...] = ()) -> Iterator[tuple[str, str]]:
    """Expand includes in place, keeping source locations for diagnostics."""
    path = path.resolve()
    if path in stack:
        msg = f'Cyclic *INCLUDE: {" -> ".join(str(p) for p in (*stack, path))}'
        raise ValueError(msg)
    if len(stack) >= 100:  # noqa: PLR2004
        msg = f'{path}: *INCLUDE nesting exceeds 100 files'
        raise ValueError(msg)
    for line, location in _records(path):
        keyword, options = _keyword(line) if line.startswith('*') else ('', {})
        if keyword == '*INCLUDE':
            filename = options.get('INPUT')
            if not filename:
                msg = f'{location}: *INCLUDE requires INPUT'
                raise ValueError(msg)
            # CalculiX resolves paths against the job directory even in
            # nested includes. Never change the process working directory.
            yield from _lines(root / filename, root, (*stack, path))
        else:
            yield line, location


def _select_set(
    keyword: str,
    options: dict[str, str],
    nodes: dict[str, set[int]],
    elements: dict[str, set[int]],
) -> tuple[set[int] | None, dict[str, set[int]]]:
    if keyword in {'*PART', '*ASSEMBLY', '*INSTANCE'} or 'INSTANCE' in options:
        msg = 'part/assembly/instance namespaces are not supported'
        raise ValueError(msg)
    if keyword in {'*NGEN', '*NFILL', '*NCOPY', '*ELGEN', '*ELCOPY'} and (
        'NSET' in options or 'ELSET' in options
    ):
        msg = f'sets created by {keyword} are not supported'
        raise ValueError(msg)
    if keyword not in {'*NSET', '*ELSET', '*NODE', '*ELEMENT'}:
        return None, {}
    association = 'NSET' if keyword in {'*NSET', '*NODE'} else 'ELSET'
    sets = nodes if association == 'NSET' else elements
    if keyword in {'*NSET', '*ELSET'} and not options.get(association):
        msg = f'{keyword} requires {association}'
        raise ValueError(msg)
    if association not in options:
        return None, sets
    name = _name(options[association])
    if not name:
        msg = 'set name must not be empty'
        raise ValueError(msg)
    # Reject parameters that change membership; unrelated parameters in
    # published decks (such as FREQUENCY on NSET) do not change its IDs.
    unsupported = (
        {'ELSET', 'INPUT'} & options.keys() if association == 'NSET' else {'INPUT'} & options.keys()
    )
    if unsupported:
        msg = f'unsupported {keyword} parameter(s): {", ".join(sorted(unsupported))}'
        raise ValueError(msg)
    return sets.setdefault(name, set()), sets


def _identifier(value: str) -> int:
    number = int(value)
    if not 0 < number <= _MAX_ID:
        msg = f'ID must be a positive int64, got {value!r}'
        raise ValueError(msg)
    return number


def _members(fields: list[str], sets: dict[str, set[int]], *, generate: bool) -> set[int]:
    if generate:
        if len(fields) not in (2, 3):
            msg = 'GENERATE requires first, last, and optional increment'
            raise ValueError(msg)
        first, last = map(_identifier, fields[:2])
        increment = _identifier(fields[2]) if len(fields) == 3 else 1  # noqa: PLR2004
        if last < first:
            msg = 'GENERATE requires an ascending range with a positive increment'
            raise ValueError(msg)
        return set(range(first, last + 1, increment))
    members: set[int] = set()
    for value in fields:
        if re.fullmatch(r'[+-]?\d+', value):
            members.add(_identifier(value))
        else:
            name = _name(value)
            if name not in sets:
                msg = f'undefined set {value!r}; references must name a previously defined set'
                raise ValueError(msg)
            members.update(sets[name])
    return members


def _element_size(element_type: str) -> int | None:
    """Return connectivity counts from the CalculiX *ELEMENT interface."""
    match = re.fullmatch(r'(?:DC3D|C3D|F3D|M3D|CPS|CPE|CAX|S)(\d+)[A-Z]*', element_type.upper())
    if match:
        return int(match[1])
    match = re.fullmatch(r'T[23]D([23])', element_type.upper())
    if match:
        return int(match[1])
    return {
        'B21': 2,
        'B31': 2,
        'B31R': 2,
        'B32': 3,
        'B32R': 3,
        'D': 3,
        'GAPUNI': 2,
        'DASHPOTA': 2,
        'SPRING1': 1,
        'SPRING2': 2,
        'SPRINGA': 2,
        'DCOUP3D': 1,
        'MASS': 1,
    }.get(element_type.upper())


def read_sets(path: str | os.PathLike[str]) -> INPSets:
    """Read node and element set membership from a CalculiX ``.inp`` file.

    Parameters
    ----------
    path : str | os.PathLike
        Input deck. Relative ``*INCLUDE, INPUT=...`` paths are resolved from
        this file's directory, the CalculiX job directory.

    Returns
    -------
    INPSets
        Sets expressed as original node and element IDs, not mesh indices.

    Raises
    ------
    ValueError
        Invalid set syntax, an undefined reference, an include cycle, or
        unsupported assembly or set-generation syntax.
    OSError
        The deck or an included file cannot be opened.

    Notes
    -----
    Supports ``*NSET``, ``*ELSET``, ``GENERATE``, references to earlier sets,
    repeated definitions, ``*NODE, NSET=...``, ``*ELEMENT, ELSET=...``, and
    nested ``*INCLUDE``. References copy membership at the point of use.
    Other analysis keywords are ignored. Surfaces, Abaqus part/instance
    namespaces, and sets created by mesh-generation keywords are unsupported.

    Examples
    --------
    >>> import pyvista_frd
    >>> sets = pyvista_frd.read_sets('model.inp')  # doctest: +SKIP
    >>> fixed_ids = sets.node_sets['FIXED']  # doctest: +SKIP

    """
    path = Path(path)
    nodes: dict[str, set[int]] = {}
    elements: dict[str, set[int]] = {}
    keyword = ''
    options: dict[str, str] = {}
    target = None
    continued_element = False
    remaining = 0
    for line, location in _lines(path, path.resolve().parent):
        try:
            if line.startswith('*'):
                keyword, options = _keyword(line)
                target = None
                continued_element = False
                remaining = 0
                target, sets = _select_set(keyword, options, nodes, elements)
            elif target is not None:
                fields = [value for value in _fields(line) if value]
                if keyword in {'*NODE', '*ELEMENT'}:
                    if not continued_element:
                        target.add(_identifier(fields[0]))
                    if keyword == '*ELEMENT':
                        size = _element_size(options.get('TYPE', ''))
                        if size is None:
                            continued_element = line.endswith(',')
                        else:
                            remaining = (remaining if continued_element else size + 1) - len(fields)
                            continued_element = remaining > 0
                else:
                    target.update(_members(fields, sets, generate='GENERATE' in options))
        except (ValueError, IndexError) as exc:  # noqa: PERF203 - retain the failing source line
            msg = f'{location}: {exc}'
            raise ValueError(msg) from exc
    return INPSets(
        {name: np.array(sorted(ids), dtype=np.int64) for name, ids in nodes.items()},
        {name: np.array(sorted(ids), dtype=np.int64) for name, ids in elements.items()},
    )

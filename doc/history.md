# History and credit

This package reimplements PyVista's FRD reader in C++ and exposes it through a
C API. The parser behavior and array conventions come from the original
PyVista implementation.

## PyVista reader

[Rafal (@3rav)](https://github.com/3rav) wrote the original reader and its
subsequent format and pyramid support:

| Change | Description |
| --- | --- |
| [pyvista#8255](https://github.com/pyvista/pyvista/pull/8255) | Added the FRD reader. Opened 2026-01-22 and merged 2026-03-10. |
| [pyvista#8448](https://github.com/pyvista/pyvista/pull/8448) | Added short, long, and fixed-width record handling. |
| [pyvista#8936](https://github.com/pyvista/pyvista/pull/8936) | Adds C3D5 and C3D13 pyramid support. This pull request is still open. |

[@efirvida](https://github.com/efirvida) requested FRD support in
[pyvista#5350](https://github.com/pyvista/pyvista/issues/5350). Later changes
by [@user27182](https://github.com/user27182) added VTK 9.7 wedge ordering in
[pyvista#8819](https://github.com/pyvista/pyvista/pull/8819) and updated import
conventions in
[pyvista#8868](https://github.com/pyvista/pyvista/pull/8868).

The file `tests/conformance/ref_frd.py` is an unchanged copy of PyVista's
reader. The conformance tests use it as the reference implementation. Its
header records the upstream file and commit.

PyVista 0.49 removed its built-in FRD reader. The tests use the installed
reader when available and the pinned upstream classes in
`tests/conformance/ref_reader.py` otherwise. Those class bodies are verbatim
extracts from the same upstream commit as the parser; only their imports
are adapted. This preserves warning and binary-to-ASCII comparisons without
depending on the removed API or substituting this package as its own reference.

## FRD format

[Guido Dhondt and Klaus Wittig](http://www.dhondt.de/) created CalculiX and
the FRD format. CalculiX is GPL-licensed. No independent FRD specification is
available, so this project checks behavior against files written by `ccx` and
read by `cgx`.

## This implementation

This project adds:

- a C API in `cpp/include/pvfrd/pvfrd.h`;
- byte-oriented parsing and binary FRD support;
- derived von Mises and principal-value calculations without a LAPACK
  dependency;
- a writer and encoding converter;
- C++, Python, conformance, fuzz, and mutation tests.

The external parity results compare behavior. They do not imply that the
algorithms or implementation are the same.

## Licenses

| Component | License | Location |
| --- | --- | --- |
| pyvista-frd-reader | MIT | `LICENSE` |
| PyVista and its FRD reader | MIT | Upstream PyVista repository |
| Vendored PyVista reference reader | MIT | `tests/conformance/ref_frd.py` |
| CalculiX and its regression suite | GPL | Downloaded by `tools/fetch_corpus.py`; not vendored |

The generated fixtures under `tests/fixtures` use input decks written for this
repository and are covered by its MIT license.

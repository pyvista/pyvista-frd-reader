"""Build the native pvfrd core and bundle it into the wheel.

There is no pure-Python fallback in this package, so the native build is
**required**, not best effort. A build that cannot produce the shared library
fails here rather than producing a wheel that installs and then raises on
import -- the second is strictly worse, because it fails on the user's machine
instead of on ours.

``PVFRD_BUILD_NATIVE=0`` skips the build. That exists for one purpose: CI jobs
that install the package as pure Python and point it at a library built
separately by CMake, so that the artefact under test is the one the CMake job
produced rather than a second copy compiled by pip.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from setuptools import setup
from setuptools.dist import Distribution

HERE = Path(__file__).parent.resolve()
CPP_DIR = HERE / 'cpp'
PACKAGE_LIB_DIR = HERE / 'src' / 'pyvista_frd' / 'lib'

_SKIPPED = os.environ.get('PVFRD_BUILD_NATIVE', '').strip() == '0'


def _library_names() -> list[str]:
    """Shared-library file names CMake may produce, per platform.

    Kept in step with ``pyvista_frd._capi._candidate_names``; the loader looks
    for these exact names inside the installed package.
    """
    if sys.platform == 'win32':
        return ['pvfrd.dll', 'libpvfrd.dll']
    if sys.platform == 'darwin':
        return ['libpvfrd.dylib']
    return ['libpvfrd.so']


def _find_built_library(build_dir: Path) -> Path | None:
    """Locate the shared library inside a finished CMake build tree.

    Searched recursively because multi-config generators (Visual Studio) put
    the artefact under a per-configuration subdirectory while single-config
    generators leave it at the top.
    """
    for name in _library_names():
        matches = sorted(build_dir.rglob(name))
        if matches:
            return matches[0]
    return None


def _macos_architectures() -> str:
    """Return the macOS architectures to build for, or an empty string.

    ``CMAKE_OSX_ARCHITECTURES`` wins when set. Otherwise the value comes from
    ``ARCHFLAGS``, which is how wheel builders request a cross-build: they
    export ``ARCHFLAGS=-arch x86_64`` and say nothing about CMake. Ignoring it
    silently produces a library for the host architecture inside a wheel
    labelled for the other one.
    """
    explicit = os.environ.get('CMAKE_OSX_ARCHITECTURES', '').strip()
    if explicit:
        return explicit
    if sys.platform != 'darwin':
        return ''
    flags = os.environ.get('ARCHFLAGS', '').split()
    found = [flags[i + 1] for i, flag in enumerate(flags) if flag == '-arch' and i + 1 < len(flags)]
    return ';'.join(dict.fromkeys(found))


def _build_native() -> Path | None:
    """Configure, build, and return the path to the bundled shared library."""
    if _SKIPPED:
        print('pvfrd: PVFRD_BUILD_NATIVE=0, skipping the native build')
        return None
    if not (CPP_DIR / 'CMakeLists.txt').is_file():
        msg = (
            f'pvfrd: no CMake project at {CPP_DIR}. An sdist that omitted cpp/ '
            f'cannot build this package.'
        )
        raise SystemExit(msg)

    build_dir = Path(tempfile.mkdtemp(prefix='pvfrd-build-'))
    configure = [
        'cmake',
        '-S',
        str(CPP_DIR),
        '-B',
        str(build_dir),
        '-DCMAKE_BUILD_TYPE=Release',
        '-DPVFRD_BUILD_SHARED=ON',
        # A wheel has no use for the dump tool or the test binary, and
        # building either only lengthens every wheel build.
        '-DPVFRD_BUILD_TOOLS=OFF',
        '-DPVFRD_BUILD_TESTS=OFF',
        '-DCMAKE_POSITION_INDEPENDENT_CODE=ON',
    ]
    if sys.platform == 'darwin' and (target := os.environ.get('MACOSX_DEPLOYMENT_TARGET')):
        configure.append(f'-DCMAKE_OSX_DEPLOYMENT_TARGET={target}')
    if archs := _macos_architectures():
        configure.append(f'-DCMAKE_OSX_ARCHITECTURES={archs}')

    try:
        subprocess.run(configure, check=True)
        subprocess.run(
            ['cmake', '--build', str(build_dir), '--config', 'Release', '--parallel'],
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        msg = f'pvfrd: the native build failed and this package requires it: {exc}'
        raise SystemExit(msg) from exc

    built = _find_built_library(build_dir)
    if built is None:
        msg = f'pvfrd: the build produced no shared library in {build_dir}'
        raise SystemExit(msg)

    PACKAGE_LIB_DIR.mkdir(parents=True, exist_ok=True)
    destination = PACKAGE_LIB_DIR / built.name
    shutil.copy2(built, destination)
    print(f'pvfrd: bundled {built} -> {destination}')
    shutil.rmtree(build_dir, ignore_errors=True)
    return destination


# Commands that put files into a wheel or an installed tree. Metadata-only
# invocations (``dist_info``, ``egg_info``, ``sdist``) are deliberately absent:
# invoking a C++ compiler to answer a question about the version is waste.
_BUILDING_COMMANDS = frozenset({'bdist_wheel', 'build', 'build_py', 'editable_wheel', 'install'})


def _is_a_build() -> bool:
    """Whether this invocation is going to produce installable artefacts."""
    return any(arg in _BUILDING_COMMANDS for arg in sys.argv[1:])


# Built here, at import time, rather than from inside build_py. bdist_wheel
# decides the wheel's platform tag in finalize_options, which runs before any
# build command, so the answer has to exist by the time setup() is called.
# Deferring it produces a wheel containing a Linux shared object tagged
# py3-none-any, which pip would happily hand to a Windows machine.
_bundled: Path | None = _build_native() if _is_a_build() else None


class NativeDistribution(Distribution):
    """Tag the wheel for this platform once a compiled library is inside it."""

    def has_ext_modules(self) -> bool:
        """Report whether a compiled artefact is going into the wheel."""
        return _bundled is not None


_cmdclass: dict[str, type] = {}

try:
    from setuptools.command.bdist_wheel import bdist_wheel
except ImportError:  # pragma: no cover - setuptools older than 70.1
    try:
        from wheel.bdist_wheel import bdist_wheel  # type: ignore[no-redef]
    except ImportError:
        bdist_wheel = None  # type: ignore[assignment]

if bdist_wheel is not None:

    class PlatformNotInterpreterWheel(bdist_wheel):
        """Tag the wheel by platform only, never by interpreter.

        ``has_ext_modules`` above makes setuptools reach for the full
        ``cp313-cp313-linux_x86_64`` tag, which is what a CPython extension
        module needs. This library is not one: it is a plain C shared object
        loaded through ctypes with no reference to the CPython ABI, so a
        single build serves every supported interpreter. Left alone, the
        stricter tag would multiply the wheel matrix by the number of Python
        versions and gain nothing.
        """

        def get_tag(self) -> tuple[str, str, str]:
            """Return the wheel tag, widened to every Python 3 interpreter."""
            python, abi, platform = super().get_tag()
            if _bundled is not None:
                return 'py3', 'none', platform
            return python, abi, platform

    _cmdclass['bdist_wheel'] = PlatformNotInterpreterWheel


setup(
    distclass=NativeDistribution,
    cmdclass=_cmdclass,
    package_data={'pyvista_frd': ['lib/*']},
)

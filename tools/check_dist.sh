#!/usr/bin/env bash
# Fail unless a directory holds a wheel for every platform we publish, plus
# an sdist. Takes the directory as its one argument.
#
# A partial upload is worse than none: PyPI keeps what it is given, and a
# release missing its macOS wheel sends every Mac user to a source build they
# may not be able to run.
#
# Matched by architecture, never by glibc version. An earlier form of this
# check named manylinux_2_17 explicitly, and would have gone stale unnoticed
# the moment the manylinux floor moved -- which it since has.
set -uo pipefail

dist=${1:?usage: check_dist.sh DIR}
missing=0

require() {
  # Unquoted on purpose: $1 is a glob and has to be expanded here.
  # shellcheck disable=SC2086
  if ! ls "$dist"/$1 > /dev/null 2>&1; then
    echo "::error::nothing matching $1 in $dist; refusing to publish a partial release"
    missing=1
  fi
}

require '*linux*_x86_64.whl'
require '*linux*_aarch64.whl'
require '*macosx*_x86_64.whl'
require '*macosx*_arm64.whl'
require '*win_amd64.whl'
require '*.tar.gz'

exit $missing

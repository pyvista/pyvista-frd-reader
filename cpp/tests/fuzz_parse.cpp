/* libFuzzer entry point for the parser.
 *
 * An FRD file is untrusted text that this library reads into fixed-size
 * arrays, indexes by byte offset, and splits at fixed widths. Every one of
 * those is a place where a malformed file could walk off the end of a buffer,
 * and none of them is reachable from a corpus of well-formed fixtures.
 *
 * The parse is driven through the memory entry point so that a case needs no
 * temporary file, and every accessor is exercised afterwards: a document that
 * parses without crashing but then hands out a bad pointer is the failure
 * this would otherwise miss.
 */

#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <vector>

#include "pvfrd/pvfrd.h"

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
  /* The wedge option is part of the input so both permutation paths are
   * reached, rather than only whichever one is the default. */
  pvfrd_open_options options = {PVFRD_WEDGE_ASIS, 0};
  if (size > 0 && (data[0] & 1u)) options.wedge_order = PVFRD_WEDGE_SWAP;

  pvfrd_file *file = nullptr;
  if (pvfrd_open_memory(data, size, &options, &file) != PVFRD_OK) return 0;

  /* Touch every array the mesh claims to have, so an offset table that does
   * not match the connectivity is a read past the end rather than a number
   * nobody looked at. */
  const uint64_t n_points = pvfrd_n_points(file);
  const double *points = pvfrd_points(file);
  volatile double sink = 0.0;
  for (uint64_t i = 0; i < n_points * 3; ++i) sink += points[i];

  const uint64_t n_cells = pvfrd_n_cells(file);
  const int64_t *offsets = pvfrd_cell_offsets(file);
  const int64_t *connectivity = pvfrd_cell_connectivity(file);
  for (uint64_t c = 0; c < n_cells; ++c) {
    for (int64_t k = offsets[c]; k < offsets[c + 1]; ++k) {
      if (connectivity[k] < 0 || static_cast<uint64_t>(connectivity[k]) >= n_points) {
        /* std::abort rather than __builtin_trap: the latter is a GCC and
         * Clang builtin and MSVC has no such identifier, so the replay
         * driver -- which is built by every compiler -- would not compile.
         * Both are fatal, and libFuzzer and the sanitizers report an abort
         * the same way they report a trap. */
        std::abort(); /* a point index the mesh cannot satisfy */
      }
    }
  }

  for (uint64_t i = 0; i < pvfrd_n_diagnostics(file); ++i) {
    pvfrd_diagnostic diagnostic;
    pvfrd_diagnostic_at(file, i, &diagnostic);
  }

  for (uint64_t step = 0; step < pvfrd_n_steps(file); ++step) {
    double time = 0.0;
    pvfrd_step_time(file, step, &time);
    uint64_t n_arrays = 0;
    if (pvfrd_n_arrays(file, step, &n_arrays) != PVFRD_OK) continue;
    if (n_arrays == 0) continue;

    std::vector<pvfrd_array_info> info(n_arrays);
    if (pvfrd_array_info_range(file, step, 0, n_arrays, info.data()) != PVFRD_OK) continue;
    for (uint64_t a = 0; a < n_arrays; ++a) {
      const double *values = nullptr;
      if (pvfrd_array_data(file, step, a, &values) != PVFRD_OK) continue;
      const uint64_t count = info[a].n_tuples * info[a].n_components;
      for (uint64_t v = 0; v < count; ++v) sink += values[v];
      pvfrd_find_array(file, step, info[a].name);
    }
  }

  pvfrd_close(file);
  return 0;
}

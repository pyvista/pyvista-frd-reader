/* frd_dump -- print everything a reader can see about an FRD file.
 *
 * The output is deterministic and line-oriented, so two builds of this
 * library can be compared with `diff` rather than by trusting that both
 * exited zero. That is what the WebAssembly job does: a build that configures
 * and links proves nothing about whether its arithmetic agrees with the
 * native one.
 *
 * Values are printed with %.17g, which round-trips a double exactly, so a
 * difference in the last bit shows up as a difference in the text.
 */

#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "pvfrd/pvfrd.h"

namespace {

int usage(const char *argv0) {
  std::fprintf(stderr,
               "usage: %s [--wedge-swap] FILE\n"
               "\n"
               "  --wedge-swap  order PE6 wedge nodes the way VTK < 9.7 expects\n",
               argv0);
  return 2;
}

}  // namespace

int main(int argc, char **argv) {
  pvfrd_open_options options = {PVFRD_WEDGE_ASIS, 0};
  const char *path = nullptr;

  for (int i = 1; i < argc; ++i) {
    if (std::strcmp(argv[i], "--wedge-swap") == 0) {
      options.wedge_order = PVFRD_WEDGE_SWAP;
    } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
      return usage(argv[0]);
    } else {
      if (path != nullptr) return usage(argv[0]);
      path = argv[i];
    }
  }
  if (path == nullptr) return usage(argv[0]);

  pvfrd_file *file = nullptr;
  pvfrd_status status = pvfrd_open_ex(path, &options, &file);
  if (status != PVFRD_OK) {
    std::fprintf(stderr, "%s: %s\n", path, pvfrd_status_message(status));
    return 1;
  }

  std::printf("abi %u\n", pvfrd_abi_version());

  const uint64_t n_points = pvfrd_n_points(file);
  const double *points = pvfrd_points(file);
  const int64_t *ids = pvfrd_node_ids(file);
  std::printf("points %llu\n", static_cast<unsigned long long>(n_points));
  for (uint64_t i = 0; i < n_points; ++i) {
    std::printf("  %lld %.17g %.17g %.17g\n", static_cast<long long>(ids[i]), points[i * 3],
                points[i * 3 + 1], points[i * 3 + 2]);
  }

  const uint64_t n_cells = pvfrd_n_cells(file);
  const uint8_t *types = pvfrd_cell_types(file);
  const int64_t *offsets = pvfrd_cell_offsets(file);
  const int64_t *conn = pvfrd_cell_connectivity(file);
  std::printf("cells %llu\n", static_cast<unsigned long long>(n_cells));
  for (uint64_t c = 0; c < n_cells; ++c) {
    std::printf("  type %u:", static_cast<unsigned>(types[c]));
    for (int64_t k = offsets[c]; k < offsets[c + 1]; ++k) {
      std::printf(" %lld", static_cast<long long>(conn[k]));
    }
    std::printf("\n");
  }

  const uint64_t n_diagnostics = pvfrd_n_diagnostics(file);
  std::printf("diagnostics %llu\n", static_cast<unsigned long long>(n_diagnostics));
  for (uint64_t i = 0; i < n_diagnostics; ++i) {
    pvfrd_diagnostic diagnostic;
    if (pvfrd_diagnostic_at(file, i, &diagnostic) != PVFRD_OK) continue;
    std::printf("  kind %d type %d line %lld expected %lld actual %lld\n", diagnostic.kind,
                diagnostic.element_type, static_cast<long long>(diagnostic.line),
                static_cast<long long>(diagnostic.n_expected),
                static_cast<long long>(diagnostic.n_actual));
  }

  const uint64_t n_steps = pvfrd_n_steps(file);
  std::printf("steps %llu\n", static_cast<unsigned long long>(n_steps));
  for (uint64_t s = 0; s < n_steps; ++s) {
    double time = 0.0;
    pvfrd_step_time(file, s, &time);
    uint64_t n_arrays = 0;
    if (pvfrd_n_arrays(file, s, &n_arrays) != PVFRD_OK) {
      std::printf("  step %.17g UNREADABLE: %s\n", time, pvfrd_last_error(file));
      continue;
    }
    std::printf("  step %.17g arrays %llu\n", time, static_cast<unsigned long long>(n_arrays));
    for (uint64_t a = 0; a < n_arrays; ++a) {
      pvfrd_array_info info;
      if (pvfrd_array_info_at(file, s, a, &info) != PVFRD_OK) continue;
      const double *data = nullptr;
      if (pvfrd_array_data(file, s, a, &data) != PVFRD_OK) continue;
      std::printf("    %s comps %u tuples %llu kind %d\n", info.name, info.n_components,
                  static_cast<unsigned long long>(info.n_tuples), info.kind);
      const uint64_t n_values = info.n_tuples * info.n_components;
      for (uint64_t v = 0; v < n_values; ++v) {
        std::printf("      %.17g\n", data[v]);
      }
    }
  }

  pvfrd_close(file);
  return 0;
}

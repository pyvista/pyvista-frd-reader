/* The C ABI.
 *
 * Everything here is a thin translation between the header's plain-C surface
 * and the Document behind it. Two rules hold throughout:
 *
 *   - No exception escapes. Every entry point that can allocate is wrapped,
 *     because unwinding out of an `extern "C"` frame into a ctypes caller is
 *     undefined behaviour, and the caller most likely to hit it is the one
 *     least able to diagnose it.
 *   - A NULL argument is PVFRD_E_INVALID, never a crash. This library is
 *     bound dynamically from languages with no compiler to check the calls.
 */

#include <cstdio>
#include <cstring>
#include <new>
#include <string>

#if defined(_WIN32)
#include <windows.h>
#endif

#include "frd.h"
#include "pvfrd/pvfrd.h"

/* The Document holds a mutex for the lazy per-step materialisation, so it is
 * neither copyable nor movable. Constructed in place here rather than handed
 * in, which keeps that constraint local to one line. */
struct pvfrd_file {
  pvfrd_file(std::string buffer, pvfrd_open_options options)
      : document(std::move(buffer), options) {}
  pvfrd::Document document;
};

namespace {

const pvfrd_open_options kDefaultOptions = {PVFRD_WEDGE_ASIS, 0};

/* Open a path given as UTF-8, which is what the header promises.
 *
 * On Windows that promise needs work: fopen interprets its bytes in the
 * process's active code page, not as UTF-8, so a path containing anything
 * outside ASCII fails to open -- or, worse, opens a different file. Python
 * hands this function UTF-8 (PEP 529), and so does any caller following the
 * header, so the bytes are converted to UTF-16 here and _wfopen is used.
 *
 * Everywhere else, a path is bytes and fopen takes them unchanged. */
std::FILE *open_path(const char *path) {
#if defined(_WIN32)
  const int wide_length = MultiByteToWideChar(CP_UTF8, 0, path, -1, nullptr, 0);
  if (wide_length <= 0) return nullptr;
  std::wstring wide(static_cast<size_t>(wide_length), L'\0');
  if (MultiByteToWideChar(CP_UTF8, 0, path, -1, wide.data(), wide_length) <= 0) return nullptr;
  return _wfopen(wide.c_str(), L"rb");
#else
  return std::fopen(path, "rb");
#endif
}

pvfrd_status open_from_buffer(std::string buffer, const pvfrd_open_options *options,
                              pvfrd_file **out) {
  if (out == nullptr) return PVFRD_E_INVALID;
  *out = nullptr;

  pvfrd_open_options opts = (options != nullptr) ? *options : kDefaultOptions;
  if (opts.wedge_order != PVFRD_WEDGE_ASIS && opts.wedge_order != PVFRD_WEDGE_SWAP) {
    return PVFRD_E_INVALID;
  }
  if (opts.reserved != 0) return PVFRD_E_INVALID;

  try {
    auto *file = new pvfrd_file(std::move(buffer), opts);
    pvfrd_status status = file->document.parse();
    if (status != PVFRD_OK) {
      delete file;
      return status;
    }
    *out = file;
    return PVFRD_OK;
  } catch (const std::bad_alloc &) {
    return PVFRD_E_NOMEM;
  } catch (...) {
    return PVFRD_E_FORMAT;
  }
}

}  // namespace

extern "C" {

uint32_t pvfrd_abi_version(void) {
  return PVFRD_ABI_VERSION;
}

const char *pvfrd_status_message(int status) {
  switch (status) {
    case PVFRD_OK: return "ok";
    case PVFRD_E_IO: return "the file could not be opened or read";
    case PVFRD_E_FORMAT: return "the file did not parse as an FRD document";
    case PVFRD_E_RANGE: return "index out of range";
    case PVFRD_E_NOMEM: return "out of memory";
    case PVFRD_E_INVALID: return "invalid argument";
    case PVFRD_E_RAGGED: return "a result block gave two nodes different component counts";
    default: return "unknown status";
  }
}

const char *pvfrd_last_error(const pvfrd_file *file) {
  if (file == nullptr) return "";
  return file->document.last_error().c_str();
}

pvfrd_status pvfrd_open(const char *path, pvfrd_file **out) {
  return pvfrd_open_ex(path, nullptr, out);
}

pvfrd_status pvfrd_open_ex(const char *path, const pvfrd_open_options *options, pvfrd_file **out) {
  if (path == nullptr || out == nullptr) return PVFRD_E_INVALID;
  *out = nullptr;

  /* Read the whole file up front. FRD is a text format whose parse touches
   * every line, so there is no read pattern that a streaming reader would
   * save; and holding the bytes is what lets a time step be materialised
   * later without going back to disk, which is the point of the lazy step
   * path. */
  std::FILE *handle = open_path(path);
  if (handle == nullptr) return PVFRD_E_IO;

  std::string buffer;
  try {
    char chunk[1 << 16];
    for (;;) {
      size_t got = std::fread(chunk, 1, sizeof(chunk), handle);
      if (got > 0) buffer.append(chunk, got);
      if (got < sizeof(chunk)) break;
    }
    if (std::ferror(handle) != 0) {
      std::fclose(handle);
      return PVFRD_E_IO;
    }
  } catch (const std::bad_alloc &) {
    std::fclose(handle);
    return PVFRD_E_NOMEM;
  }
  std::fclose(handle);

  return open_from_buffer(std::move(buffer), options, out);
}

pvfrd_status pvfrd_open_memory(const void *data, size_t size, const pvfrd_open_options *options,
                               pvfrd_file **out) {
  if (out == nullptr) return PVFRD_E_INVALID;
  *out = nullptr;
  if (data == nullptr && size != 0) return PVFRD_E_INVALID;
  try {
    std::string buffer(static_cast<const char *>(data), size);
    return open_from_buffer(std::move(buffer), options, out);
  } catch (const std::bad_alloc &) {
    return PVFRD_E_NOMEM;
  }
}

void pvfrd_close(pvfrd_file *file) {
  delete file;
}

uint64_t pvfrd_n_points(const pvfrd_file *file) {
  return file == nullptr ? 0 : file->document.n_points();
}

const double *pvfrd_points(const pvfrd_file *file) {
  return file == nullptr ? nullptr : file->document.points();
}

const int64_t *pvfrd_node_ids(const pvfrd_file *file) {
  return file == nullptr ? nullptr : file->document.node_ids();
}

uint64_t pvfrd_n_cells(const pvfrd_file *file) {
  return file == nullptr ? 0 : file->document.n_cells();
}

const uint8_t *pvfrd_cell_types(const pvfrd_file *file) {
  return file == nullptr ? nullptr : file->document.cell_types();
}

const int64_t *pvfrd_cell_offsets(const pvfrd_file *file) {
  return file == nullptr ? nullptr : file->document.cell_offsets();
}

const int64_t *pvfrd_cell_connectivity(const pvfrd_file *file) {
  return file == nullptr ? nullptr : file->document.cell_connectivity();
}

uint64_t pvfrd_n_diagnostics(const pvfrd_file *file) {
  return file == nullptr ? 0 : static_cast<uint64_t>(file->document.diagnostics().size());
}

pvfrd_status pvfrd_diagnostic_at(const pvfrd_file *file, uint64_t index, pvfrd_diagnostic *out) {
  if (file == nullptr || out == nullptr) return PVFRD_E_INVALID;
  const auto &all = file->document.diagnostics();
  if (index >= all.size()) return PVFRD_E_RANGE;
  *out = all[index];
  return PVFRD_OK;
}

uint64_t pvfrd_n_steps(const pvfrd_file *file) {
  return file == nullptr ? 0 : file->document.n_steps();
}

pvfrd_status pvfrd_step_time(const pvfrd_file *file, uint64_t step, double *out) {
  if (file == nullptr || out == nullptr) return PVFRD_E_INVALID;
  if (step >= file->document.n_steps()) return PVFRD_E_RANGE;
  *out = file->document.step_time(step);
  return PVFRD_OK;
}

pvfrd_status pvfrd_n_arrays(const pvfrd_file *file, uint64_t step, uint64_t *out) {
  if (file == nullptr || out == nullptr) return PVFRD_E_INVALID;
  if (step >= file->document.n_steps()) return PVFRD_E_RANGE;
  const pvfrd::MaterialisedStep *materialised = file->document.step_arrays(step);
  if (materialised == nullptr) return PVFRD_E_RAGGED;
  *out = static_cast<uint64_t>(materialised->arrays.size());
  return PVFRD_OK;
}

pvfrd_status pvfrd_array_info_at(const pvfrd_file *file, uint64_t step, uint64_t index,
                                 pvfrd_array_info *out) {
  return pvfrd_array_info_range(file, step, index, 1, out);
}

pvfrd_status pvfrd_array_info_range(const pvfrd_file *file, uint64_t step, uint64_t first,
                                    uint64_t count, pvfrd_array_info *out) {
  if (file == nullptr) return PVFRD_E_INVALID;
  if (count != 0 && out == nullptr) return PVFRD_E_INVALID;
  if (step >= file->document.n_steps()) return PVFRD_E_RANGE;
  const pvfrd::MaterialisedStep *materialised = file->document.step_arrays(step);
  if (materialised == nullptr) return PVFRD_E_RAGGED;

  const uint64_t total = static_cast<uint64_t>(materialised->arrays.size());
  /* Checked without adding first + count, which can wrap. */
  if (first > total || count > total - first) return PVFRD_E_RANGE;

  for (uint64_t i = 0; i < count; ++i) {
    const pvfrd::Array &array = materialised->arrays[first + i];
    out[i].name = array.name.c_str();
    out[i].n_components = array.n_components;
    out[i].n_tuples = file->document.n_points();
    out[i].kind = array.kind;
  }
  return PVFRD_OK;
}

pvfrd_status pvfrd_array_data(const pvfrd_file *file, uint64_t step, uint64_t index,
                              const double **out) {
  if (file == nullptr || out == nullptr) return PVFRD_E_INVALID;
  *out = nullptr;
  if (step >= file->document.n_steps()) return PVFRD_E_RANGE;
  const pvfrd::MaterialisedStep *materialised = file->document.step_arrays(step);
  if (materialised == nullptr) return PVFRD_E_RAGGED;
  if (index >= materialised->arrays.size()) return PVFRD_E_RANGE;
  *out = materialised->arrays[index].data.data();
  return PVFRD_OK;
}

int64_t pvfrd_find_array(const pvfrd_file *file, uint64_t step, const char *name) {
  if (file == nullptr || name == nullptr) return -1;
  if (step >= file->document.n_steps()) return -1;
  const pvfrd::MaterialisedStep *materialised = file->document.step_arrays(step);
  if (materialised == nullptr) return -1;
  auto it = materialised->by_name.find(std::string(name));
  return it == materialised->by_name.end() ? -1 : static_cast<int64_t>(it->second);
}

}  // extern "C"

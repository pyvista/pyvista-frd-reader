/* The C ABI.
 *
 * Everything here is a thin translation between the header's plain-C surface
 * and the Document behind it. Two rules hold throughout:
 *
 *   - No exception escapes. Every entry point that can allocate is wrapped,
 *     because unwinding out of an `extern "C"` frame into a ctypes caller is
 *     undefined behaviour, and the caller most likely to hit it is the one
 *     least able to diagnose it. `guard()` below is how that is spelled;
 *     grep for it before adding an entry point that touches the Document.
 *
 *     Note which entry points allocate. It is not only the ones that build
 *     something: a step is materialised on first access, so the *readers* of
 *     a step -- n_arrays, array_info_range, array_data, find_array -- parse
 *     and allocate too. That is the sharp edge of the lazy path, and these
 *     four went unwrapped for exactly that reason.
 *   - A NULL argument is PVFRD_E_INVALID, never a crash. This library is
 *     bound dynamically from languages with no compiler to check the calls.
 */

#include <cstdio>
#include <cstring>
#include <new>
#include <stdexcept>
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
  /* _wfopen_s, not _wfopen: the latter is deprecated on MSVC and warns at
   * /W4, and silencing it with _CRT_SECURE_NO_WARNINGS would silence every
   * other one of these warnings too. */
  std::FILE *handle = nullptr;
  if (_wfopen_s(&handle, wide.c_str(), L"rb") != 0) return nullptr;
  return handle;
#else
  return std::fopen(path, "rb");
#endif
}

/* Where a failure goes when there is no reader to record it on.
 *
 * pvfrd_last_error takes a reader, and the open path has none yet -- so the
 * detail for the failure a caller is least equipped to guess at had nowhere
 * to live, and the Python binding papered over it by reporting the path it
 * had passed in. Thread-local rather than global because two threads opening
 * two files must not overwrite each other's reason. */
std::string &thread_error() {
  static thread_local std::string message;
  return message;
}

void record(std::string message) {
  /* Assigning to a std::string can itself throw, and this runs on the failure
   * path, sometimes while handling bad_alloc. Losing the message is
   * acceptable; throwing out of a catch block is not. */
  try {
    thread_error() = std::move(message);
  } catch (...) {
    // NOLINT(bugprone-empty-catch) -- see above
  }
}

/* Run `body` and translate anything it throws into a status.
 *
 * The mapping is deliberately specific. An earlier version ended in
 * `catch (...) { return PVFRD_E_FORMAT; }`, which reports every unexpected
 * failure -- a library bug, a mutex refusing to lock, an allocation too large
 * to express -- as "the file did not parse as an FRD document". That is a
 * misdiagnosis with consequences: it sends someone to inspect a file that is
 * perfectly good. A fault in here is PVFRD_E_INTERNAL and says so. */
template <typename Body>
pvfrd_status guard(Body body) {
  try {
    return body();
  } catch (const std::bad_alloc &) {
    record("allocation failed");
    return PVFRD_E_NOMEM;
  } catch (const std::length_error &e) {
    /* A resize or reserve beyond max_size(). Reached by a file large enough
     * that its arrays cannot be expressed on this platform -- a 32-bit or
     * WebAssembly build long before a 64-bit one. Out of memory in substance,
     * whatever the type says. */
    record(std::string("size beyond what this platform can express: ") + e.what());
    return PVFRD_E_NOMEM;
  } catch (const std::exception &e) {
    record(std::string("internal error: ") + e.what());
    return PVFRD_E_INTERNAL;
  } catch (...) {
    record("internal error: an exception not derived from std::exception");
    return PVFRD_E_INTERNAL;
  }
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

  return guard([&]() -> pvfrd_status {
    auto *file = new pvfrd_file(std::move(buffer), opts);
    pvfrd_status status = file->document.parse();
    if (status != PVFRD_OK) {
      /* Carry the reason across the delete. The reader is about to stop
       * existing, and with it the only place pvfrd_last_error could have read
       * it from. */
      record(file->document.last_error());
      delete file;
      return status;
    }
    *out = file;
    return PVFRD_OK;
  });
}

}  // namespace

extern "C" {

uint32_t pvfrd_abi_version(void) {
  return PVFRD_ABI_VERSION;
}

uint32_t pvfrd_struct_size(int which) {
  switch (which) {
    case PVFRD_STRUCT_OPEN_OPTIONS: return static_cast<uint32_t>(sizeof(pvfrd_open_options));
    case PVFRD_STRUCT_ARRAY_INFO: return static_cast<uint32_t>(sizeof(pvfrd_array_info));
    case PVFRD_STRUCT_DIAGNOSTIC: return static_cast<uint32_t>(sizeof(pvfrd_diagnostic));
    default: return 0;
  }
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
    case PVFRD_E_INTERNAL: return "an unexpected error inside the library; please report it";
    default: return "unknown status";
  }
}

const char *pvfrd_last_error(const pvfrd_file *file) {
  /* NULL is not a misuse here. It is the open path asking why it failed,
   * which is the question with no reader to put it to. */
  if (file == nullptr) return thread_error().c_str();
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
  if (handle == nullptr) {
    record("the file could not be opened for reading");
    return PVFRD_E_IO;
  }
  /* Closed by scope rather than by hand. The read below can leave through
   * more exits than it used to -- length_error as well as bad_alloc -- and a
   * descriptor leaked on the failure path is the kind of thing that only
   * shows up in a long-running process reading many files. */
  struct Closer {
    std::FILE *handle;
    ~Closer() {
      if (handle != nullptr) std::fclose(handle);
    }
  } closer{handle};

  std::string buffer;
  const pvfrd_status read_status = guard([&]() -> pvfrd_status {
    /* Read straight into the string's own storage. The obvious spelling of
     * this loop puts a `char chunk[1 << 16]` on the stack, and 64 KiB of
     * stack is more than some perfectly ordinary targets give a whole thread
     * -- it is the entire default stack under Emscripten, where this
     * overflowed on the first file it was handed. Growing the destination and
     * reading into it costs nothing and drops a copy per chunk.
     *
     * resize() throws length_error, not bad_alloc, once the total passes
     * max_size(). That is reachable on a 32-bit or WebAssembly build long
     * before a 64-bit one, and guard() is what maps it to PVFRD_E_NOMEM
     * rather than letting it leave through an extern "C" frame. */
    constexpr size_t kChunk = size_t{1} << 16;
    for (;;) {
      const size_t offset = buffer.size();
      buffer.resize(offset + kChunk);
      const size_t got = std::fread(&buffer[offset], 1, kChunk, handle);
      buffer.resize(offset + got);
      if (got < kChunk) break;
    }
    if (std::ferror(handle) != 0) {
      record("the file could not be read to the end");
      return PVFRD_E_IO;
    }
    return PVFRD_OK;
  });
  if (read_status != PVFRD_OK) return read_status;

  std::fclose(closer.handle);
  closer.handle = nullptr;

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
  /* Guarded because step_arrays parses on first access. Asking how many
   * arrays a step has is what causes them to exist. */
  return guard([&]() -> pvfrd_status {
    const pvfrd::MaterialisedStep *materialised = file->document.step_arrays(step);
    if (materialised == nullptr) return PVFRD_E_RAGGED;
    *out = static_cast<uint64_t>(materialised->arrays.size());
    return PVFRD_OK;
  });
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
  return guard([&]() -> pvfrd_status {
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
  });
}

pvfrd_status pvfrd_array_data(const pvfrd_file *file, uint64_t step, uint64_t index,
                              const double **out) {
  if (file == nullptr || out == nullptr) return PVFRD_E_INVALID;
  *out = nullptr;
  if (step >= file->document.n_steps()) return PVFRD_E_RANGE;
  return guard([&]() -> pvfrd_status {
    const pvfrd::MaterialisedStep *materialised = file->document.step_arrays(step);
    if (materialised == nullptr) return PVFRD_E_RAGGED;
    if (index >= materialised->arrays.size()) return PVFRD_E_RANGE;
    *out = materialised->arrays[index].data.data();
    return PVFRD_OK;
  });
}

uint64_t pvfrd_steps_parsed(const pvfrd_file *file) {
  return file == nullptr ? 0 : file->document.steps_parsed();
}

int64_t pvfrd_find_array(const pvfrd_file *file, uint64_t step, const char *name) {
  if (file == nullptr || name == nullptr) return -1;
  if (step >= file->document.n_steps()) return -1;
  /* This one reports failure as -1 rather than a status, so it cannot use
   * guard() -- but it still materialises a step and still builds a
   * std::string from `name`, either of which can throw. -1 already means "no
   * such array", which is the truthful answer when the lookup could not be
   * performed; the reason lands in the thread-local slot for a caller who
   * wants to tell the two apart. */
  int64_t found = -1;
  const pvfrd_status status = guard([&]() -> pvfrd_status {
    const pvfrd::MaterialisedStep *materialised = file->document.step_arrays(step);
    if (materialised == nullptr) return PVFRD_E_RAGGED;
    auto it = materialised->by_name.find(std::string(name));
    if (it != materialised->by_name.end()) found = static_cast<int64_t>(it->second);
    return PVFRD_OK;
  });
  return (status == PVFRD_OK) ? found : -1;
}

}  // extern "C"

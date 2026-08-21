/* pvfrd -- C ABI for reading CalculiX FRD (.frd) result files.
 *
 * This header is the whole public surface. It is plain C with no C++ types
 * crossing the boundary, so it binds from ctypes, from another C++ project
 * consuming this as a submodule, or from WebAssembly, without a Python
 * extension module anywhere in the picture.
 *
 * Two things a caller should know before reading further:
 *
 *   - Opening a file parses the mesh and *indexes* the result blocks. The
 *     values of a time step are materialised when that step is first asked
 *     for, so opening a 500-step file and reading one step does not pay for
 *     the other 499.
 *   - Every pointer returned by an accessor is owned by the reader and stays
 *     valid until pvfrd_close(). Do not free them. A reader is immutable
 *     apart from that per-step materialisation, which is guarded, so several
 *     threads may read from one reader concurrently.
 *
 * The behavioural contract is pyvista's `FRDReader`: this library exists to
 * produce the same arrays that reader produces, from the same bytes. Where it
 * deliberately differs, doc/divergences.md says so and names the test that
 * pins the difference.
 */

#ifndef PVFRD_PVFRD_H
#define PVFRD_PVFRD_H

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32) && defined(PVFRD_SHARED)
#if defined(PVFRD_BUILDING)
#define PVFRD_API __declspec(dllexport)
#else
#define PVFRD_API __declspec(dllimport)
#endif
#elif defined(__GNUC__) && __GNUC__ >= 4
#define PVFRD_API __attribute__((visibility("default")))
#else
#define PVFRD_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Bumped on any change to the declarations below, additions included.
 *
 * Additions are bumped too because the check is an equality, not a floor: a
 * binding declares every symbol it knows about up front, so meeting an older
 * library missing one would fail at bind time with an error naming the symbol
 * rather than the version. Bumping keeps that mismatch reported as what it
 * is. */
#define PVFRD_ABI_VERSION 1u

typedef enum pvfrd_status {
  PVFRD_OK = 0,
  PVFRD_E_IO = 1,      /* file missing or unreadable */
  PVFRD_E_FORMAT = 2,  /* the file parsed but produced nothing usable */
  PVFRD_E_RANGE = 3,   /* index out of range, or destination too small */
  PVFRD_E_NOMEM = 4,   /* allocation failed */
  PVFRD_E_INVALID = 5, /* NULL argument or misuse */
  PVFRD_E_RAGGED = 6,  /* a result block gave two nodes different component
                        * counts; see pvfrd_last_error for which */
  PVFRD_E_INTERNAL = 7 /* an unexpected failure inside the library, not a
                        * property of the file. Distinct from PVFRD_E_FORMAT
                        * on purpose: reporting a library fault as a bad file
                        * sends the caller to inspect a file that is fine.
                        * pvfrd_last_error carries what() where there was
                        * one. Please report it. */
} pvfrd_status;

/* CalculiX element type codes, as they appear in the second field of a `-1`
 * record inside a `3C` block. */
typedef enum pvfrd_element_type {
  PVFRD_HE8 = 1,
  PVFRD_PE6 = 2,
  PVFRD_TE4 = 3,
  PVFRD_HE20 = 4,
  PVFRD_PE15 = 5,
  PVFRD_TE10 = 6,
  PVFRD_TR3 = 7,
  PVFRD_TR6 = 8,
  PVFRD_QU4 = 9,
  PVFRD_QU8 = 10,
  PVFRD_BE2 = 11,
  PVFRD_BE3 = 12,
  PVFRD_PY5 = 15, /* experimental pyramid, CalculiX C3D5 */
  PVFRD_PY13 = 16 /* experimental pyramid, CalculiX C3D13 */
} pvfrd_element_type;

/* How a PE6 (linear wedge) has its nodes ordered on output.
 *
 * This is an option rather than a constant because the answer is a property
 * of the *consumer*, not of the file: VTK changed its wedge node order at
 * 9.7, and this library cannot see which VTK its caller will hand the cells
 * to. There is deliberately no "detect" value -- there is nothing here to
 * detect from.
 *
 * PVFRD_WEDGE_SWAP reproduces what pyvista does on VTK < 9.7: nodes 1 and 2
 * are exchanged, and 4 and 5 with them. PVFRD_WEDGE_ASIS passes CalculiX's
 * order through, which is what VTK >= 9.7 wants. */
typedef enum pvfrd_wedge_order { PVFRD_WEDGE_ASIS = 0, PVFRD_WEDGE_SWAP = 1 } pvfrd_wedge_order;

/* Why an element was reported as questionable. The reader keeps parsing in
 * every case; TOO_FEW and UNSUPPORTED elements are dropped from the mesh,
 * TOO_MANY are kept and truncated to the cell's point count. */
typedef enum pvfrd_diagnostic_kind {
  PVFRD_DIAG_TOO_MANY_POINTS = 0,
  PVFRD_DIAG_TOO_FEW_POINTS = 1,
  PVFRD_DIAG_UNSUPPORTED_ELEMENT = 2
} pvfrd_diagnostic_kind;

/* Whether an array came off the file or was computed from one that did. */
typedef enum pvfrd_array_kind { PVFRD_ARRAY_RAW = 0, PVFRD_ARRAY_DERIVED = 1 } pvfrd_array_kind;

typedef struct pvfrd_file pvfrd_file;

/* Options for pvfrd_open_ex. Zero-initialise and set what you need; a
 * zeroed struct is the documented default (PVFRD_WEDGE_ASIS). */
typedef struct pvfrd_open_options {
  int32_t wedge_order; /* one of pvfrd_wedge_order */
  int32_t reserved;    /* must be 0 */
} pvfrd_open_options;

typedef struct pvfrd_array_info {
  const char *name; /* NUL-terminated, owned by the reader */
  uint64_t n_tuples;
  uint32_t n_components;
  int32_t kind; /* one of pvfrd_array_kind */
} pvfrd_array_info;

typedef struct pvfrd_diagnostic {
  int32_t kind;         /* one of pvfrd_diagnostic_kind */
  int32_t element_type; /* the raw code from the file, valid or not */
  int64_t line;         /* 1-based line of the element's `-1` record */
  int64_t n_expected;   /* -1 when the element type was not recognised */
  int64_t n_actual;     /* -1 when the element type was not recognised */
} pvfrd_diagnostic;

/* ---- Library ---- */

PVFRD_API uint32_t pvfrd_abi_version(void);

/* Which struct pvfrd_struct_size is being asked about. */
typedef enum pvfrd_struct {
  PVFRD_STRUCT_OPEN_OPTIONS = 0,
  PVFRD_STRUCT_ARRAY_INFO = 1,
  PVFRD_STRUCT_DIAGNOSTIC = 2
} pvfrd_struct;

/* Size in bytes of one of the structs above, as this library was compiled.
 * Returns 0 for an unknown value.
 *
 * A binding that declares these layouts by hand -- which is every
 * foreign-function binding, including the ctypes one shipped with this
 * package -- has no compiler checking it. A field in the wrong order, or an
 * int where an int64 belongs, produces garbage rather than an error, and it
 * produces it only on the platform whose alignment rules differ from the one
 * the binding was written on. Comparing sizes catches that at the point where
 * it can still be reported. */
PVFRD_API uint32_t pvfrd_struct_size(int which);

/* A short, stable description of a status code. Never NULL. */
PVFRD_API const char *pvfrd_status_message(int status);

/* The last failure recorded on this reader, or "" if none. Owned by the
 * reader. Carries the detail a status code cannot -- which array was ragged,
 * which line refused to parse.
 *
 * `file` may be NULL, and that is the case worth knowing about: a failure in
 * pvfrd_open leaves no reader to ask, which is exactly when the caller most
 * needs the detail. With NULL this returns the last failure recorded on the
 * *calling thread* instead, so the open path has somewhere to put it.
 *
 * The thread-local message is valid until the next failing call on the same
 * thread. Copy it if you intend to keep it. Never NULL. */
PVFRD_API const char *pvfrd_last_error(const pvfrd_file *file);

/* ---- Opening ---- */

/* Open by path. Equivalent to pvfrd_open_ex with zeroed options.
 *
 * `path` is UTF-8 on every platform, including Windows, where it is converted
 * to UTF-16 internally. Passing bytes in the active code page instead would
 * open the wrong file for any path outside ASCII. */
PVFRD_API pvfrd_status pvfrd_open(const char *path, pvfrd_file **out);

PVFRD_API pvfrd_status pvfrd_open_ex(const char *path, const pvfrd_open_options *options,
                                     pvfrd_file **out);

/* Open from bytes already in memory. The buffer is copied, so the caller may
 * release it as soon as this returns. `options` may be NULL.
 *
 * This exists so a caller holding the file in an archive member, an HTTP
 * response, or a memory-mapped blob does not have to invent a temporary file
 * to read it. */
PVFRD_API pvfrd_status pvfrd_open_memory(const void *data, size_t size,
                                         const pvfrd_open_options *options, pvfrd_file **out);

/* Release a reader. Safe to call with NULL. */
PVFRD_API void pvfrd_close(pvfrd_file *file);

/* ---- Mesh ----
 *
 * Points are ordered by ascending node id, which is what makes the point
 * index deterministic and independent of the order nodes appear in the file.
 * pvfrd_node_ids gives the original ids in that same order. */

PVFRD_API uint64_t pvfrd_n_points(const pvfrd_file *file);

/* 3 * n_points doubles, xyz interleaved. */
PVFRD_API const double *pvfrd_points(const pvfrd_file *file);

/* n_points ids, strictly ascending. */
PVFRD_API const int64_t *pvfrd_node_ids(const pvfrd_file *file);

PVFRD_API uint64_t pvfrd_n_cells(const pvfrd_file *file);

/* One VTK cell type per cell. */
PVFRD_API const uint8_t *pvfrd_cell_types(const pvfrd_file *file);

/* n_cells + 1 offsets into the connectivity array (VTK 9 form). */
PVFRD_API const int64_t *pvfrd_cell_offsets(const pvfrd_file *file);

/* Zero-based point indices; pvfrd_cell_offsets[n_cells] entries in total. */
PVFRD_API const int64_t *pvfrd_cell_connectivity(const pvfrd_file *file);

/* ---- Diagnostics ----
 *
 * Available immediately after open: they come out of the element block, which
 * is parsed eagerly. A caller that wants to warn before touching results can
 * do so without materialising any. */

PVFRD_API uint64_t pvfrd_n_diagnostics(const pvfrd_file *file);

PVFRD_API pvfrd_status pvfrd_diagnostic_at(const pvfrd_file *file, uint64_t index,
                                           pvfrd_diagnostic *out);

/* ---- Time steps ---- */

PVFRD_API uint64_t pvfrd_n_steps(const pvfrd_file *file);

/* Step times, ascending. Steps sharing a time value are one step here, as
 * they are one dictionary entry in the reference reader. */
PVFRD_API pvfrd_status pvfrd_step_time(const pvfrd_file *file, uint64_t step, double *out);

/* ---- Result arrays ----
 *
 * Arrays are addressed by index within a step, in the order their blocks
 * appeared in the file, with each derived array immediately following the one
 * it was computed from. That order is part of the contract: a caller
 * comparing two implementations compares array i with array i.
 *
 * The first call for a given step materialises it. Later calls are lookups. */

PVFRD_API pvfrd_status pvfrd_n_arrays(const pvfrd_file *file, uint64_t step, uint64_t *out);

PVFRD_API pvfrd_status pvfrd_array_info_at(const pvfrd_file *file, uint64_t step, uint64_t index,
                                           pvfrd_array_info *out);

/* Describe `count` arrays starting at `first`.
 *
 * The same information as calling pvfrd_array_info_at in a loop; the point is
 * that it is one crossing of the boundary rather than one per array. A caller
 * reaching this library through a foreign-function layer pays a fixed cost
 * per call that can exceed the work being asked for, and a step holds one
 * array per result block plus five more for every tensor, so describing a
 * step was paying that cost a dozen times to copy a few hundred bytes.
 *
 * Returns PVFRD_E_RANGE and writes nothing if first + count runs past the
 * end. A count of zero succeeds and writes nothing. */
PVFRD_API pvfrd_status pvfrd_array_info_range(const pvfrd_file *file, uint64_t step, uint64_t first,
                                              uint64_t count, pvfrd_array_info *out);

/* n_tuples * n_components doubles, component-major within a tuple. Nodes the
 * block did not mention are zero, which is what the reference reader does. */
PVFRD_API pvfrd_status pvfrd_array_data(const pvfrd_file *file, uint64_t step, uint64_t index,
                                        const double **out);

/* Index of the array called `name` within `step`, or -1 if there is none. */
PVFRD_API int64_t pvfrd_find_array(const pvfrd_file *file, uint64_t step, const char *name);

/* How many times a step's values have been parsed.
 *
 * Zero immediately after opening. For correct behaviour it equals the number
 * of *distinct* steps a caller has asked about, because a step is parsed at
 * most once and every later request is a lookup.
 *
 * Exposed because both halves of that are otherwise unverifiable claims. A
 * reader that parsed everything up front, or that re-parsed on every request,
 * would return identical arrays and identical timings on any file small
 * enough to sit in page cache -- the only thing separating the designs is
 * what a large file costs. Counting parses is what tells them apart, and it
 * counts parses rather than parsed steps so that a re-parse is visible at
 * all. */
PVFRD_API uint64_t pvfrd_steps_parsed(const pvfrd_file *file);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* PVFRD_PVFRD_H */

/* The writing half of the C ABI.
 *
 * Two entry points with quite different guarantees, and the difference is
 * worth being explicit about because only one of them is checked against
 * CalculiX's own bytes.
 *
 *   pvfrd_rewrite_memory   reads a document and emits it again. With
 *                          PVFRD_FORMAT_KEEP this is the identity over every
 *                          FRD file this project could find, so the emitter's
 *                          field layout is checked against files nobody here
 *                          wrote. That is the gate.
 *
 *   pvfrd_writer_*         builds a document from a mesh and some arrays.
 *                          The records go through the same emitter, so the
 *                          gate covers them; what it cannot cover is the
 *                          header lines, which have no original to be
 *                          compared against. Those are checked by writing a
 *                          file and having CalculiX read it back -- see
 *                          doc/writing.md, which also records what that does
 *                          and does not establish.
 */

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <new>
#include <string>
#include <vector>

#include "document.h"
#include "frd.h"
#include "pvfrd/pvfrd.h"

namespace {

using pvfrd::RawBlock;
using pvfrd::RawDocument;
using pvfrd::RawElement;
using pvfrd::RawNode;
using pvfrd::RawRecord;

/* VTK cell type -> CalculiX element code. The inverse of the table in
 * parse.cpp, written out rather than searched for, so that a type this
 * library can read but not write is a compile-time visible omission. */
bool calculix_code_for(uint8_t vtk_type, int64_t *code, uint32_t *n_points) {
  switch (vtk_type) {
    case 12:
      *code = PVFRD_HE8;
      *n_points = 8;
      return true;
    case 13:
      *code = PVFRD_PE6;
      *n_points = 6;
      return true;
    case 10:
      *code = PVFRD_TE4;
      *n_points = 4;
      return true;
    case 25:
      *code = PVFRD_HE20;
      *n_points = 20;
      return true;
    case 26:
      *code = PVFRD_PE15;
      *n_points = 15;
      return true;
    case 24:
      *code = PVFRD_TE10;
      *n_points = 10;
      return true;
    case 5:
      *code = PVFRD_TR3;
      *n_points = 3;
      return true;
    case 22:
      *code = PVFRD_TR6;
      *n_points = 6;
      return true;
    case 9:
      *code = PVFRD_QU4;
      *n_points = 4;
      return true;
    case 23:
      *code = PVFRD_QU8;
      *n_points = 8;
      return true;
    case 3:
      *code = PVFRD_BE2;
      *n_points = 2;
      return true;
    case 21:
      *code = PVFRD_BE3;
      *n_points = 3;
      return true;
    case 14:
      *code = PVFRD_PY5;
      *n_points = 5;
      return true;
    case 27:
      *code = PVFRD_PY13;
      *n_points = 13;
      return true;
    default: return false;
  }
}

/* CalculiX order from VTK order: the inverse of parse.cpp's `permute`.
 *
 * Every one of these happens to be an involution, so the same code would
 * invert itself -- which is exactly why it is written out separately instead.
 * A table that is its own inverse today is not a property anyone declared,
 * and the first element type whose ordering is a rotation rather than a swap
 * would turn a silent reuse into a silently wrong file. WriteTest requires
 * the two to compose to the identity for every supported type. */
std::vector<int64_t> unpermute(const std::vector<int64_t> &vtk, int64_t code, int32_t wedge_order) {
  std::vector<int64_t> out;
  out.reserve(vtk.size());
  auto take = [&](size_t begin, size_t end) {
    for (size_t i = begin; i < end && i < vtk.size(); ++i) out.push_back(vtk[i]);
  };

  if (code == PVFRD_HE20) {
    /* Read swaps the two four-node bands; writing swaps them back. */
    take(0, 8);
    take(8, 12);
    take(16, 20);
    take(12, 16);
  } else if (code == PVFRD_PE6 && wedge_order == PVFRD_WEDGE_SWAP) {
    const size_t order[6] = {0, 2, 1, 3, 5, 4};
    for (size_t i : order) {
      if (i < vtk.size()) out.push_back(vtk[i]);
    }
  } else if (code == PVFRD_PE15) {
    take(0, 9);
    take(12, 15);
    take(9, 12);
  } else {
    take(0, vtk.size());
  }
  return out;
}

/* Header lines in CalculiX's own column layout, measured from its output:
 * a `2C` or `3C` header is 74 columns with the record count ending at 36 and
 * the format code at 74. Synthesised rather than copied because a document
 * built from a mesh has no original header to copy. */
std::string block_header(const char *key, int64_t count, int format) {
  char buffer[128];
  std::snprintf(buffer, sizeof(buffer), "    %s%30lld%38d", key, static_cast<long long>(count),
                format);
  return buffer;
}

std::string step_header(int32_t number, double time, int64_t count, int format) {
  /* The time field is 12 columns. Fixed point while it fits, which is what
   * CalculiX writes for the ordinary case, and scientific when it does not --
   * a 12-column field cannot hold 1234567.891234567 any other way. */
  char clock[32];
  std::snprintf(clock, sizeof(clock), "%12.9f", time);
  if (std::strlen(clock) > 12) std::snprintf(clock, sizeof(clock), "%12.5E", time);

  char buffer[192];
  std::snprintf(buffer, sizeof(buffer), "  100CL%5d%s%12lld%22d%5d%12d", number, clock,
                static_cast<long long>(count), 0, 1, format);
  return buffer;
}

std::string pstep_line(int32_t number) {
  char buffer[128];
  std::snprintf(buffer, sizeof(buffer), "    1PSTEP%26d%12d%12d          ", number, 1, 1);
  return buffer;
}

/* The name field is eight columns and CalculiX truncates to fit -- there are
 * names in its own corpus like `CT3D-MIS` that were plainly longer once. This
 * writer does not truncate, and pads short names instead.
 *
 * Truncating an array called `STRESS_Mises` gives `STRESS_M`, which is also
 * what `STRESS_sgMises` gives, so a mesh carrying both loses one of them to a
 * name collision on the way out. Silently. Overflowing the field costs
 * alignment with a strict fixed-width consumer -- the numbers after the name
 * shift right, and every reader involved here splits that line on whitespace
 * -- which is a smaller price than merging two of the caller's arrays. */
std::string padded(const std::string &name) {
  return name.size() >= 8 ? name : name + std::string(8 - name.size(), ' ');
}

std::string attribute_line(const std::string &name, uint32_t n_components, int32_t ictype) {
  char buffer[512];
  std::snprintf(buffer, sizeof(buffer), " -4  %s%5u%5d", padded(name).c_str(), n_components,
                ictype);
  return buffer;
}

std::string component_line(const std::string &name, int32_t ictype, int32_t first, int32_t second) {
  char buffer[512];
  std::snprintf(buffer, sizeof(buffer), " -5  %s%5d%5d%5d%5d", padded(name).c_str(), 1, ictype,
                first, second);
  return buffer;
}

/* A name with whitespace in it would split into two fields and be read back as
 * a different name with a stray number after it. */
bool name_is_usable(const char *name) {
  if (name == nullptr || *name == '\0') return false;
  for (const char *c = name; *c != '\0'; ++c) {
    if (*c == ' ' || *c == '\t' || *c == '\n' || *c == '\r') return false;
  }
  return true;
}

int32_t ictype_for(uint32_t n_components) {
  if (n_components == 3) return 2; /* vector */
  if (n_components == 6) return 4; /* tensor */
  return 1;                        /* scalar */
}

}  // namespace

struct pvfrd_writer {
  int format = PVFRD_FORMAT_LONG_ASCII;
  std::string newline = "\n";
  bool finished = false;

  std::vector<int64_t> node_ids;
  std::vector<double> xyz;

  RawBlock nodes;
  RawBlock elements;
  std::vector<RawBlock> results;

  bool has_open_step = false;
  int32_t step_number = 0;
  double step_time = 0.0;
};

extern "C" {

void pvfrd_free(char *buffer) {
  delete[] buffer;
}

static pvfrd_status hand_back(const std::string &text, char **out, size_t *out_size) {
  char *buffer = new (std::nothrow) char[text.size() + 1];
  if (buffer == nullptr) return PVFRD_E_NOMEM;
  std::memcpy(buffer, text.data(), text.size());
  buffer[text.size()] = '\0';
  *out = buffer;
  *out_size = text.size();
  return PVFRD_OK;
}

pvfrd_status pvfrd_rewrite_memory(const void *data, size_t size, int32_t format, char **out,
                                  size_t *out_size) {
  if (data == nullptr || out == nullptr || out_size == nullptr) return PVFRD_E_INVALID;
  if (format < PVFRD_FORMAT_KEEP || format > PVFRD_FORMAT_BINARY_DOUBLE) return PVFRD_E_INVALID;
  *out = nullptr;
  *out_size = 0;

  const std::string buffer(static_cast<const char *>(data), size);
  RawDocument document;
  std::string error;
  const pvfrd_status status = pvfrd::parse_raw(buffer, &document, &error);
  if (status != PVFRD_OK) {
    pvfrd::set_thread_error(error);
    return status;
  }
  std::string why;
  if (!pvfrd::can_emit_as(document, format, &why)) {
    pvfrd::set_thread_error("cannot convert this document to format " + std::to_string(format) +
                            ": " + why);
    return PVFRD_E_FORMAT;
  }
  return hand_back(pvfrd::emit_raw(document, format), out, out_size);
}

pvfrd_writer *pvfrd_writer_new(int32_t format) {
  if (format < PVFRD_FORMAT_SHORT_ASCII || format > PVFRD_FORMAT_BINARY_DOUBLE) return nullptr;
  pvfrd_writer *writer = new (std::nothrow) pvfrd_writer();
  if (writer != nullptr) writer->format = format;
  return writer;
}

void pvfrd_writer_free(pvfrd_writer *writer) {
  delete writer;
}

pvfrd_status pvfrd_writer_set_nodes(pvfrd_writer *writer, uint64_t n_points,
                                    const int64_t *node_ids, const double *xyz) {
  if (writer == nullptr || writer->finished) return PVFRD_E_INVALID;
  if (n_points != 0 && xyz == nullptr) return PVFRD_E_INVALID;

  writer->node_ids.clear();
  writer->node_ids.reserve(n_points);
  for (uint64_t i = 0; i < n_points; ++i) {
    writer->node_ids.push_back(node_ids != nullptr ? node_ids[i] : static_cast<int64_t>(i + 1));
  }

  writer->nodes = RawBlock();
  writer->nodes.kind = RawBlock::kNodes;
  writer->nodes.format = writer->format;
  writer->nodes.declared = static_cast<int64_t>(n_points);
  writer->nodes.nodes.reserve(n_points);
  for (uint64_t i = 0; i < n_points; ++i) {
    RawNode node;
    node.id = writer->node_ids[i];
    node.xyz[0] = xyz[i * 3 + 0];
    node.xyz[1] = xyz[i * 3 + 1];
    node.xyz[2] = xyz[i * 3 + 2];
    writer->nodes.items.push_back(
        {static_cast<int64_t>(writer->nodes.nodes.size()), std::string()});
    writer->nodes.nodes.push_back(node);
  }
  return PVFRD_OK;
}

pvfrd_status pvfrd_writer_set_cells(pvfrd_writer *writer, uint64_t n_cells,
                                    const uint8_t *cell_types, const int64_t *offsets,
                                    const int64_t *connectivity, const int64_t *cell_ids,
                                    int32_t wedge_order) {
  if (writer == nullptr || writer->finished) return PVFRD_E_INVALID;
  if (n_cells != 0 && (cell_types == nullptr || offsets == nullptr || connectivity == nullptr)) {
    return PVFRD_E_INVALID;
  }
  if (wedge_order != PVFRD_WEDGE_ASIS && wedge_order != PVFRD_WEDGE_SWAP) return PVFRD_E_INVALID;

  writer->elements = RawBlock();
  writer->elements.kind = RawBlock::kElements;
  /* Element records hold no floats, so CalculiX writes them in format 2 in
   * any binary file and in the ASCII width otherwise. */
  writer->elements.format =
      (writer->format >= PVFRD_FORMAT_BINARY_FLOAT) ? PVFRD_FORMAT_BINARY_FLOAT : writer->format;
  writer->elements.declared = static_cast<int64_t>(n_cells);

  for (uint64_t c = 0; c < n_cells; ++c) {
    int64_t code = 0;
    uint32_t needed = 0;
    if (!calculix_code_for(cell_types[c], &code, &needed)) {
      char message[160];
      std::snprintf(message, sizeof(message),
                    "cell %llu has VTK type %u, which has no CalculiX element code",
                    static_cast<unsigned long long>(c), static_cast<unsigned>(cell_types[c]));
      pvfrd::set_thread_error(message);
      return PVFRD_E_FORMAT;
    }
    const int64_t begin = offsets[c];
    const int64_t end = offsets[c + 1];
    if (end < begin || static_cast<uint64_t>(end - begin) != needed) {
      char message[160];
      std::snprintf(message, sizeof(message), "cell %llu has %lld points, but its type needs %u",
                    static_cast<unsigned long long>(c), static_cast<long long>(end - begin),
                    static_cast<unsigned>(needed));
      pvfrd::set_thread_error(message);
      return PVFRD_E_FORMAT;
    }

    std::vector<int64_t> ids;
    ids.reserve(needed);
    for (int64_t i = begin; i < end; ++i) {
      const int64_t index = connectivity[i];
      if (index < 0 || static_cast<uint64_t>(index) >= writer->node_ids.size()) {
        pvfrd::set_thread_error("cell connectivity refers to a point that is not in the mesh");
        return PVFRD_E_FORMAT;
      }
      ids.push_back(writer->node_ids[static_cast<size_t>(index)]);
    }

    RawElement element;
    element.id = cell_ids != nullptr ? cell_ids[c] : static_cast<int64_t>(c + 1);
    element.type = code;
    element.group = 1;
    element.material = 1;
    element.nodes = unpermute(ids, code, wedge_order);
    writer->elements.items.push_back(
        {static_cast<int64_t>(writer->elements.elements.size()), std::string()});
    writer->elements.elements.push_back(std::move(element));
  }
  return PVFRD_OK;
}

pvfrd_status pvfrd_writer_begin_step(pvfrd_writer *writer, int32_t number, double time) {
  if (writer == nullptr || writer->finished) return PVFRD_E_INVALID;
  writer->has_open_step = true;
  writer->step_number = number;
  writer->step_time = time;
  return PVFRD_OK;
}

pvfrd_status pvfrd_writer_add_array(pvfrd_writer *writer, const char *name, uint32_t n_components,
                                    const char *const *component_names, int32_t ictype,
                                    const double *values) {
  if (writer == nullptr || writer->finished || name == nullptr) return PVFRD_E_INVALID;
  if (!writer->has_open_step) return PVFRD_E_INVALID;
  if (n_components == 0 || values == nullptr) return PVFRD_E_INVALID;
  if (!name_is_usable(name)) {
    pvfrd::set_thread_error(
        std::string("array name \"") + name +
        "\" is empty or contains whitespace, and would not survive being read back");
    return PVFRD_E_INVALID;
  }

  const uint64_t n_points = writer->node_ids.size();
  const int32_t kind = (ictype != 0) ? ictype : ictype_for(n_components);

  RawBlock block;
  block.kind = RawBlock::kResults;
  block.format = writer->format;
  block.declared = static_cast<int64_t>(n_points);
  block.n_components = n_components;

  block.lines.push_back(pstep_line(writer->step_number) + writer->newline);
  block.lines.push_back(step_header(writer->step_number, writer->step_time,
                                    static_cast<int64_t>(n_points), writer->format) +
                        writer->newline);
  block.lines.push_back(attribute_line(name, n_components, kind) + writer->newline);
  for (uint32_t k = 0; k < n_components; ++k) {
    std::string component;
    if (component_names != nullptr && component_names[k] != nullptr) {
      component = component_names[k];
    } else {
      component = std::string(name).substr(0, 6) + std::to_string(k + 1);
    }
    block.lines.push_back(component_line(component, kind, static_cast<int32_t>(k + 1), 0) +
                          writer->newline);
  }

  block.records.reserve(n_points);
  for (uint64_t i = 0; i < n_points; ++i) {
    RawRecord record;
    record.id = writer->node_ids[i];
    record.values.assign(values + i * n_components, values + (i + 1) * n_components);
    block.items.push_back({static_cast<int64_t>(block.records.size()), std::string()});
    block.records.push_back(std::move(record));
  }
  block.terminator = " -3" + writer->newline;

  writer->results.push_back(std::move(block));
  return PVFRD_OK;
}

pvfrd_status pvfrd_writer_finish(pvfrd_writer *writer, char **out, size_t *out_size) {
  if (writer == nullptr || out == nullptr || out_size == nullptr) return PVFRD_E_INVALID;
  if (writer->finished) return PVFRD_E_INVALID;
  writer->finished = true;
  *out = nullptr;
  *out_size = 0;

  RawDocument document;
  document.newline = writer->newline;

  RawBlock preamble;
  preamble.kind = RawBlock::kVerbatim;
  preamble.lines.push_back("    1C" + writer->newline);
  /* Named honestly. A file claiming CalculiX wrote it would make every
   * provenance check downstream a lie, including this project's own -- the
   * fixture suite identifies solver output by exactly this banner. */
  preamble.lines.push_back("    1UPGM               pyvista-frd-reader" + writer->newline);
  document.blocks.push_back(std::move(preamble));

  writer->nodes.lines.assign(
      {block_header("2C", static_cast<int64_t>(writer->nodes.nodes.size()), writer->nodes.format) +
       writer->newline});
  writer->nodes.terminator =
      (writer->nodes.format >= PVFRD_FORMAT_BINARY_FLOAT) ? "" : " -3" + writer->newline;
  document.blocks.push_back(writer->nodes);

  if (!writer->elements.elements.empty()) {
    writer->elements.lines.assign(
        {block_header("3C", static_cast<int64_t>(writer->elements.elements.size()),
                      writer->elements.format) +
         writer->newline});
    writer->elements.terminator =
        (writer->elements.format >= PVFRD_FORMAT_BINARY_FLOAT) ? "" : " -3" + writer->newline;
    document.blocks.push_back(writer->elements);
  }

  for (RawBlock &block : writer->results) {
    if (block.format >= PVFRD_FORMAT_BINARY_FLOAT) block.terminator.clear();
    document.blocks.push_back(block);
  }

  RawBlock trailer;
  trailer.kind = RawBlock::kVerbatim;
  trailer.lines.push_back(" 9999" + writer->newline);
  document.blocks.push_back(std::move(trailer));

  return hand_back(pvfrd::emit_raw(document, PVFRD_FORMAT_KEEP), out, out_size);
}

}  // extern "C"

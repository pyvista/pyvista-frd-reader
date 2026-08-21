/* The parse itself.
 *
 * The shape of this file follows the reference implementation deliberately,
 * including the state machine in parse_elements, because the behaviour being
 * copied is not always the behaviour a fresh implementation would choose. The
 * comments mark the places where that matters. Each one has a gtest named
 * after it.
 */

#include <algorithm>
#include <cstddef>
#include <cstring>
#include <string>
#include <utility>

#include "frd.h"
#include "text.h"

namespace pvfrd {
namespace {

/* Record markers, as they appear at the start of a stripped line.
 *
 * These are compared with startswith, not equality, exactly as the reference
 * does -- which means a line beginning "-30" enters the "-3" branch and ends
 * the block. Copied rather than corrected: a file relying on the difference
 * would read differently under the two implementations, and matching the
 * incumbent is the contract. */
constexpr std::string_view kNodalValues = "-1";
constexpr std::string_view kElementFaces = "-2";
constexpr std::string_view kEndOfBlock = "-3";
constexpr std::string_view kAttributeHeader = "-4";
constexpr std::string_view kComponentDefinition = "-5";

constexpr std::string_view kNodeBlock = "2C";
constexpr std::string_view kElementBlock = "3C";
constexpr std::string_view kResultBlock = "100";

/* The encoding a block's records use, declared by the last field of the
 * block's header line.
 *
 * CalculiX writes this from `frd.c`: the node header carries `one` for ASCII
 * and `three` for binary, the element header `one` and `two`. The two binary
 * codes are not interchangeable -- they say how wide a floating point value
 * is -- and the element block only ever uses 2 because its records hold no
 * floats at all.
 *
 * Reading these is not an extension of the format. It *is* the format; this
 * library simply did not implement half of it, which is why CalculiX's own
 * refined-mesh output (`*REFINE MESH` writes binary unconditionally, see
 * `writenewmesh.c`) read as an empty mesh. */
constexpr int kFormatShortAscii = 0;
constexpr int kFormatLongAscii = 1;
constexpr int kFormatBinaryFloat = 2;
constexpr int kFormatBinaryDouble = 3;

/* The integer prefix of a token, or -1 if it does not start with a digit.
 * FRD's component-definition lines run a flag and a name together. */
int64_t leading_int(std::string_view token) {
  size_t n = 0;
  while (n < token.size() && is_digit(token[n])) ++n;
  if (n == 0) return -1;
  int64_t value = 0;
  if (!parse_int(token.substr(0, n), &value)) return -1;
  return value;
}

bool is_binary_format(int format) {
  return format == kFormatBinaryFloat || format == kFormatBinaryDouble;
}

/* CalculiX writes its binary records with plain fwrite of native types, so
 * there is no marker to read the byte order from and no portable way to
 * discover it. Little-endian is assumed, which is right on every platform
 * this library ships wheels for. memcpy rather than a cast: the payload has
 * no alignment guarantee and type-punning through a pointer is undefined. */
int32_t read_i32_le(const char *p) {
  uint32_t bits = static_cast<uint8_t>(p[0]) |
                  (static_cast<uint32_t>(static_cast<uint8_t>(p[1])) << 8) |
                  (static_cast<uint32_t>(static_cast<uint8_t>(p[2])) << 16) |
                  (static_cast<uint32_t>(static_cast<uint8_t>(p[3])) << 24);
  int32_t out;
  std::memcpy(&out, &bits, sizeof(out));
  return out;
}

float read_f32_le(const char *p) {
  uint32_t bits = static_cast<uint8_t>(p[0]) |
                  (static_cast<uint32_t>(static_cast<uint8_t>(p[1])) << 8) |
                  (static_cast<uint32_t>(static_cast<uint8_t>(p[2])) << 16) |
                  (static_cast<uint32_t>(static_cast<uint8_t>(p[3])) << 24);
  float out;
  std::memcpy(&out, &bits, sizeof(out));
  return out;
}

double read_f64_le(const char *p) {
  uint64_t bits = 0;
  for (int i = 7; i >= 0; --i) {
    bits = (bits << 8) | static_cast<uint8_t>(p[i]);
  }
  double out;
  std::memcpy(&out, &bits, sizeof(out));
  return out;
}

/* A block header reads `<key> <count> ... <format>`; both numbers are
 * optional in files that other tools write, so a missing one falls back to
 * the ASCII behaviour this library had before. */
struct BlockHeader {
  int64_t count = -1;
  int format = kFormatLongAscii;
};

/* A result header reads `100CL <id> <time> <count> ... <format>`, so its
 * record count sits in a different field from the node and element headers.
 * Kept separate rather than generalised: one function that took the field
 * index as an argument would put the two conventions side by side in every
 * call and make the wrong one a plausible typo. */
/* Whether `offset` sits at the start of something that could be an FRD
 * header line, used to confirm a computed binary span landed where it should.
 * End of file counts: the last block in a file is followed by nothing. */
bool looks_like_header_at(std::string_view buffer, size_t offset) {
  while (offset < buffer.size() && (buffer[offset] == '\r' || buffer[offset] == '\n')) ++offset;
  if (offset >= buffer.size()) return true;
  size_t i = offset;
  while (i < buffer.size() && buffer[i] == ' ') ++i;
  if (i >= buffer.size()) return true;
  return is_digit(buffer[i]) || buffer[i] == '-';
}

BlockHeader parse_result_header(std::string_view header) {
  BlockHeader out;
  std::vector<std::string_view> parts = split(header);
  if (parts.size() >= 4) {
    int64_t value = 0;
    if (parse_int(parts[3], &value)) out.count = value;
  }
  if (parts.size() >= 5) {
    int64_t value = 0;
    if (parse_int(parts.back(), &value) && value >= kFormatShortAscii &&
        value <= kFormatBinaryDouble) {
      out.format = static_cast<int>(value);
    }
  }
  return out;
}

BlockHeader parse_block_header(std::string_view header) {
  BlockHeader out;
  std::vector<std::string_view> parts = split(header);
  if (parts.size() >= 2) {
    int64_t value = 0;
    if (parse_int(parts[1], &value)) out.count = value;
  }
  if (parts.size() >= 3) {
    int64_t value = 0;
    if (parse_int(parts.back(), &value) && value >= kFormatShortAscii &&
        value <= kFormatBinaryDouble) {
      out.format = static_cast<int>(value);
    }
  }
  return out;
}

struct CellSpec {
  uint8_t vtk_type;
  uint32_t n_points;
};

/* CalculiX element code -> VTK cell type and its point count.
 *
 * PY5/PY13 are CalculiX's experimental pyramids (C3D5/C3D13). They need no
 * permutation: CalculiX and VTK agree on pyramid node order. */
bool cell_spec_for(int64_t code, CellSpec *out) {
  switch (code) {
    case PVFRD_HE8: *out = {12, 8}; return true;   /* HEXAHEDRON */
    case PVFRD_PE6: *out = {13, 6}; return true;   /* WEDGE */
    case PVFRD_TE4: *out = {10, 4}; return true;   /* TETRA */
    case PVFRD_HE20: *out = {25, 20}; return true; /* QUADRATIC_HEXAHEDRON */
    case PVFRD_PE15: *out = {26, 15}; return true; /* QUADRATIC_WEDGE */
    case PVFRD_TE10: *out = {24, 10}; return true; /* QUADRATIC_TETRA */
    case PVFRD_TR3: *out = {5, 3}; return true;    /* TRIANGLE */
    case PVFRD_TR6: *out = {22, 6}; return true;   /* QUADRATIC_TRIANGLE */
    case PVFRD_QU4: *out = {9, 4}; return true;    /* QUAD */
    case PVFRD_QU8: *out = {23, 8}; return true;   /* QUADRATIC_QUAD */
    case PVFRD_BE2: *out = {3, 2}; return true;    /* LINE */
    case PVFRD_BE3: *out = {21, 3}; return true;   /* QUADRATIC_EDGE */
    case PVFRD_PY5: *out = {14, 5}; return true;   /* PYRAMID */
    case PVFRD_PY13: *out = {27, 13}; return true; /* QUADRATIC_PYRAMID */
    default: return false;
  }
}

/* CalculiX node order -> VTK node order.
 *
 * Only three types need reordering, and one of them depends on which VTK the
 * cells are destined for -- see pvfrd_wedge_order in the public header. The
 * slices below are the reference implementation's, transcribed: they also
 * truncate, which is what makes an element carrying too many nodes come out
 * with the right count rather than overflowing. */
std::vector<int64_t> permute(const std::vector<int64_t> &ids, int64_t code, uint32_t needed,
                             int32_t wedge_order) {
  std::vector<int64_t> out;
  out.reserve(needed);
  auto take = [&](size_t begin, size_t end) {
    for (size_t i = begin; i < end && i < ids.size(); ++i) out.push_back(ids[i]);
  };

  if (code == PVFRD_HE20) {
    /* ids[:8] + ids[8:12] + ids[16:20] + ids[12:16] */
    take(0, 8);
    take(8, 12);
    take(16, 20);
    take(12, 16);
  } else if (code == PVFRD_PE6 && wedge_order == PVFRD_WEDGE_SWAP) {
    /* [0, 2, 1, 3, 5, 4] -- VTK's wedge winding before 9.7. */
    const size_t order[6] = {0, 2, 1, 3, 5, 4};
    for (size_t i : order) out.push_back(ids[i]);
  } else if (code == PVFRD_PE15) {
    /* ids[:9] + ids[12:15] + ids[9:12] */
    take(0, 9);
    take(12, 15);
    take(9, 12);
  } else {
    take(0, ids.size());
  }

  if (out.size() > needed) out.resize(needed);
  return out;
}

/* Uppercase an ASCII string, matching what str.upper() does to the names
 * CalculiX writes. */
std::string ascii_upper(std::string_view s) {
  std::string out(s);
  for (char &c : out) {
    if (c >= 'a' && c <= 'z') c = static_cast<char>(c - 'a' + 'A');
  }
  return out;
}

bool contains(const std::string &haystack, std::string_view needle) {
  return haystack.find(needle) != std::string::npos;
}

/* `100CL 101 5.00000E-01 ...` -> (step id, step time).
 *
 * A header that does not parse becomes step 0.0, not an error: the reference
 * swallows both IndexError and ValueError here and carries on with a default,
 * so a malformed header merges that block into the zero-time step rather than
 * losing it. */
double step_time_of(std::string_view stripped) {
  std::vector<std::string_view> parts = split(stripped);
  if (parts.size() < 3) return 0.0;
  int64_t step_id = 0;
  double time = 0.0;
  if (!parse_int(parts[1], &step_id)) return 0.0;
  if (!parse_double(parts[2], &time)) return 0.0;
  return time;
}

}  // namespace

Document::Document(std::string buffer, pvfrd_open_options options)
    : buffer_(std::move(buffer)), options_(options) {}

void Document::parse_nodes(LineReader &reader) {
  std::string_view line;
  while (reader.next(&line)) {
    std::string_view s = strip(line);
    if (starts_with(s, kEndOfBlock)) return;
    if (!starts_with(s, kNodalValues)) continue;

    /* find on the raw line, startswith on the stripped one -- the reference
     * mixes the two, and the marker it finds is the first "-1" anywhere in
     * the line, which need not be the leading token. */
    size_t idx = line.find(kNodalValues);
    if (idx == std::string_view::npos) continue;

    std::string data = fix_scientific(line.substr(idx + kNodalValues.size()));
    std::vector<std::string_view> parts = split(data);

    /* A node needs at least id, x, y, z. Anything shorter is dropped in
     * silence, as is anything whose numbers refuse to parse: FRD files carry
     * unstructured text that happens to start with the nodal marker. */
    if (parts.size() < 4) continue;
    int64_t nid = 0;
    double xyz[3];
    if (!parse_int(parts[0], &nid)) continue;
    if (!parse_double(parts[1], &xyz[0])) continue;
    if (!parse_double(parts[2], &xyz[1])) continue;
    if (!parse_double(parts[3], &xyz[2])) continue;

    auto it = raw_node_slot_.find(nid);
    if (it == raw_node_slot_.end()) {
      raw_node_slot_.emplace(nid, raw_node_ids_.size());
      raw_node_ids_.push_back(nid);
      raw_node_xyz_.insert(raw_node_xyz_.end(), xyz, xyz + 3);
    } else {
      /* A repeated id overwrites, as a dict assignment does. */
      std::copy(xyz, xyz + 3, raw_node_xyz_.begin() + static_cast<ptrdiff_t>(it->second * 3));
    }
  }
}

/* Nodes, binary. One record is a 4-byte id followed by three coordinates,
 * each 4 bytes under format 2 and 8 under format 3.
 *
 * Returns false on a short buffer, which the caller turns into an error. A
 * truncated binary block used to produce an empty mesh and no complaint --
 * the header would say 2195 nodes and the reader would hand back nothing --
 * and silence is the worse failure of the two. */
bool Document::parse_nodes_binary(LineReader &reader, int64_t count, int format) {
  if (count < 0) return false;
  const size_t value_size = (format == kFormatBinaryDouble) ? 8 : 4;
  const size_t record = 4 + 3 * value_size;
  const char *p = nullptr;
  if (!reader.take_bytes(static_cast<size_t>(count) * record, &p)) return false;

  raw_node_ids_.reserve(raw_node_ids_.size() + static_cast<size_t>(count));
  raw_node_xyz_.reserve(raw_node_xyz_.size() + static_cast<size_t>(count) * 3);

  for (int64_t i = 0; i < count; ++i, p += record) {
    const int64_t nid = read_i32_le(p);
    double xyz[3];
    for (int k = 0; k < 3; ++k) {
      const char *v = p + 4 + static_cast<ptrdiff_t>(k) * static_cast<ptrdiff_t>(value_size);
      xyz[k] = (value_size == 8) ? read_f64_le(v) : static_cast<double>(read_f32_le(v));
    }
    auto it = raw_node_slot_.find(nid);
    if (it == raw_node_slot_.end()) {
      raw_node_slot_.emplace(nid, raw_node_ids_.size());
      raw_node_ids_.push_back(nid);
      raw_node_xyz_.insert(raw_node_xyz_.end(), xyz, xyz + 3);
    } else {
      /* A repeated id overwrites, matching the ASCII path exactly. */
      std::copy(xyz, xyz + 3, raw_node_xyz_.begin() + static_cast<ptrdiff_t>(it->second * 3));
    }
  }
  reader.skip_newline();
  return true;
}

/* Elements, binary. One record is element number, type, group and material as
 * four 4-byte integers, then the connectivity as one 4-byte integer per node.
 *
 * The connectivity is written in the same permuted order as the ASCII branch
 * -- `frd.c` emits the identical index sequence in both -- so `permute` does
 * the same job here and the quadratic orderings need no separate treatment. */
bool Document::parse_elements_binary(LineReader &reader, int64_t count, int format) {
  (void)format; /* element records hold no floats; only 2 is ever written */
  if (count < 0) return false;

  std::vector<int64_t> node_ids;
  for (int64_t i = 0; i < count; ++i) {
    const char *head = nullptr;
    if (!reader.take_bytes(16, &head)) return false;
    const int64_t code = read_i32_le(head + 4);

    CellSpec spec{0, 0};
    if (!cell_spec_for(code, &spec)) {
      /* Unlike the ASCII path this cannot skip the record and carry on: the
       * next record's position is only known from this one's node count, and
       * an unknown type means that count is unknown too. Everything after it
       * is unreadable, so say so rather than resynchronising onto noise. */
      diagnostics_.push_back({PVFRD_DIAG_UNSUPPORTED_ELEMENT, static_cast<int32_t>(code),
                              reader.line_number(), -1, -1});
      return false;
    }

    const char *body = nullptr;
    if (!reader.take_bytes(static_cast<size_t>(spec.n_points) * 4, &body)) return false;
    node_ids.clear();
    node_ids.reserve(spec.n_points);
    for (uint32_t k = 0; k < spec.n_points; ++k) {
      node_ids.push_back(read_i32_le(body + static_cast<ptrdiff_t>(k) * 4));
    }
    raw_cells_.push_back(permute(node_ids, code, spec.n_points, options_.wedge_order));
    raw_cell_types_.push_back(spec.vtk_type);
  }
  reader.skip_newline();
  return true;
}

void Document::parse_elements(LineReader &reader) {
  uint32_t needed = 0;
  std::vector<int64_t> node_ids;
  int64_t code = 0;
  CellSpec spec{0, 0};
  bool open_element = false;
  int64_t element_line = -1;

  std::string_view line;
  while (reader.next(&line)) {
    std::string_view s = strip(line);

    /* An element left open when a non-"-2" line arrives never got its nodes.
     * The reference checks this *before* the end-of-block test, so a block
     * ending mid-element still reports the element it was building. */
    if (open_element && !starts_with(s, kElementFaces)) {
      diagnostics_.push_back({PVFRD_DIAG_TOO_FEW_POINTS, static_cast<int32_t>(code), element_line,
                              static_cast<int64_t>(needed), static_cast<int64_t>(node_ids.size())});
      open_element = false;
    }

    if (starts_with(s, kEndOfBlock)) return;

    if (starts_with(s, kNodalValues)) {
      element_line = reader.line_number();
      size_t idx = line.find(kNodalValues);
      if (idx == std::string_view::npos) continue;
      std::vector<std::string_view> parts = split(line.substr(idx + kNodalValues.size()));

      /* parts[0] is the element id, parts[1] its type. A missing or
       * unparseable type abandons the element without a diagnostic -- only a
       * type that parses but is unknown gets reported. */
      int64_t value = 0;
      if (parts.size() < 2 || !parse_int(parts[1], &value)) {
        open_element = false;
        continue;
      }
      if (!cell_spec_for(value, &spec)) {
        diagnostics_.push_back(
            {PVFRD_DIAG_UNSUPPORTED_ELEMENT, static_cast<int32_t>(value), element_line, -1, -1});
        open_element = false;
        continue;
      }
      code = value;
      needed = spec.n_points;
      node_ids.clear();
      open_element = true;

    } else if (starts_with(s, kElementFaces) && open_element) {
      size_t idx = line.find(kElementFaces);
      if (idx == std::string_view::npos) continue;
      std::string_view data = line.substr(idx + kElementFaces.size());

      /* The field width is decided once, by the first element-face line in
       * the file, and applies to every element after it. Long format writes
       * 10-wide ids, short format 5-wide, and CalculiX does not label which
       * it used -- the length of the first such line is the only signal. */
      if (!format_detected_) {
        is_long_format_ = rstrip(data).size() > 50;
        format_detected_ = true;
      }
      const size_t width = is_long_format_ ? 10 : 5;

      /* Fixed-width first: it is what splits `1234567890` into two ids,
       * which whitespace splitting cannot do. If any chunk fails to parse,
       * nothing from this line is kept and the whole line is retried as
       * whitespace-separated fields, skipping the ones that are not
       * integers. */
      if (!chunk_fixed_width(data, width, &node_ids)) {
        for (std::string_view token : split(data)) {
          int64_t value = 0;
          if (parse_int(token, &value)) node_ids.push_back(value);
        }
      }

      if (node_ids.size() < needed) continue; /* more nodes on the next line */

      if (node_ids.size() > needed) {
        /* Reported, but kept: the extra ids are dropped and the element is
         * built from the ones the cell type calls for. */
        diagnostics_.push_back({PVFRD_DIAG_TOO_MANY_POINTS, static_cast<int32_t>(code),
                                element_line, static_cast<int64_t>(needed),
                                static_cast<int64_t>(node_ids.size())});
      }

      raw_cells_.push_back(permute(node_ids, code, needed, options_.wedge_order));
      raw_cell_types_.push_back(spec.vtk_type);
      open_element = false;
      node_ids.clear();
    }
  }

  /* End of file with an element still open. The reference's loop simply ends
   * here and the element is forgotten without a diagnostic; matched, because
   * a warning this implementation raises and the incumbent does not is a
   * behavioural difference in the direction users notice. */
}

void Document::index_results(LineReader &reader, StepRef *step, int64_t declared_records,
                             int format) {
  std::string name = "Unknown";
  std::string_view line;

  while (reader.next(&line)) {
    std::string_view s = strip(line);

    if (starts_with(s, kAttributeHeader)) {
      std::vector<std::string_view> parts = split(s);
      if (parts.size() >= 2) name = std::string(parts[1]);

      if (is_binary_format(format)) {
        /* Binary blocks have to be measured here, while the header is still
         * in hand. There is no `-1` marker to find the records by and no
         * ` -3` to find their end by -- CalculiX writes the terminator only
         * in ASCII mode (`frd.c`: `if(strcmp1(output,"asc")==0)`), so the
         * payload runs straight into the next block's header line. */
        int64_t declared = 0;
        if (parts.size() < 3 || !parse_int(parts[2], &declared) || declared < 0) return;

        /* CalculiX writes exactly `declared` component definitions, and the
         * payload begins after the last of them. Some are computed by the
         * postprocessor rather than stored -- a displacement block declares
         * four and writes three, because ALL is the magnitude -- and those
         * carry a fifth field marking them as such. Counting the stored ones
         * is what gives the record its width. */
        uint32_t stored = 0;
        for (int64_t i = 0; i < declared; ++i) {
          std::string_view definition;
          if (!reader.next(&definition)) return;
          std::vector<std::string_view> fields = split(strip(definition));
          if (!starts_with(strip(definition), kComponentDefinition)) return;
          /* The `iexist` flag and the component's name are printed with no
           * separator between them -- CalculiX writes the line literally as
           * `" -5  ALL         1    2    0    0    1ALL"` -- so the field
           * splits as `1ALL` and will not parse as an integer. Reading its
           * leading digits is the whole trick, and getting it wrong is not
           * loud: it makes a displacement block four components wide instead
           * of three, and every record after the first is then read from the
           * wrong offset. */
          const bool derived = fields.size() >= 7 && leading_int(fields[6]) == 1;
          if (!derived) ++stored;
        }
        if (stored == 0) return;

        const size_t value_size = (format == kFormatBinaryDouble) ? 8 : 4;
        const size_t record = 4 + static_cast<size_t>(stored) * value_size;
        const size_t span = static_cast<size_t>(declared_records) * record;

        BlockRef block;
        block.name = name;
        block.format = format;
        block.n_components = stored;
        block.data_begin = reader.position();
        block.first_line = reader.line_number();
        const char *ignored = nullptr;
        if (!reader.take_bytes(span, &ignored)) return; /* truncated; drop the block */
        block.data_end = reader.position();

        /* The record width was computed, not read, so check where it landed.
         * A binary payload is followed immediately by another ASCII header --
         * or by the end of the file -- and every FRD header line begins with
         * spaces and then a digit or a minus. Landing anywhere else means the
         * component count was wrong, and the alternative to noticing is
         * handing back numbers decoded from the middle of other numbers. */
        if (!looks_like_header_at(buffer_, reader.position())) return;
        reader.skip_newline();
        step->blocks.push_back(std::move(block));
        return;
      }

    } else if (starts_with(s, kComponentDefinition)) {
      continue;

    } else if (starts_with(s, kNodalValues)) {
      /* The first data record ends the header. Everything from here to the
       * next "-3" is this block's values, and the block is done afterwards:
       * one array per 100C record, which is what CalculiX writes. */
      BlockRef block;
      block.name = name;
      block.data_begin = reader.line_start();
      block.first_line = reader.line_number();
      block.data_end = buffer_.size();

      std::string_view inner;
      while (reader.next(&inner)) {
        if (starts_with(strip(inner), kEndOfBlock)) {
          block.data_end = reader.line_start();
          break;
        }
      }
      step->blocks.push_back(std::move(block));
      return;

    } else if (starts_with(s, kEndOfBlock)) {
      return;
    }
  }
}

void Document::build_mesh() {
  node_ids_ = raw_node_ids_;
  std::sort(node_ids_.begin(), node_ids_.end());

  points_.resize(node_ids_.size() * 3);
  node_index_.reserve(node_ids_.size() * 2);
  for (size_t i = 0; i < node_ids_.size(); ++i) {
    node_index_.emplace(node_ids_[i], static_cast<int64_t>(i));
    size_t slot = raw_node_slot_.at(node_ids_[i]);
    std::copy(raw_node_xyz_.begin() + static_cast<ptrdiff_t>(slot * 3),
              raw_node_xyz_.begin() + static_cast<ptrdiff_t>(slot * 3 + 3),
              points_.begin() + static_cast<ptrdiff_t>(i * 3));
  }

  cell_offsets_.push_back(0);
  for (size_t c = 0; c < raw_cells_.size(); ++c) {
    const std::vector<int64_t> &ids = raw_cells_[c];
    /* An element referring to a node the file never defined is dropped
     * whole, without a diagnostic -- again matching the incumbent, which
     * catches the KeyError and moves on. */
    bool complete = true;
    for (int64_t id : ids) {
      if (node_index_.find(id) == node_index_.end()) {
        complete = false;
        break;
      }
    }
    if (!complete) continue;

    for (int64_t id : ids) connectivity_.push_back(node_index_.at(id));
    cell_offsets_.push_back(static_cast<int64_t>(connectivity_.size()));
    cell_types_.push_back(raw_cell_types_[c]);
  }

  /* The raw parse products are dead once the mesh exists, and a large file
   * holds them twice over until they are dropped. */
  raw_cells_.clear();
  raw_cells_.shrink_to_fit();
  raw_cell_types_.clear();
  raw_cell_types_.shrink_to_fit();
  raw_node_xyz_.clear();
  raw_node_xyz_.shrink_to_fit();
  raw_node_ids_.clear();
  raw_node_ids_.shrink_to_fit();
}

pvfrd_status Document::parse() {
  LineReader reader(buffer_);
  std::string_view line;

  while (reader.next(&line)) {
    std::string_view s = strip(line);
    if (starts_with(s, kNodeBlock)) {
      const BlockHeader header = parse_block_header(s);
      if (is_binary_format(header.format)) {
        if (!parse_nodes_binary(reader, header.count, header.format)) {
          set_last_error("truncated binary node block: the header declares " +
                         std::to_string(header.count) + " nodes in format " +
                         std::to_string(header.format) +
                         ", and the file does not hold that many records");
          return PVFRD_E_FORMAT;
        }
      } else {
        parse_nodes(reader);
      }
    } else if (starts_with(s, kElementBlock)) {
      const BlockHeader header = parse_block_header(s);
      if (is_binary_format(header.format)) {
        if (!parse_elements_binary(reader, header.count, header.format)) {
          set_last_error("unreadable binary element block: the header declares " +
                         std::to_string(header.count) +
                         " elements, and the records either run past the end of the file or "
                         "name an element type whose node count this reader does not know");
          return PVFRD_E_FORMAT;
        }
      } else {
        parse_elements(reader);
      }
    } else if (starts_with(s, kResultBlock)) {
      /* The step exists from the moment its header is seen, even if the
       * block turns out to hold nothing. A file's time-step list is a
       * property of its headers, not of whether every block had data. */
      double time = step_time_of(s);
      auto it = step_index_.find(time);
      if (it == step_index_.end()) {
        StepRef step;
        step.time = time;
        steps_.push_back(std::move(step));
        it = step_index_.emplace(time, steps_.size() - 1).first;
      }
      const BlockHeader result_header = parse_result_header(s);
      index_results(reader, &steps_[it->second], result_header.count, result_header.format);
    }
  }

  build_mesh();

  /* steps_ is in first-seen order; the ABI promises ascending time. */
  std::sort(steps_.begin(), steps_.end(),
            [](const StepRef &a, const StepRef &b) { return a.time < b.time; });
  materialised_.resize(steps_.size());
  return PVFRD_OK;
}

namespace {

/* One node's values inside a result block, in the order the file first
 * mentioned that node. Insertion order is load-bearing: the component count
 * of the whole array is taken from whichever node appeared first. */
struct BlockValues {
  std::vector<int64_t> ids;
  std::vector<std::vector<double>> values;
  std::unordered_map<int64_t, size_t> slot;

  void set(int64_t id, std::vector<double> v) {
    auto it = slot.find(id);
    if (it == slot.end()) {
      slot.emplace(id, ids.size());
      ids.push_back(id);
      values.push_back(std::move(v));
    } else {
      values[it->second] = std::move(v);
    }
  }
};

/* A binary result block: `count` records of a 4-byte node id followed by
 * `n_components` values, each 4 bytes under format 2 and 8 under format 3.
 *
 * The record count is not stored, because it does not need to be: the block's
 * byte range was fixed when it was indexed, and dividing it by the record
 * size is exact for a well-formed block. A trailing partial record means the
 * file is truncated, and the loop stops rather than reading past the end. */
void parse_binary_block_values(std::string_view buffer, const BlockRef &block, BlockValues *out) {
  const size_t value_size = (block.format == kFormatBinaryDouble) ? 8 : 4;
  const size_t record = 4 + static_cast<size_t>(block.n_components) * value_size;
  if (record == 4 || block.data_end <= block.data_begin) return;

  const char *p = buffer.data() + block.data_begin;
  const size_t span = block.data_end - block.data_begin;

  for (size_t offset = 0; offset + record <= span; offset += record) {
    const char *rec = p + offset;
    const int64_t nid = read_i32_le(rec);
    std::vector<double> values;
    values.reserve(block.n_components);
    for (uint32_t k = 0; k < block.n_components; ++k) {
      const char *v = rec + 4 + static_cast<ptrdiff_t>(k) * static_cast<ptrdiff_t>(value_size);
      values.push_back(value_size == 8 ? read_f64_le(v) : static_cast<double>(read_f32_le(v)));
    }
    out->set(nid, std::move(values));
  }
}

void parse_block_values(std::string_view buffer, const BlockRef &block, BlockValues *out) {
  if (is_binary_format(block.format)) {
    parse_binary_block_values(buffer, block, out);
    return;
  }
  LineReader reader(buffer);
  reader.seek(block.data_begin, block.first_line - 1);

  std::string_view line;
  while (reader.next(&line)) {
    if (reader.line_start() >= block.data_end) break;

    std::string_view s = strip(line);
    if (!starts_with(s, kNodalValues)) continue;
    size_t idx = line.find(kNodalValues);
    if (idx == std::string_view::npos) continue;

    std::string data = fix_scientific(line.substr(idx + kNodalValues.size()));
    std::vector<std::string_view> parts = split(data);
    if (parts.size() < 2) continue;

    int64_t nid = 0;
    if (!parse_int(parts[0], &nid)) continue;

    /* Every value has to parse before any of them is kept: the reference
     * builds the list in one comprehension, so a bad field at the end
     * discards the whole record rather than storing a short row. */
    std::vector<double> values;
    values.reserve(parts.size() - 1);
    bool ok = true;
    for (size_t i = 1; i < parts.size(); ++i) {
      double v = 0.0;
      if (!parse_double(parts[i], &v)) {
        ok = false;
        break;
      }
      values.push_back(v);
    }
    if (!ok || values.empty()) continue;
    out->set(nid, std::move(values));
  }
}

}  // namespace

void Document::materialise(uint64_t step_index, MaterialisedStep *out) const {
  const StepRef &step = steps_[step_index];
  const size_t n_points = node_ids_.size();

  /* Blocks are collapsed by name first, because two blocks sharing a name in
   * one step are one array: the later values win, at the position the first
   * one claimed. */
  std::vector<std::string> order;
  std::unordered_map<std::string, size_t> position;
  std::vector<BlockValues> collapsed;

  for (const BlockRef &block : step.blocks) {
    BlockValues values;
    parse_block_values(buffer_, block, &values);
    if (values.ids.empty()) continue; /* an empty block contributes no array */

    auto it = position.find(block.name);
    if (it == position.end()) {
      position.emplace(block.name, collapsed.size());
      order.push_back(block.name);
      collapsed.push_back(std::move(values));
    } else {
      collapsed[it->second] = std::move(values);
    }
  }

  for (size_t b = 0; b < order.size(); ++b) {
    const BlockValues &values = collapsed[b];
    /* Guarded at the point of use, not by the `ids.empty()` skip above. The
     * two are parallel today -- BlockValues::set appends to both -- so this
     * branch is not reachable, and that is exactly the problem with relying
     * on it: the safety of an index into `values` would be a property of a
     * different member, maintained by a different function. Indexing [0] on
     * an empty vector is undefined, and undefined behaviour is not a thing to
     * hold in place with an invariant stated somewhere else. */
    const size_t n_components = values.values.empty() ? 0 : values.values[0].size();

    Array array;
    array.name = order[b];
    array.n_components = static_cast<uint32_t>(n_components);
    array.kind = PVFRD_ARRAY_RAW;
    array.data.assign(n_points * n_components, 0.0);

    for (size_t i = 0; i < values.ids.size(); ++i) {
      auto it = node_index_.find(values.ids[i]);
      if (it == node_index_.end()) continue; /* a value for an unknown node */
      const size_t row = static_cast<size_t>(it->second);
      const std::vector<double> &v = values.values[i];

      if (n_components == 1) {
        /* A single-component array takes the first value and ignores the
         * rest, however many the record carried. */
        array.data[row] = v[0];
      } else if (v.size() == n_components) {
        std::copy(v.begin(), v.end(),
                  array.data.begin() + static_cast<ptrdiff_t>(row * n_components));
      } else if (v.size() == 1) {
        /* NumPy broadcasts a one-element assignment across the row. Copied
         * because a file can trigger it and the two readers must agree on
         * what comes out. */
        std::fill_n(array.data.begin() + static_cast<ptrdiff_t>(row * n_components), n_components,
                    v[0]);
      } else {
        out->status = PVFRD_E_RAGGED;
        out->error = "array '" + array.name + "': node " + std::to_string(values.ids[i]) + " has " +
                     std::to_string(v.size()) + " components, expected " +
                     std::to_string(n_components);
        return;
      }
    }

    const std::string upper = ascii_upper(array.name);
    const bool is_stress = n_components == 6 && contains(upper, "STRESS");
    const bool is_strain = !is_stress && n_components == 6 && contains(upper, "STRAIN");

    const std::string base = array.name;
    const std::vector<double> tensor =
        (is_stress || is_strain) ? array.data : std::vector<double>();
    out->arrays.push_back(std::move(array));

    if (!is_stress && !is_strain) continue;

    Array mises;
    mises.name = base + "_Mises";
    mises.n_components = 1;
    mises.kind = PVFRD_ARRAY_DERIVED;
    mises.data.resize(n_points);

    Array signed_mises;
    signed_mises.name = base + "_sgMises";
    signed_mises.n_components = 1;
    signed_mises.kind = PVFRD_ARRAY_DERIVED;
    signed_mises.data.resize(n_points);

    if (is_stress) {
      von_mises_stress(tensor.data(), n_points, mises.data.data(), signed_mises.data.data());
    } else {
      von_mises_strain(tensor.data(), n_points, mises.data.data(), signed_mises.data.data());
    }

    Array ps3, ps2, ps1;
    ps3.name = base + "_PS3";
    ps2.name = base + "_PS2";
    ps1.name = base + "_PS1";
    for (Array *a : {&ps3, &ps2, &ps1}) {
      a->n_components = 1;
      a->kind = PVFRD_ARRAY_DERIVED;
      a->data.resize(n_points);
    }
    for (size_t i = 0; i < n_points; ++i) {
      principal_values(tensor.data() + i * 6, &ps3.data[i], &ps2.data[i], &ps1.data[i]);
    }

    /* Order fixed by the reference: magnitude, signed magnitude, then the
     * principals from smallest to largest. */
    out->arrays.push_back(std::move(mises));
    out->arrays.push_back(std::move(signed_mises));
    out->arrays.push_back(std::move(ps3));
    out->arrays.push_back(std::move(ps2));
    out->arrays.push_back(std::move(ps1));
  }

  for (size_t i = 0; i < out->arrays.size(); ++i) {
    out->by_name.emplace(out->arrays[i].name, static_cast<uint64_t>(i));
  }
}

const MaterialisedStep *Document::step_arrays(uint64_t step) const {
  if (step >= steps_.size()) return nullptr;

  std::lock_guard<std::mutex> guard(materialise_mutex_);
  std::unique_ptr<MaterialisedStep> &slot = materialised_[step];
  if (!slot) {
    slot = std::make_unique<MaterialisedStep>();
    steps_parsed_.fetch_add(1);
    materialise(step, slot.get());
    slot->done = true;
  }
  if (slot->status != PVFRD_OK) {
    set_last_error(slot->error);
    return nullptr;
  }
  return slot.get();
}

}  // namespace pvfrd

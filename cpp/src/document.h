/* A whole FRD document, kept as written.
 *
 * parse.cpp answers "what mesh and what values" and is deliberately lossy:
 * it sorts nodes by id, permutes connectivity into VTK order, and drops
 * element numbers, group and material ids, and every header line. This is
 * the other view -- the file's own order, numbering, and unrecognised lines
 * verbatim -- so emitting it again is a copy rather than a re-derivation.
 * The corpus holds two generations of CalculiX writer padding their headers
 * to different widths; no formatter reproduces both, and not reformatting
 * them does.
 *
 * DocumentEchoTest holds the two parsers to the same mesh over every fixture.
 */

#ifndef PVFRD_DOCUMENT_H
#define PVFRD_DOCUMENT_H

#include <cstdint>
#include <string>
#include <vector>

#include "pvfrd/pvfrd.h"

namespace pvfrd {

struct RawNode {
  int64_t id = 0;
  double xyz[3] = {0.0, 0.0, 0.0};
};

/* CalculiX's own type code and connectivity order, not VTK's: converting
 * would make output depend on a permutation table being its own inverse. */
struct RawElement {
  int64_t id = 0;
  int64_t type = 0;
  int64_t group = 0;
  int64_t material = 0;
  std::vector<int64_t> nodes;
};

struct RawRecord {
  int64_t id = 0;
  std::vector<double> values;
};

/* One thing inside a block, in file order: a parsed record, or a line this
 * parser did not understand. The ordering is the point -- keeping unparsed
 * lines in a separate list hoists a stray line from the middle of a block to
 * the top of it, and the file still reads back the same. */
struct RawItem {
  int64_t record = -1;  /* index into the block's records, or -1 */
  std::string verbatim; /* the line, when there is no record */
};

struct RawBlock {
  enum Kind { kVerbatim, kNodes, kElements, kResults };

  Kind kind = kVerbatim;

  /* Reproduced exactly, each still carrying its terminator: the block header,
   * then `-4` and `-5` metadata. A verbatim block holds everything here. */
  std::vector<std::string> lines;

  std::vector<RawItem> items;
  std::string terminator; /* the ` -3` line, verbatim, or empty */

  int format = 1;
  int64_t declared = -1;     /* the count the header states */
  uint32_t n_components = 0; /* stored components, result blocks */

  /* Measured from the first record, since the header does not say and the
   * file that needs them states no format code at all (cgx's example).  Zero
   * means "not measured, fall back to the format code".
   *
   *   id_width          5 columns in the short format, 10 in the long one.
   *   fortran_exponent  an `E12.5` edit descriptor puts the mantissa in
   *                     [0.1, 1) with five significant digits: `0.86430E-07`
   *                     where C's `%12.5E` writes `8.64300E-08`. */
  size_t id_width = 0;
  bool fortran_exponent = false;

  /* The width of an element's *face* id fields, which the file never states.
   * They are written fixed-width with no separator, so five-wide ids run
   * together -- `1000110002100031` is four ids -- and the only signal is how
   * long the first such line is. The reader decides once per document; this
   * must reach the same decision or a file reads one way and writes another. */
  size_t face_width = 0;

  std::vector<RawNode> nodes;
  std::vector<RawElement> elements;
  std::vector<RawRecord> records;
};

struct RawDocument {
  std::vector<RawBlock> blocks;

  /* Taken from the file, so rewriting a CRLF document does not convert it. */
  std::string newline = "\n";
};

/* Parse for re-emission. Unrecognised content becomes a verbatim block, but a
 * binary payload whose width cannot be measured is an error: a wrong width
 * decodes every record after the first from the wrong offset. */
pvfrd_status parse_raw(const std::string &buffer, RawDocument *out, std::string *error);

/* Emit `document`. `format` is a format code, or -1 to keep each block in the
 * encoding it arrived in. */
std::string emit_raw(const RawDocument &document, int format);

/* Whether `document` can be restated in `format` without losing anything, and
 * if not, why. A header stating no format code cannot be re-stamped, so its
 * records would change encoding while the header declared the old one; and a
 * block holding an unparsed line cannot become binary, which has no room for
 * text. Checked before emitting: a plausible wrong file is worse than a
 * refusal. */
bool can_emit_as(const RawDocument &document, int format, std::string *why);

}  // namespace pvfrd

#endif

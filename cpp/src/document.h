/* A whole FRD document, kept as written.
 *
 * The reader in parse.cpp answers "what mesh and what values", which is what
 * a consumer wants and is deliberately lossy: it sorts nodes by id, permutes
 * element connectivity into VTK order, and discards element numbers, group
 * and material ids, and every header line in the file. None of that can be
 * put back, so it cannot be the input to a writer that has to reproduce what
 * CalculiX wrote.
 *
 * This is the other view. It keeps the file's own order, its own numbering,
 * and every line it does not need to understand -- verbatim, terminator
 * included -- so that emitting it again is a byte-for-byte operation rather
 * than a re-derivation. That matters more than it sounds: the corpus holds at
 * least two generations of CalculiX writer, one padding its header lines to
 * 132 columns and one to 74, and no amount of care in a formatter reproduces
 * both. Not reformatting them does.
 *
 * The two parsers are kept honest against each other by
 * DocumentEchoTest, which requires the mesh this one describes to be the mesh
 * the other one builds, over every fixture in the repository.
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

/* An element as the file numbers it: CalculiX's own type code, not a VTK
 * one, and the connectivity in CalculiX's own order. Converting either would
 * make the writer's output depend on a permutation table being its own
 * inverse, which is a bug waiting for a type whose table is asymmetric. */
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

/* One thing inside a block, in the order the file had it: either a record
 * this parser understood, or a line it did not.
 *
 * The ordering is the point. An earlier version kept unparsed lines in the
 * block's header list and emitted that list first, which moved a stray line
 * from the middle of a node block to the top of it -- the file still read
 * back the same, and its bytes had been rearranged. A writer may normalise
 * how a record is spelled; it may not move somebody's content. */
struct RawItem {
  int64_t record = -1;  /* index into the block's records, or -1 */
  std::string verbatim; /* the line, when there is no record */
};

struct RawBlock {
  enum Kind { kVerbatim, kNodes, kElements, kResults };

  Kind kind = kVerbatim;

  /* Lines reproduced exactly, each still carrying its own terminator: the
   * block header, then any `-4` and `-5` metadata for a result block. A
   * verbatim block holds its whole content here and nothing else. */
  std::vector<std::string> lines;

  /* The block's body, in file order. */
  std::vector<RawItem> items;
  std::string terminator; /* the ` -3` line, verbatim, or empty */

  int format = 1;
  int64_t declared = -1;     /* the count the header states */
  uint32_t n_components = 0; /* stored components, result blocks */

  /* Two things the header does not say, measured from the first record
   * instead. CalculiX's own output uses neither, but cgx ships an example
   * file that uses both, and a writer that imposed one dialect on a file
   * written in the other would be reformatting somebody's data on the way
   * through. Zero means "not measured, fall back to the format code".
   *
   *   id_width          the id field is 5 columns wide in the short format
   *                     and 10 in the long one -- and the file that needs
   *                     this states no format code at all.
   *   fortran_exponent  values written by a Fortran `E12.5` edit descriptor
   *                     put the mantissa in [0.1, 1) and carry five
   *                     significant digits: `0.86430E-07` where C's `%12.5E`
   *                     writes `8.64300E-08`. Same number, one digit fewer.
   */
  size_t id_width = 0;
  bool fortran_exponent = false;

  /* The width of an element's *face* id fields, which is not the same thing
   * as id_width and is not stated anywhere in the file. CalculiX writes them
   * fixed-width with no separator, so five-wide ids run together --
   * `1000110002100031...` is eight ids, not one number -- and the only signal
   * for which width was used is how long the first such line is. The reader
   * decides it that way once per document; so does this, and it has to be the
   * same decision or a file would read one way and write another. */
  size_t face_width = 0;

  std::vector<RawNode> nodes;
  std::vector<RawElement> elements;
  std::vector<RawRecord> records;
};

struct RawDocument {
  std::vector<RawBlock> blocks;

  /* What to end a generated line with. Taken from the file rather than
   * assumed, so rewriting a CRLF document does not silently convert it. */
  std::string newline = "\n";
};

/* Parse for re-emission. Never fails on content it does not recognise -- that
 * content becomes a verbatim block -- but does fail on a binary payload it
 * cannot measure, for the same reason the reader does: a wrong width means
 * every record after the first is decoded from the wrong offset. */
pvfrd_status parse_raw(const std::string &buffer, RawDocument *out, std::string *error);

/* Emit `document`. `format` is one of the four format codes, or -1 to keep
 * each block in the encoding it arrived in. */
std::string emit_raw(const RawDocument &document, int format);

/* Whether `document` can be restated in `format` without losing or corrupting
 * anything, and if not, why.
 *
 * Converting is not always possible, and the failures are quiet ones. A block
 * header that states no format code cannot be re-stamped, so its records
 * would change encoding while the header went on declaring the old one --
 * a file that says ASCII and holds binary, which no reader can be expected to
 * survive. And a block holding a line this parser did not understand cannot
 * become binary, because a binary payload has no room for a line of text.
 *
 * Checked before emitting rather than repaired during it: producing a
 * plausible file that is wrong is worse than refusing. */
bool can_emit_as(const RawDocument &document, int format, std::string *why);

}  // namespace pvfrd

#endif

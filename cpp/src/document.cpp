/* Parsing a document for re-emission, and emitting it again.
 *
 * The field layout here was derived from CalculiX's own output rather than
 * from its source, which is a licensing decision as much as a technical one:
 * this project is MIT and CalculiX is GPL, so the layout is taken as a fact
 * about the files -- measured across 833 of them -- and not transcribed from
 * anyone's expression of it. Every width below was checked against the corpus
 * before it was written, and is checked again on every run by the byte-match
 * gate, which is the only reason to believe any of it.
 *
 * Measured, uniform across the whole corpus:
 *
 *   node record     " -1" %10d then three %12.5E                  49 columns
 *   element record  " -1" %10d then %5d thrice                    28 columns
 *   element faces   " -2" then %10d, at most ten to a line       103 columns
 *   result record   " -1" %10d then %12.5E, at most six to a line 85 columns
 *   continuation    " -2" ten blanks then the same six fields      85 columns
 *
 * Header lines are never reformatted, only copied. The corpus contains two
 * generations of CalculiX writer -- one padding headers to 74 columns and one
 * to 132 -- and a formatter that reproduced both would be inventing a rule
 * that does not exist.
 */

#include "document.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "frd.h"
#include "text.h"

namespace pvfrd {
namespace {

constexpr std::string_view kNodeBlock = "2C";
constexpr std::string_view kElementBlock = "3C";
constexpr std::string_view kResultBlock = "100";
constexpr std::string_view kNodalValues = "-1";
constexpr std::string_view kElementFaces = "-2";
constexpr std::string_view kEndOfBlock = "-3";
constexpr std::string_view kAttributeHeader = "-4";
constexpr std::string_view kComponentDefinition = "-5";

constexpr int kFormatShortAscii = 0;
constexpr int kFormatLongAscii = 1;
constexpr int kFormatBinaryFloat = 2;
constexpr int kFormatBinaryDouble = 3;

/* How many ids an element's face line carries before wrapping. Ten in the
 * long format, fifteen in the short one -- both measured, in the CalculiX
 * regression corpus and in cgx's own example file respectively. It is not a
 * column limit: ten ten-wide ids is 103 columns and fifteen five-wide ids is
 * 78. */
size_t faces_per_line(size_t width) {
  return width == 5 ? 15 : 10;
}

constexpr size_t kValuesPerLine = 6;

bool is_binary(int format) {
  return format == kFormatBinaryFloat || format == kFormatBinaryDouble;
}

/* Width of an id field. Short format has never been seen in the corpus, so
 * the byte-match gate says nothing about it; it is implemented from the
 * format's documented meaning and labelled as unvalidated in doc/writing.md
 * rather than left to fail silently. */
size_t id_width(int format) {
  return format == kFormatShortAscii ? 5 : 10;
}

int64_t field_int(std::string_view stripped, size_t index) {
  std::vector<std::string_view> parts = split(stripped);
  if (parts.size() <= index) return -1;
  int64_t value = 0;
  return parse_int(parts[index], &value) ? value : -1;
}

int format_of(std::string_view stripped) {
  std::vector<std::string_view> parts = split(stripped);
  if (parts.size() < 3) return kFormatLongAscii;
  int64_t value = 0;
  if (!parse_int(parts.back(), &value)) return kFormatLongAscii;
  if (value < kFormatShortAscii || value > kFormatBinaryDouble) return kFormatLongAscii;
  return static_cast<int>(value);
}

/* The leading digits of a token. `-5` lines print the `iexist` flag hard
 * against the component name -- `1ALL` -- so the flag has to be read off the
 * front rather than parsed as a field. */
int64_t leading_int(std::string_view token) {
  size_t i = 0;
  while (i < token.size() && is_digit(token[i])) ++i;
  if (i == 0) return -1;
  int64_t value = 0;
  return parse_int(token.substr(0, i), &value) ? value : -1;
}

/* Where the id field ends, measured rather than assumed.
 *
 * The id is the first token after the record marker and is right-justified in
 * its field, so the end of that token is the end of the field. Taken on the
 * scientific-fix output because `1-1.00000E+00` is otherwise a single token --
 * the fix only ever inserts *after* the id, so the offset is the same in both
 * strings. Returns 0 if there is no token, and the caller keeps its default. */
size_t measure_id_width(std::string_view line, size_t after_marker) {
  size_t i = after_marker;
  while (i < line.size() && is_python_space(line[i])) ++i;
  const size_t begin = i;
  while (i < line.size() && !is_python_space(line[i]) && line[i] != '-') ++i;
  if (i == begin) return 0;
  return i - after_marker;
}

/* Whether a value token is written in the Fortran style, in which the
 * mantissa sits in [0.1, 1). Zero is spelled `0.00000E+00` either way and so
 * decides nothing; only a non-zero value does. */
bool looks_fortran(std::string_view token) {
  size_t i = 0;
  if (i < token.size() && (token[i] == '+' || token[i] == '-')) ++i;
  if (i + 1 >= token.size() || token[i] != '0' || token[i + 1] != '.') return false;
  for (size_t k = i + 2; k < token.size(); ++k) {
    if (token[k] == 'E' || token[k] == 'e' || token[k] == 'D' || token[k] == 'd') break;
    if (token[k] != '0') return true; /* 0.86430E-07 -> Fortran */
  }
  return false; /* 0.00000E+00 -> says nothing */
}

int32_t read_i32_le(const char *p) {
  uint32_t bits = 0;
  std::memcpy(&bits, p, sizeof(bits));
  return static_cast<int32_t>(bits);
}

double read_f32_le(const char *p) {
  float value = 0.0F;
  std::memcpy(&value, p, sizeof(value));
  return static_cast<double>(value);
}

double read_f64_le(const char *p) {
  double value = 0.0;
  std::memcpy(&value, p, sizeof(value));
  return value;
}

void write_i32_le(std::string *out, int32_t value) {
  uint32_t bits = static_cast<uint32_t>(value);
  char bytes[4];
  std::memcpy(bytes, &bits, sizeof(bytes));
  out->append(bytes, sizeof(bytes));
}

void write_f32_le(std::string *out, double value) {
  float narrowed = static_cast<float>(value);
  char bytes[4];
  std::memcpy(bytes, &narrowed, sizeof(bytes));
  out->append(bytes, sizeof(bytes));
}

void write_f64_le(std::string *out, double value) {
  char bytes[8];
  std::memcpy(bytes, &value, sizeof(bytes));
  out->append(bytes, sizeof(bytes));
}

/* `%12.5E`, except for the one value printf spells differently.
 *
 * CalculiX writes NaN coordinates for the nodes of a network deck, and prints
 * them as `NaN`; glibc's printf prints `NAN` and Windows prints `nan`. Left
 * to the C library the same document would be written three ways depending on
 * where it was written, so the spelling is fixed here. */
/* CalculiX writes its ASCII values through single precision, and it shows.
 *
 * Converting one of its binary files to ASCII and comparing against the ASCII
 * file it wrote from the same run, 800 of 825 record lines matched and 25
 * differed -- always by one in the last digit, always at a rounding tie.
 * 6.464285098e-04 prints as 6.46429E-04 from the double and 6.46428E-04 from
 * the float, and the float is what CalculiX writes. Rounding the double is
 * not more accurate here, it is a different number from the one the format
 * carries.
 *
 * Safe for re-emitting an ASCII file too: the format holds six significant
 * digits and a float round-trips six exactly, so a value read from ASCII and
 * narrowed comes back as itself. The guard is for values a float cannot hold
 * at all -- none exist in 2,976,281 scanned across the corpus, but losing one
 * silently to an infinity or a zero would be a poor way to find the first. */
double as_written(double value) {
  const float narrowed = static_cast<float>(value);
  if (!std::isfinite(narrowed)) return value;
  if (narrowed == 0.0F && value != 0.0) return value;
  return static_cast<double>(narrowed);
}

void append_value(std::string *out, double value_in, bool fortran) {
  if (std::isnan(value_in)) {
    out->append("         NaN");
    return;
  }
  const double value = as_written(value_in);
  char buffer[32];
  if (!fortran) {
    std::snprintf(buffer, sizeof(buffer), "%12.5E", value);
    out->append(buffer);
    return;
  }

  /* Fortran's `E12.5`: the same value with the mantissa shifted one place
   * right and the exponent raised to match, and one significant digit fewer.
   * Printed through C and then shifted, rather than reimplemented, so the
   * rounding is the library's and not a hand-rolled approximation of it --
   * `%.4E` already rounds to the five significant digits this format keeps. */
  std::snprintf(buffer, sizeof(buffer), "%.4E", value);
  std::string text = buffer;
  const size_t e = text.find('E');
  if (e == std::string::npos || e < 2) {
    out->append(buffer);
    return;
  }
  int exponent = std::atoi(text.c_str() + e + 1);
  const bool negative = text[0] == '-';
  std::string digits = text.substr(negative ? 1 : 0, e - (negative ? 1 : 0));
  digits.erase(digits.find('.'), 1); /* "8.6430" -> "86430" */

  char shifted[32];
  /* Zero has no mantissa to shift and is written `0.00000E+00` in both
   * dialects; incrementing its exponent would invent `0.00000E+01`. */
  if (value != 0.0) ++exponent;
  std::snprintf(shifted, sizeof(shifted), "%s0.%sE%+03d", negative ? "-" : "", digits.c_str(),
                exponent);
  std::string field = shifted;
  if (field.size() < 12) field.insert(0, 12 - field.size(), ' ');
  out->append(field);
}

void append_int(std::string *out, int64_t value, size_t width) {
  char buffer[32];
  std::snprintf(buffer, sizeof(buffer), "%*lld", static_cast<int>(width),
                static_cast<long long>(value));
  out->append(buffer);
}

/* The block header with its format code replaced.
 *
 * The code is the last field of the line, and only that field moves: the rest
 * of the header is other people's spacing and is left alone. Rewritten in
 * place so the line keeps its width -- a header padded to 132 columns stays
 * padded to 132 columns. */
bool header_carries_a_format_code(const std::string &header) {
  std::string_view body = header;
  size_t end = body.size();
  while (end > 0 && (body[end - 1] == '\n' || body[end - 1] == '\r')) --end;
  size_t tail = end;
  while (tail > 0 && is_python_space(body[tail - 1])) --tail;
  size_t begin = tail;
  while (begin > 0 && !is_python_space(body[begin - 1])) --begin;
  int64_t value = 0;
  if (begin >= tail || !parse_int(body.substr(begin, tail - begin), &value)) return false;
  return value >= kFormatShortAscii && value <= kFormatBinaryDouble;
}

std::string with_format(const std::string &header, int format) {
  std::string_view body = header;
  size_t end = body.size();
  while (end > 0 && (body[end - 1] == '\n' || body[end - 1] == '\r')) --end;
  size_t tail = end;
  while (tail > 0 && is_python_space(body[tail - 1])) --tail;
  size_t begin = tail;
  while (begin > 0 && !is_python_space(body[begin - 1])) --begin;

  int64_t existing = 0;
  if (begin >= tail || !parse_int(body.substr(begin, tail - begin), &existing)) return header;
  if (existing < kFormatShortAscii || existing > kFormatBinaryDouble) return header;

  std::string out = header;
  const std::string replacement = std::to_string(format);
  /* Same number of digits either way -- 0 to 3 -- so the field is a
   * substitution and not a reflow. */
  if (replacement.size() != tail - begin) return header;
  out.replace(begin, tail - begin, replacement);
  return out;
}

}  // namespace

pvfrd_status parse_raw(const std::string &buffer, RawDocument *out, std::string *error) {
  LineReader reader(buffer);
  std::string_view line;

  bool newline_known = false;
  size_t face_width = 10;
  bool face_width_known = false;
  std::vector<std::string> pending;

  auto verbatim_of = [&buffer, &reader]() {
    return buffer.substr(reader.line_start(), reader.position() - reader.line_start());
  };

  auto flush_pending = [&]() {
    if (pending.empty()) return;
    RawBlock block;
    block.kind = RawBlock::kVerbatim;
    block.lines = std::move(pending);
    pending.clear();
    out->blocks.push_back(std::move(block));
  };

  while (reader.next(&line)) {
    const std::string verbatim = verbatim_of();
    if (!newline_known && verbatim.size() > line.size()) {
      out->newline = verbatim.substr(line.size());
      newline_known = true;
    }

    const std::string_view stripped = strip(line);

    if (starts_with(stripped, kNodeBlock) || starts_with(stripped, kElementBlock)) {
      const bool nodes = starts_with(stripped, kNodeBlock);
      flush_pending();

      RawBlock block;
      block.kind = nodes ? RawBlock::kNodes : RawBlock::kElements;
      block.lines.push_back(verbatim);
      block.format = format_of(stripped);
      block.declared = field_int(stripped, 1);

      if (is_binary(block.format)) {
        if (block.declared < 0) {
          *error = "binary block header states no record count";
          return PVFRD_E_FORMAT;
        }
        if (nodes) {
          const size_t width = (block.format == kFormatBinaryDouble) ? 8 : 4;
          const char *payload = nullptr;
          if (!reader.take_bytes(static_cast<size_t>(block.declared) * (4 + 3 * width), &payload)) {
            *error = "truncated binary node block";
            return PVFRD_E_FORMAT;
          }
          for (int64_t i = 0; i < block.declared; ++i) {
            const char *record = payload + static_cast<size_t>(i) * (4 + 3 * width);
            RawNode node;
            node.id = read_i32_le(record);
            for (int k = 0; k < 3; ++k) {
              const char *at = record + 4 + static_cast<size_t>(k) * width;
              node.xyz[k] = (width == 8) ? read_f64_le(at) : read_f32_le(at);
            }
            block.items.push_back({static_cast<int64_t>(block.nodes.size()), std::string()});
            block.nodes.push_back(node);
          }
        } else {
          for (int64_t i = 0; i < block.declared; ++i) {
            const char *head = nullptr;
            if (!reader.take_bytes(16, &head)) {
              *error = "truncated binary element block";
              return PVFRD_E_FORMAT;
            }
            RawElement element;
            element.id = read_i32_le(head);
            element.type = read_i32_le(head + 4);
            element.group = read_i32_le(head + 8);
            element.material = read_i32_le(head + 12);
            uint32_t n_points = 0;
            if (!element_point_count(element.type, &n_points)) {
              *error = "binary element block names element type " + std::to_string(element.type) +
                       ", whose node count is unknown, so the records after it cannot be located";
              return PVFRD_E_FORMAT;
            }
            const char *body = nullptr;
            if (!reader.take_bytes(static_cast<size_t>(n_points) * 4, &body)) {
              *error = "truncated binary element block";
              return PVFRD_E_FORMAT;
            }
            for (uint32_t k = 0; k < n_points; ++k) {
              element.nodes.push_back(read_i32_le(body + static_cast<size_t>(k) * 4));
            }
            block.items.push_back({static_cast<int64_t>(block.elements.size()), std::string()});
            block.elements.push_back(std::move(element));
          }
        }
        reader.skip_newline();
        out->blocks.push_back(std::move(block));
        continue;
      }

      /* ASCII: records until the terminator. */
      while (reader.next(&line)) {
        const std::string record_text = verbatim_of();
        const std::string_view record = strip(line);
        if (starts_with(record, kEndOfBlock)) {
          block.terminator = record_text;
          break;
        }
        if (nodes) {
          if (!starts_with(record, kNodalValues)) {
            block.items.push_back({-1, record_text});
            continue;
          }
          const size_t marker = line.find(kNodalValues);
          const std::string data = fix_scientific(line.substr(marker + kNodalValues.size()));
          const std::vector<std::string_view> parts = split(data);
          RawNode node;
          if (parts.size() < 4 || !parse_int(parts[0], &node.id) ||
              !parse_double(parts[1], &node.xyz[0]) || !parse_double(parts[2], &node.xyz[1]) ||
              !parse_double(parts[3], &node.xyz[2])) {
            block.items.push_back({-1, record_text});
            continue;
          }
          if (block.nodes.empty()) {
            block.id_width = measure_id_width(line, marker + kNodalValues.size());
            for (size_t i = 1; i < 4 && !block.fortran_exponent; ++i) {
              block.fortran_exponent = looks_fortran(parts[i]);
            }
          }
          block.items.push_back({static_cast<int64_t>(block.nodes.size()), std::string()});
          block.nodes.push_back(node);
        } else if (starts_with(record, kNodalValues)) {
          const std::vector<std::string_view> parts = split(record.substr(kNodalValues.size()));
          if (block.elements.empty()) {
            const size_t marker = line.find(kNodalValues);
            block.id_width = measure_id_width(line, marker + kNodalValues.size());
          }
          RawElement element;
          if (parts.size() < 4 || !parse_int(parts[0], &element.id) ||
              !parse_int(parts[1], &element.type) || !parse_int(parts[2], &element.group) ||
              !parse_int(parts[3], &element.material)) {
            block.items.push_back({-1, record_text});
            continue;
          }
          block.items.push_back({static_cast<int64_t>(block.elements.size()), std::string()});
          block.elements.push_back(std::move(element));
        } else if (starts_with(record, kElementFaces) && !block.elements.empty()) {
          const size_t at = line.find(kElementFaces);
          const std::string_view data = line.substr(at + kElementFaces.size());

          /* Decided once for the document by the first face line, exactly as
           * the reader decides it. Anything else and a file could be read one
           * way and written the other. */
          if (!face_width_known) {
            face_width = rstrip(data).size() > 50 ? 10 : 5;
            face_width_known = true;
          }

          /* Fixed-width first, because whitespace splitting cannot separate
           * ids that were written with no gap between them -- and the glued
           * form is not hypothetical, it is what a five-wide field holding a
           * five-digit id produces. Read as one token it overflows and is
           * dropped, and the element loses its connectivity in silence. */
          std::vector<int64_t> ids;
          if (!chunk_fixed_width(data, face_width, &ids)) {
            ids.clear();
            for (std::string_view field : split(data)) {
              int64_t id = 0;
              if (parse_int(field, &id)) ids.push_back(id);
            }
          }
          for (int64_t id : ids) block.elements.back().nodes.push_back(id);

          /* The width to *write* is measured, not inherited from the rule
           * above. That rule is a parsing heuristic -- it asks whether the
           * line is longer than fifty columns -- and a two-node element's
           * face line is twenty columns wide whichever width it used. The
           * ids are right-justified and the last one ends the line, so the
           * columns each id occupies is the line's length divided by how many
           * there are. Taken from the block's first face line, and checked
           * against 1,111 files that already had an answer. */
          if (block.face_width == 0 && !ids.empty()) {
            const size_t span = rstrip(data).size();
            block.face_width = (span % ids.size() == 0) ? span / ids.size() : face_width;
          }
        } else {
          block.items.push_back({-1, record_text});
        }
      }
      out->blocks.push_back(std::move(block));
      continue;
    }

    if (starts_with(stripped, kResultBlock)) {
      flush_pending();
      RawBlock block;
      block.kind = RawBlock::kResults;
      block.lines.push_back(verbatim);
      block.format = format_of(stripped);
      block.declared = field_int(stripped, 3);

      /* The `-4` line and its `-5` component definitions, copied. The stored
       * component count comes from them: a definition carrying a trailing
       * `1` is computed by the postprocessor rather than written, and
       * counting it makes every record too wide. */
      size_t mark = reader.position();
      int64_t mark_line = reader.line_number();
      while (reader.next(&line)) {
        const std::string_view meta = strip(line);
        if (!starts_with(meta, kAttributeHeader) && !starts_with(meta, kComponentDefinition)) {
          reader.seek(mark, mark_line);
          break;
        }
        block.lines.push_back(verbatim_of());
        if (starts_with(meta, kComponentDefinition)) {
          const std::vector<std::string_view> fields = split(meta);
          const bool derived = fields.size() >= 7 && leading_int(fields[6]) == 1;
          if (!derived) ++block.n_components;
        }
        mark = reader.position();
        mark_line = reader.line_number();
      }

      if (is_binary(block.format)) {
        if (block.declared < 0 || block.n_components == 0) {
          *error = "binary result block states no record count or no stored components";
          return PVFRD_E_FORMAT;
        }
        const size_t width = (block.format == kFormatBinaryDouble) ? 8 : 4;
        const size_t record_size = 4 + static_cast<size_t>(block.n_components) * width;
        const char *payload = nullptr;
        if (!reader.take_bytes(static_cast<size_t>(block.declared) * record_size, &payload)) {
          *error = "truncated binary result block";
          return PVFRD_E_FORMAT;
        }
        for (int64_t i = 0; i < block.declared; ++i) {
          const char *at = payload + static_cast<size_t>(i) * record_size;
          RawRecord entry;
          entry.id = read_i32_le(at);
          for (uint32_t k = 0; k < block.n_components; ++k) {
            const char *value = at + 4 + static_cast<size_t>(k) * width;
            entry.values.push_back((width == 8) ? read_f64_le(value) : read_f32_le(value));
          }
          block.items.push_back({static_cast<int64_t>(block.records.size()), std::string()});
          block.records.push_back(std::move(entry));
        }
        reader.skip_newline();
        out->blocks.push_back(std::move(block));
        continue;
      }

      while (reader.next(&line)) {
        std::string record_text = verbatim_of();
        std::string_view record = strip(line);
        if (starts_with(record, kEndOfBlock)) {
          block.terminator = record_text;
          break;
        }
        if (!starts_with(record, kNodalValues)) {
          block.items.push_back({-1, record_text});
          continue;
        }

        /* A record is its ` -1` line together with the ` -2` continuations
         * that follow it -- one node's values, wrapped at six to a line --
         * and it is read as a unit because it has to be re-emitted as one.
         *
         * If any token in the unit refuses to parse, every line of it is kept
         * verbatim instead. Dropping the bad token and re-emitting the rest
         * looks harmless and is not: comprehensive.frd has a record reading
         * `bad_f 3.0 4.0 5.0 6.0` in a six-component block, and re-emitting
         * the four numbers changes how ragged that block is. The reader then
         * refuses the rewritten file with a different message than the
         * original, which is a writer editing a malformed file on its way
         * through. */
        std::vector<std::string> unit_lines{record_text};
        size_t marker = line.find(kNodalValues);
        std::string data = fix_scientific(line.substr(marker + kNodalValues.size()));
        std::vector<std::string_view> parts = split(data);

        RawRecord entry;
        bool clean = !parts.empty() && parse_int(parts[0], &entry.id);
        const size_t width_here = measure_id_width(line, marker + kNodalValues.size());
        std::vector<std::string> tokens;
        for (size_t i = 1; i < parts.size(); ++i) tokens.emplace_back(parts[i]);

        size_t mark_at = reader.position();
        int64_t mark_no = reader.line_number();
        while (clean && reader.next(&line)) {
          const std::string_view next_line = strip(line);
          if (!starts_with(next_line, kElementFaces)) {
            reader.seek(mark_at, mark_no);
            break;
          }
          unit_lines.push_back(verbatim_of());
          const size_t at = line.find(kElementFaces);
          const std::string more = fix_scientific(line.substr(at + kElementFaces.size()));
          for (std::string_view field : split(more)) tokens.emplace_back(field);
          mark_at = reader.position();
          mark_no = reader.line_number();
        }

        for (const std::string &token : tokens) {
          double value = 0.0;
          if (!parse_double(token, &value)) {
            clean = false;
            break;
          }
          entry.values.push_back(value);
        }

        if (!clean) {
          for (std::string &text : unit_lines) block.items.push_back({-1, std::move(text)});
          continue;
        }

        if (block.records.empty()) {
          block.id_width = width_here;
          for (const std::string &token : tokens) {
            if (looks_fortran(token)) {
              block.fortran_exponent = true;
              break;
            }
          }
        }
        block.items.push_back({static_cast<int64_t>(block.records.size()), std::string()});
        block.records.push_back(std::move(entry));
      }
      out->blocks.push_back(std::move(block));
      continue;
    }

    pending.push_back(verbatim);
  }

  flush_pending();
  return PVFRD_OK;
}

bool can_emit_as(const RawDocument &document, int format, std::string *why) {
  if (format < 0) return true; /* keeping every block as it was always works */

  for (const RawBlock &block : document.blocks) {
    if (block.kind == RawBlock::kVerbatim || block.format == format) continue;

    if (block.lines.empty() || !header_carries_a_format_code(block.lines.front())) {
      *why =
          "a block header states no format code, so it cannot be restamped, and converting "
          "its records would leave the header declaring the encoding they no longer use";
      return false;
    }
    if (is_binary(format)) {
      for (const RawItem &item : block.items) {
        if (item.record < 0) {
          *why =
              "a block holds a line this reader could not parse as a record, and a binary "
              "block has no way to carry it";
          return false;
        }
      }
    }
  }
  return true;
}

std::string emit_raw(const RawDocument &document, int format) {
  std::string out;

  for (const RawBlock &block : document.blocks) {
    const int target = (format < 0) ? block.format : format;

    if (block.kind == RawBlock::kVerbatim) {
      for (const std::string &text : block.lines) out += text;
      continue;
    }

    for (size_t i = 0; i < block.lines.size(); ++i) {
      out += (i == 0) ? with_format(block.lines[i], target) : block.lines[i];
    }

    /* The dialect the block arrived in, where it was measured. Converting to
     * a different format is a decision to restate the records, so it drops
     * back to that format's own conventions. */
    const bool keeping = (format < 0) || (format == block.format);
    const size_t width = (keeping && block.id_width != 0) ? block.id_width : id_width(target);
    const bool fortran = keeping && block.fortran_exponent;
    const bool binary = is_binary(target);
    const size_t value_width = (target == kFormatBinaryDouble) ? 8 : 4;

    if (block.kind == RawBlock::kNodes) {
      for (const RawItem &item : block.items) {
        if (item.record < 0) {
          out += item.verbatim;
          continue;
        }
        const RawNode &node = block.nodes[static_cast<size_t>(item.record)];
        if (binary) {
          write_i32_le(&out, static_cast<int32_t>(node.id));
          for (double coordinate : node.xyz) {
            if (value_width == 8) {
              write_f64_le(&out, coordinate);
            } else {
              write_f32_le(&out, coordinate);
            }
          }
          continue;
        }
        out += " -1";
        append_int(&out, node.id, width);
        for (double coordinate : node.xyz) append_value(&out, coordinate, fortran);
        out += document.newline;
      }
    } else if (block.kind == RawBlock::kElements) {
      for (const RawItem &item : block.items) {
        if (item.record < 0) {
          out += item.verbatim;
          continue;
        }
        const RawElement &element = block.elements[static_cast<size_t>(item.record)];
        if (binary) {
          write_i32_le(&out, static_cast<int32_t>(element.id));
          write_i32_le(&out, static_cast<int32_t>(element.type));
          write_i32_le(&out, static_cast<int32_t>(element.group));
          write_i32_le(&out, static_cast<int32_t>(element.material));
          for (int64_t node : element.nodes) write_i32_le(&out, static_cast<int32_t>(node));
          continue;
        }
        out += " -1";
        append_int(&out, element.id, width);
        append_int(&out, element.type, 5);
        append_int(&out, element.group, 5);
        append_int(&out, element.material, 5);
        out += document.newline;
        const size_t face = (keeping && block.face_width != 0) ? block.face_width : width;
        const size_t per_line = faces_per_line(face);
        for (size_t i = 0; i < element.nodes.size(); i += per_line) {
          out += " -2";
          const size_t stop = std::min(i + per_line, element.nodes.size());
          for (size_t k = i; k < stop; ++k) append_int(&out, element.nodes[k], face);
          out += document.newline;
        }
      }
    } else {
      for (const RawItem &item : block.items) {
        if (item.record < 0) {
          out += item.verbatim;
          continue;
        }
        const RawRecord &record = block.records[static_cast<size_t>(item.record)];
        if (binary) {
          write_i32_le(&out, static_cast<int32_t>(record.id));
          for (double value : record.values) {
            if (value_width == 8) {
              write_f64_le(&out, value);
            } else {
              write_f32_le(&out, value);
            }
          }
          continue;
        }
        for (size_t i = 0; i < record.values.size() || i == 0; i += kValuesPerLine) {
          if (i == 0) {
            out += " -1";
            append_int(&out, record.id, width);
          } else {
            out += " -2";
            out.append(width, ' ');
          }
          const size_t stop = std::min(i + kValuesPerLine, record.values.size());
          for (size_t k = i; k < stop; ++k) append_value(&out, record.values[k], fortran);
          out += document.newline;
        }
      }
    }

    if (binary) continue;
    if (!block.terminator.empty()) {
      out += block.terminator;
    } else if (is_binary(block.format)) {
      /* Converting a binary block to ASCII has to invent the terminator,
       * because binary blocks do not carry one -- CalculiX writes ` -3` only
       * in ASCII mode. Leaving it out produces a file that looks right and
       * that CalculiX refuses with "there are either no nodes or no elements
       * in the master frd-file": its reader ends a block on the terminator,
       * so without one the whole rest of the file is still the node block.
       *
       * A same-format rewrite could never have found this. That gate compares
       * a file with itself, and a binary block that had no terminator still
       * has none afterwards. It took feeding the converted file back to
       * CalculiX to see it. A block whose terminator is missing because the
       * *file* was truncated keeps it missing, so the identity is unharmed.
       */
      out += " -3" + document.newline;
    }
  }

  return out;
}

}  // namespace pvfrd

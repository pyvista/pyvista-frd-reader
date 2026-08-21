/* Text primitives that mirror the reference reader's Python semantics.
 *
 * Every function here exists because the reference implementation reached for
 * a Python built-in whose behaviour is not the obvious C++ one. They are in a
 * header, separate from the parser, so the gtest suite can exercise each one
 * against the Python behaviour it is copying rather than only through a
 * finished parse.
 */

#ifndef PVFRD_TEXT_H
#define PVFRD_TEXT_H

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

#include "fast_float/fast_float.h"

namespace pvfrd {

/* Python has two ASCII whitespace sets, and a reader that copies its
 * behaviour needs both of them.
 *
 *   str.strip() and str.split()  0x09-0x0D, 0x1C-0x1F, 0x20
 *   int() and float()            0x09-0x0D,            0x20
 *
 * They differ by exactly the four C0 information separators, 0x1C to 0x1F.
 * `int('\x1c42')` raises ValueError while `'a\x1cb'.split()` gives two
 * fields, which reads like an inconsistency and is simply the rule.
 *
 * The two are kept apart because that is what Python does, not because a
 * file has been found that tells them apart. It is worth being precise about
 * that. After a whitespace split a token cannot contain a separator -- it was
 * the separator -- so the only route to the distinction is the fixed-width
 * path, where a field is sliced by position. A separator there is either
 * interior to the digits, which both sets reject, or leading or trailing, in
 * which case the reference's chunking fails, falls back to split(), and
 * arrives at the same number the wide set would have read directly.
 *
 * Measured, not assumed: widening strip_numeric to the split() set leaves
 * every test in this repository green and every differential case in
 * test_bytes_and_str.py in agreement. So this is correctness by construction
 * against Python's documented rule, and TextTest pins it at the level where
 * it is observable -- parse_int refusing "\x1c42" exactly as int() does --
 * rather than at a file level where nothing yet distinguishes it. If the
 * fixed-width fallback ever changes, this is where it will start to matter.
 *
 * Non-ASCII whitespace is a different question and deliberately not answered
 * here; see doc/divergences.md, which records why it has no answer. */
inline bool is_c_space(char c) {
  return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\v' || c == '\f';
}

/* What str.strip() and str.split() treat as whitespace, restricted to ASCII. */
inline bool is_python_space(char c) {
  return is_c_space(c) || (c >= '\x1c' && c <= '\x1f');
}

inline std::string_view strip(std::string_view s) {
  size_t b = 0;
  size_t e = s.size();
  while (b < e && is_python_space(s[b])) ++b;
  while (e > b && is_python_space(s[e - 1])) --e;
  return s.substr(b, e - b);
}

inline std::string_view rstrip(std::string_view s) {
  size_t e = s.size();
  while (e > 0 && is_python_space(s[e - 1])) --e;
  return s.substr(0, e);
}

inline bool starts_with(std::string_view s, std::string_view prefix) {
  return s.size() >= prefix.size() && s.compare(0, prefix.size(), prefix) == 0;
}

/* Python's str.split() with no argument: split on runs of whitespace, with
 * leading and trailing runs producing no empty fields. Not the same as
 * splitting on a single space, which is what a naive C++ tokeniser does. */
inline std::vector<std::string_view> split(std::string_view s) {
  std::vector<std::string_view> out;
  size_t i = 0;
  while (i < s.size()) {
    while (i < s.size() && is_python_space(s[i])) ++i;
    if (i >= s.size()) break;
    size_t start = i;
    while (i < s.size() && !is_python_space(s[i])) ++i;
    out.push_back(s.substr(start, i - start));
  }
  return out;
}

/* The reference reader's `_SCIENTIFIC_RE.sub(' -', line)`, whose pattern is
 * `(?<![EeDd])-`: every minus sign not immediately preceded by an exponent
 * letter gets a space in front of it.
 *
 * This is what lets `1-1.00000E+00` split into two fields. It runs on node
 * and result lines only -- element lines are fixed-width and would be
 * corrupted by it -- and the parser keeps that split faithfully. */
inline std::string fix_scientific(std::string_view s) {
  std::string out;
  out.reserve(s.size() + 8);
  for (size_t i = 0; i < s.size(); ++i) {
    char c = s[i];
    if (c == '-') {
      char prev = (i == 0) ? '\0' : s[i - 1];
      bool exponent = (prev == 'E' || prev == 'e' || prev == 'D' || prev == 'd');
      if (!exponent) out.push_back(' ');
    }
    out.push_back(c);
  }
  return out;
}

/* Python's int(str) restricted to what an FRD file can hold.
 *
 * Accepts surrounding ASCII whitespace, an optional sign, and ASCII digits.
 * Two deliberate narrowings from Python, both recorded in
 * doc/divergences.md: digit-group underscores ("1_000") and non-ASCII digits
 * are rejected here, and a value too large for int64 is rejected rather than
 * promoted to arbitrary precision. All three make the reference reader accept
 * a record this one drops. */
/* The strip int() and float() perform before parsing: the C set, without the
 * information separators. Separate from strip() on purpose -- see above. */
inline std::string_view strip_numeric(std::string_view s) {
  size_t b = 0;
  size_t e = s.size();
  while (b < e && is_c_space(s[b])) ++b;
  while (e > b && is_c_space(s[e - 1])) --e;
  return s.substr(b, e - b);
}

inline bool is_digit(char c) {
  return c >= '0' && c <= '9';
}

/* Python allows an underscore inside a numeric literal, and the rule is the
 * same for int() and float(): it must have a digit immediately on both sides.
 * `1_000` and `.5_0` and `1e1_0` parse; `_1`, `1_`, `1__0`, `1._5`, `1.0e_1`
 * do not.
 *
 * Another ASCII-only divergence, which is the interesting part. It sits in
 * doc/divergences.md under a heading about int() accepting things outside
 * ASCII, and this half of it needs no non-ASCII byte at all -- so a file
 * entirely within the format's character set would read in PyVista and be
 * dropped here. Same shape as the information separators above. */
inline bool underscores_are_placed_as_python_allows(std::string_view t) {
  for (size_t i = 0; i < t.size(); ++i) {
    if (t[i] != '_') continue;
    if (i == 0 || i + 1 >= t.size()) return false;
    if (!is_digit(t[i - 1]) || !is_digit(t[i + 1])) return false;
  }
  return true;
}

inline bool parse_int(std::string_view s, int64_t *out) {
  std::string_view t = strip_numeric(s);
  if (t.empty()) return false;
  size_t i = 0;
  bool negative = false;
  if (t[i] == '+' || t[i] == '-') {
    negative = (t[i] == '-');
    ++i;
  }
  if (i >= t.size()) return false;
  uint64_t magnitude = 0;
  bool previous_was_digit = false;
  for (; i < t.size(); ++i) {
    char c = t[i];
    if (c == '_') {
      /* Between digits only. `previous_was_digit` covers the left side; the
       * right side has to be looked at directly. */
      if (!previous_was_digit || i + 1 >= t.size() || !is_digit(t[i + 1])) return false;
      previous_was_digit = false;
      continue;
    }
    if (c < '0' || c > '9') return false;
    previous_was_digit = true;
    uint64_t digit = static_cast<uint64_t>(c - '0');
    /* Guard before multiplying, not after: signed overflow is undefined and
     * the sanitiser lane would be right to stop on it. */
    if (magnitude > (UINT64_C(9223372036854775807) - digit) / 10) return false;
    magnitude = magnitude * 10 + digit;
  }
  *out = negative ? -static_cast<int64_t>(magnitude) : static_cast<int64_t>(magnitude);
  return true;
}

/* Python's float(str), for a token with no surrounding whitespace.
 *
 * fast_float is correctly rounded and locale-independent, which is what makes
 * bit-identical coordinates achievable rather than merely close: strtod under
 * a comma-decimal locale would silently truncate every value in the file at
 * the decimal point, and a hand-rolled parser would round differently in the
 * last place.
 *
 * The whole token must be consumed. Python's float() also accepts underscores
 * and a "D" exponent is *not* accepted by either -- CalculiX writes "E". */
inline bool parse_double(std::string_view s, double *out) {
  std::string_view t = strip_numeric(s);
  if (t.empty()) return false;
  const char *first = t.data();
  const char *last = t.data() + t.size();
  /* fast_float declines a leading '+' unless told otherwise; Python accepts
   * it. Step over it so the two agree. */
  if (*first == '+') {
    ++first;
    if (first == last) return false;
  }
  double value = 0.0;
  auto result = fast_float::from_chars(first, last, value);
  if (result.ec == std::errc() && result.ptr == last) {
    *out = value;
    return true;
  }

  /* Only now consider underscores. Doing it this way costs the common case
   * nothing: a value without one has already been parsed and returned above,
   * and this branch is reached only by input fast_float has already refused.
   * A pre-scan for '_' would put a pass over every field in the file on the
   * hot path in exchange for a case no CalculiX file contains. */
  const std::string_view remaining(first, static_cast<size_t>(last - first));
  if (remaining.find('_') == std::string_view::npos) return false;
  if (!underscores_are_placed_as_python_allows(remaining)) return false;

  std::string without;
  without.reserve(remaining.size());
  for (char c : remaining) {
    if (c != '_') without.push_back(c);
  }
  const char *begin = without.data();
  const char *end = begin + without.size();
  auto retry = fast_float::from_chars(begin, end, value);
  if (retry.ec != std::errc() || retry.ptr != end) return false;
  *out = value;
  return true;
}

/* The reference reader's fixed-width element-node split:
 *
 *     chunks = [data[i:i + width] for i in range(0, len(data), width)]
 *     new_nodes = [int(c) for c in chunks if c.strip()]
 *
 * A single bad chunk aborts the whole comprehension, so nothing is appended
 * and the caller falls back to whitespace splitting. That all-or-nothing
 * behaviour is the reason this returns a bool instead of appending as it
 * goes: appending the good chunks before hitting a bad one would leave the
 * element holding nodes the reference reader never gave it. */
inline bool chunk_fixed_width(std::string_view data, size_t width, std::vector<int64_t> *out) {
  std::vector<int64_t> parsed;
  for (size_t i = 0; i < data.size(); i += width) {
    std::string_view chunk = data.substr(i, width);
    if (strip(chunk).empty()) continue;
    int64_t value = 0;
    if (!parse_int(chunk, &value)) return false;
    parsed.push_back(value);
  }
  out->insert(out->end(), parsed.begin(), parsed.end());
  return true;
}

/* Iterate lines the way Python's text mode does.
 *
 * Universal newlines: "\n", "\r\n" and a lone "\r" all end a line, and the
 * terminator is not part of what this yields. The reference reader only ever
 * strips or searches within a line, so dropping the terminator here is
 * equivalent -- with one exception the parser handles itself, noted where the
 * element format width is decided.
 *
 * A lone "\r" mattering is not hypothetical: FRD files written on classic Mac
 * tooling and files mangled by a text-mode file transfer both arrive that
 * way, and treating "\r" as ordinary content would put the whole file on one
 * line and find nothing in it. */
class LineReader {
 public:
  explicit LineReader(std::string_view buffer) : buffer_(buffer) {}

  /* Returns false at end of input. `line` excludes the terminator. */
  bool next(std::string_view *line) {
    if (pos_ >= buffer_.size()) return false;
    line_start_ = pos_;
    size_t i = pos_;
    while (i < buffer_.size() && buffer_[i] != '\n' && buffer_[i] != '\r') ++i;
    *line = buffer_.substr(pos_, i - pos_);
    if (i < buffer_.size()) {
      if (buffer_[i] == '\r' && i + 1 < buffer_.size() && buffer_[i + 1] == '\n') {
        i += 2;
      } else {
        ++i;
      }
    }
    pos_ = i;
    ++line_number_;
    return true;
  }

  /* 1-based number of the line most recently returned. Counted from the
   * start of the file across every block, because that is what the reference
   * reader reports in its warnings and the tests read those numbers. */
  int64_t line_number() const { return line_number_; }

  /* Byte offset of the start of the line most recently returned. */
  size_t line_start() const { return line_start_; }

  /* Byte offset of the next line to be returned. */
  size_t position() const { return pos_; }

  void seek(size_t position, int64_t line_number) {
    pos_ = position;
    line_number_ = line_number;
  }

 private:
  std::string_view buffer_;
  size_t pos_ = 0;
  size_t line_start_ = 0;
  int64_t line_number_ = 0;
};

}  // namespace pvfrd

#endif  // PVFRD_TEXT_H

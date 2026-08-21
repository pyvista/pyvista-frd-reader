/* Text primitives mirroring the reference reader's Python semantics. Each one
 * exists because the reference reached for a built-in whose behaviour is not
 * the obvious C++ one; they are in a header so TextTest can exercise them
 * directly rather than only through a finished parse. */

#ifndef PVFRD_TEXT_H
#define PVFRD_TEXT_H

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

#include "fast_float/fast_float.h"

namespace pvfrd {

/* Python has two ASCII whitespace sets and a reader copying it needs both:
 * str.strip()/str.split() take 0x09-0x0D, 0x1C-0x1F, 0x20, while int() and
 * float() take 0x09-0x0D, 0x20. They differ by the four C0 information
 * separators, so `int('\x1c42')` raises while `'a\x1cb'.split()` gives two
 * fields.
 *
 * No file yet distinguishes them: widening strip_numeric to the split() set
 * leaves every test green. TextTest pins the difference where it is
 * observable, at parse_int, rather than at a file level. It becomes reachable
 * only if the fixed-width fallback changes. Non-ASCII whitespace is a
 * separate question doc/divergences.md records as unanswered. */
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

/* Python's str.split() with no argument: runs of whitespace, no empty
 * leading or trailing fields. */
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

/* The reference's `_SCIENTIFIC_RE.sub(' -', line)`, pattern `(?<![EeDd])-`:
 * what lets `1-1.00000E+00` split into two fields. Node and result lines
 * only; element lines are fixed-width and would be corrupted by it. */
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

/* The strip int() and float() perform: the C set, without the information
 * separators. Separate from strip() on purpose -- see above. */
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

/* Python's rule for both int() and float(): an underscore needs a digit
 * immediately on both sides. `1_000`, `.5_0`, `1e1_0` parse; `_1`, `1_`,
 * `1__0`, `1._5`, `1.0e_1` do not. */
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
      /* Between digits only; the right side has to be looked at directly. */
      if (!previous_was_digit || i + 1 >= t.size() || !is_digit(t[i + 1])) return false;
      previous_was_digit = false;
      continue;
    }
    if (c < '0' || c > '9') return false;
    previous_was_digit = true;
    uint64_t digit = static_cast<uint64_t>(c - '0');
    /* Before multiplying: signed overflow is undefined. */
    if (magnitude > (UINT64_C(9223372036854775807) - digit) / 10) return false;
    magnitude = magnitude * 10 + digit;
  }
  *out = negative ? -static_cast<int64_t>(magnitude) : static_cast<int64_t>(magnitude);
  return true;
}

/* Python's float(str). fast_float is correctly rounded and locale
 * independent, which is what makes bit-identical coordinates achievable:
 * strtod under a comma-decimal locale truncates every value at the decimal
 * point. The whole token must be consumed. Neither accepts a "D" exponent. */
inline bool parse_double(std::string_view s, double *out) {
  std::string_view t = strip_numeric(s);
  if (t.empty()) return false;
  const char *first = t.data();
  const char *last = t.data() + t.size();
  /* fast_float declines a leading '+'; Python accepts it. */
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

  /* Underscores only now: reached only by input fast_float refused, so the
   * common case pays nothing. A pre-scan would cost a pass over every field
   * in the file for a case no CalculiX file contains. */
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

/* The reference's fixed-width element-node split:
 *
 *     chunks = [data[i:i + width] for i in range(0, len(data), width)]
 *     new_nodes = [int(c) for c in chunks if c.strip()]
 *
 * One bad chunk aborts the comprehension and the caller falls back to
 * whitespace splitting -- hence the bool, rather than appending as it goes
 * and leaving the element holding nodes the reference never gave it. */
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

/* Lines as Python's text mode gives them. Universal newlines: "\n", "\r\n"
 * and a lone "\r" all end a line, and the terminator is not yielded -- the
 * reference only strips or searches within a line, with one exception noted
 * where the element format width is decided. A lone "\r" is not
 * hypothetical: classic Mac tooling and text-mode transfers both produce it,
 * and treating it as content puts the whole file on one line. */
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

  /* 1-based, counted from the start of the file across every block, because
   * that is what the reference reports in its warnings. */
  int64_t line_number() const { return line_number_; }

  /* Byte offset of the start of the line most recently returned. */
  size_t line_start() const { return line_start_; }

  /* Byte offset of the next line to be returned. */
  size_t position() const { return pos_; }

  void seek(size_t position, int64_t line_number) {
    pos_ = position;
    line_number_ = line_number;
  }

  /* Hand back `n` raw bytes and step past them, for a binary block. FRD keeps
   * block headers in ASCII and makes only records binary, so a file is read
   * by line until a header declares a binary payload, then by byte for
   * exactly as many bytes as its record count implies.
   *
   * The count is the only thing that works: CalculiX writes no ` -3` after a
   * binary block -- the payload runs straight into the next header -- and
   * scanning for one would find whatever the floats happened to spell.
   *
   * False without moving if the buffer is short. */
  bool take_bytes(size_t n, const char **out) {
    if (n > buffer_.size() - pos_) return false;
    *out = buffer_.data() + pos_;
    pos_ += n;
    /* Not counted as lines: line numbers exist to match the reference's
     * warnings about *text* records. */
    return true;
  }

  /* CalculiX ends the ASCII header before a binary payload with a newline and
   * adds none after the records. */
  void skip_newline() {
    if (pos_ < buffer_.size() && buffer_[pos_] == '\r') ++pos_;
    if (pos_ < buffer_.size() && buffer_[pos_] == '\n') ++pos_;
  }

 private:
  std::string_view buffer_;
  size_t pos_ = 0;
  size_t line_start_ = 0;
  int64_t line_number_ = 0;
};

}  // namespace pvfrd

#endif  // PVFRD_TEXT_H

/* The text primitives, each against the Python behaviour it is copying.
 *
 * These are worth testing separately from a finished parse because a parse
 * that comes out right can still be right for the wrong reason: two
 * compensating mistakes in tokenising and field-width handling produce a
 * correct mesh on the files that happen to be in the corpus and a wrong one
 * on the next file anybody tries.
 */

#include <gtest/gtest.h>

#include <string>
#include <vector>

#include "text.h"

using namespace pvfrd;

namespace {

std::vector<std::string> split_strings(std::string_view s) {
  std::vector<std::string> out;
  for (std::string_view piece : split(s)) out.emplace_back(piece);
  return out;
}

}  // namespace

TEST(TextTest, StripMatchesPythonWhitespaceSet) {
  EXPECT_EQ(strip("  hello  "), "hello");
  EXPECT_EQ(strip("\t\n\v\f\r x \r\f\v\n\t"), "x");
  EXPECT_EQ(strip("   "), "");
  EXPECT_EQ(strip(""), "");
  /* No interior collapsing: strip touches the ends only. */
  EXPECT_EQ(strip(" a  b "), "a  b");
}

TEST(TextTest, NonAsciiWhitespace) {
  /* U+00A0 is whitespace to Python's str.strip() and not to this one. FRD is
   * an ASCII format, so the divergence is recorded rather than fixed; this
   * test exists to make it a decision rather than an accident. */
  const std::string nbsp = "\xC2\xA0";
  EXPECT_EQ(strip(nbsp + "x" + nbsp), nbsp + "x" + nbsp);
}

TEST(TextTest, TheInformationSeparatorsAreWhitespaceToStripAndSplit) {
  /* 0x1C to 0x1F are whitespace to Python's str.strip() and str.split(), and
   * they are ASCII -- so this is a divergence that could occur in a file with
   * no non-ASCII byte in it at all, which is every file this format allows.
   *
   * It was one, until measured: a STRESS row separated by 0x1C was read by
   * the reference and dropped entirely here, losing the array. The whole
   * bytes-versus-str family had been filed under "needs a non-ASCII file",
   * and four of its members needed no such thing. */
  for (char c : {'\x1c', '\x1d', '\x1e', '\x1f'}) {
    const std::string s(1, c);
    EXPECT_TRUE(is_python_space(c)) << "byte " << static_cast<int>(c);
    EXPECT_EQ(strip(s + "x" + s), "x") << "byte " << static_cast<int>(c);
    EXPECT_EQ(split_strings("1" + s + "2"), (std::vector<std::string>{"1", "2"}))
        << "byte " << static_cast<int>(c);
  }
}

TEST(TextTest, TheInformationSeparatorsAreNotWhitespaceToIntAndFloat) {
  /* The other half of the same rule, and the reason there are two predicates.
   * Python is asymmetric here: `'a\x1cb'.split()` gives two fields but
   * `int('\x1c42')` raises ValueError. A reader with one whitespace set is
   * wrong on one side of that or the other. */
  for (char c : {'\x1c', '\x1d', '\x1e', '\x1f'}) {
    const std::string s(1, c);
    EXPECT_FALSE(is_c_space(c)) << "byte " << static_cast<int>(c);
    int64_t value = 0;
    EXPECT_FALSE(parse_int(s + "42", &value))
        << "int() refuses a leading 0x" << std::hex << static_cast<int>(c);
    EXPECT_FALSE(parse_int("42" + s, &value))
        << "int() refuses a trailing 0x" << std::hex << static_cast<int>(c);
    double d = 0.0;
    EXPECT_FALSE(parse_double(s + "1.5", &d))
        << "float() refuses a leading 0x" << std::hex << static_cast<int>(c);
  }
}

TEST(TextTest, TheTwoWhitespaceSetsDifferByExactlyTheSeparators) {
  /* Pinned as a set relation rather than as two lists, so a byte added to one
   * predicate and forgotten in the other fails here rather than somewhere
   * downstream. The reference for both is Python: str.isspace() restricted to
   * ASCII on one side, int()'s accepted padding on the other. */
  for (int b = 0; b < 128; ++b) {
    const char c = static_cast<char>(b);
    const bool separator = (b >= 0x1c && b <= 0x1f);
    EXPECT_EQ(is_python_space(c), is_c_space(c) || separator) << "byte 0x" << std::hex << b;
    if (!separator) {
      EXPECT_EQ(is_python_space(c), is_c_space(c)) << "byte 0x" << std::hex << b;
    }
  }
  /* And that the C set is exactly the six characters it should be. */
  int c_spaces = 0;
  for (int b = 0; b < 128; ++b) {
    if (is_c_space(static_cast<char>(b))) ++c_spaces;
  }
  EXPECT_EQ(c_spaces, 6);
}

TEST(TextTest, UnderscoresBetweenDigitsParseAsPythonParsesThem) {
  /* Python allows an underscore inside a numeric literal when it has a digit
   * immediately on both sides, and the rule is the same for int() and
   * float(). Every expectation below was taken from running the equivalent
   * expression in Python, not from reading the grammar.
   *
   * Worth having because this is ASCII: a file with no byte above 0x7F could
   * carry `1_000` as a node id, be read by the reference, and be dropped
   * here. doc/divergences.md filed it under a heading about int() accepting
   * non-ASCII digits, which hid the half of it that needs no such thing. */
  struct Case {
    const char *text;
    bool as_int;
    int64_t integer;
    bool as_double;
    double real;
  };
  const Case cases[] = {
      {"1_000", true, 1000, true, 1000.0},
      {"+1_0", true, 10, true, 10.0},
      {"-1_0", true, -10, true, -10.0},
      {"1_000_000.5", false, 0, true, 1000000.5},
      {"1_0.5", false, 0, true, 10.5},
      {"1e1_0", false, 0, true, 1e10},
      {"1_0e1_0", false, 0, true, 1e11},
      {"1_0E+1_0", false, 0, true, 1e11},
      {".5_0", false, 0, true, 0.5},
      /* And every way of placing one that Python refuses. */
      {"_1", false, 0, false, 0.0},
      {"1_", false, 0, false, 0.0},
      {"1__0", false, 0, false, 0.0},
      {"1._5", false, 0, false, 0.0},
      {"1_.5", false, 0, false, 0.0},
      {"1.5_e3", false, 0, false, 0.0},
      {"1.0_", false, 0, false, 0.0},
      {"_1.0", false, 0, false, 0.0},
      {"1.0e_1", false, 0, false, 0.0},
      {"1.0e1_", false, 0, false, 0.0},
  };

  for (const Case &c : cases) {
    int64_t integer = 0;
    EXPECT_EQ(parse_int(c.text, &integer), c.as_int) << "parse_int(\"" << c.text << "\")";
    if (c.as_int) EXPECT_EQ(integer, c.integer) << c.text;

    double real = 0.0;
    EXPECT_EQ(parse_double(c.text, &real), c.as_double) << "parse_double(\"" << c.text << "\")";
    if (c.as_double) EXPECT_DOUBLE_EQ(real, c.real) << c.text;
  }
}

TEST(TextTest, SplitCollapsesRunsLikePythonSplit) {
  EXPECT_EQ(split_strings("  1   2\t3 \n"), (std::vector<std::string>{"1", "2", "3"}));
  EXPECT_EQ(split_strings("   "), std::vector<std::string>{});
  EXPECT_EQ(split_strings(""), std::vector<std::string>{});
  EXPECT_EQ(split_strings("single"), std::vector<std::string>{"single"});
}

TEST(TextTest, FixScientificSplitsGluedNegatives) {
  /* The case this exists for: a coordinate whose minus sign is welded to the
   * previous field. */
  EXPECT_EQ(fix_scientific("    1-1.00000E+00-2.00000E+00"), "    1 -1.00000E+00 -2.00000E+00");
  /* An exponent's own sign must survive untouched, or every value in the
   * file splits in half. */
  EXPECT_EQ(fix_scientific("1.5E-07"), "1.5E-07");
  EXPECT_EQ(fix_scientific("1.5e-07"), "1.5e-07");
  EXPECT_EQ(fix_scientific("1.5D-07"), "1.5D-07");
  EXPECT_EQ(fix_scientific("1.5d-07"), "1.5d-07");
  /* A leading minus has no preceding character, so it is spaced -- which is
   * what the Python lookbehind does at position zero. */
  EXPECT_EQ(fix_scientific("-5"), " -5");
}

TEST(TextTest, ParseIntAcceptsWhatPythonIntAccepts) {
  int64_t value = 0;
  EXPECT_TRUE(parse_int("  42 ", &value));
  EXPECT_EQ(value, 42);
  EXPECT_TRUE(parse_int("-7", &value));
  EXPECT_EQ(value, -7);
  EXPECT_TRUE(parse_int("+7", &value));
  EXPECT_EQ(value, 7);
  EXPECT_TRUE(parse_int("0009", &value));
  EXPECT_EQ(value, 9);

  EXPECT_FALSE(parse_int("", &value));
  EXPECT_FALSE(parse_int("   ", &value));
  EXPECT_FALSE(parse_int("-", &value));
  EXPECT_FALSE(parse_int("1.0", &value));
  EXPECT_FALSE(parse_int("bad_t", &value));
  EXPECT_FALSE(parse_int("1 2", &value));

  /* `1_000` used to be listed here as a documented narrowing. It is not one
   * any more -- see UnderscoresBetweenDigitsParseAsPythonParsesThem -- and it
   * should never have been grouped with the one below it. Underscores are
   * ASCII and cost a dozen lines to support; unbounded integers are neither.
   * Filing them together made the cheap half look as settled as the hard
   * half. */
  EXPECT_TRUE(parse_int("1_000", &value));
  EXPECT_EQ(value, 1000);

  /* This one is a real narrowing and stays. Python's int() has no upper
   * bound; an int64 does, and a node id past it has nowhere to go in the
   * arrays it indexes, so accepting it would buy nothing but a different
   * record to drop. */
  EXPECT_FALSE(parse_int("99999999999999999999", &value));
}

TEST(TextTest, ParseIntBoundaries) {
  int64_t value = 0;
  ASSERT_TRUE(parse_int("9223372036854775807", &value));
  EXPECT_EQ(value, INT64_MAX);
  ASSERT_TRUE(parse_int("-9223372036854775807", &value));
  EXPECT_EQ(value, -INT64_MAX);
  /* One past the top must be refused rather than wrapping. Signed overflow
   * is undefined, so a naive accumulate-then-check would be a real bug and
   * not merely a wrong answer. */
  EXPECT_FALSE(parse_int("9223372036854775808", &value));
}

TEST(TextTest, ParseDoubleIsCorrectlyRounded) {
  double value = 0.0;
  ASSERT_TRUE(parse_double("0.1", &value));
  /* The nearest double to 0.1, spelled exactly. A parser that accumulates
   * digits and multiplies by powers of ten lands one ulp away from this. */
  EXPECT_EQ(value, 0.1);
  ASSERT_TRUE(parse_double("1.00000E+01", &value));
  EXPECT_EQ(value, 10.0);
  ASSERT_TRUE(parse_double("-3.38813E-21", &value));
  EXPECT_EQ(value, -3.38813e-21);
  ASSERT_TRUE(parse_double("+2.5", &value));
  EXPECT_EQ(value, 2.5);
  ASSERT_TRUE(parse_double("2.2250738585072011e-308", &value));
  EXPECT_EQ(value, 2.2250738585072011e-308);
}

TEST(TextTest, ParseDoubleRejectsWhatPythonRejects) {
  double value = 0.0;
  EXPECT_FALSE(parse_double("", &value));
  EXPECT_FALSE(parse_double("bad_f", &value));
  EXPECT_FALSE(parse_double("1.0.0", &value));
  EXPECT_FALSE(parse_double("1.0x", &value));
  /* Fortran D-exponents: CalculiX writes E, and Python's float() would raise
   * on this too. Accepting it here would make this reader read a file
   * PyVista cannot. */
  EXPECT_FALSE(parse_double("1.0D+03", &value));
}

TEST(TextTest, ChunkFixedWidthSplitsGluedIds) {
  std::vector<int64_t> out;
  ASSERT_TRUE(chunk_fixed_width("    1    2    3", 5, &out));
  EXPECT_EQ(out, (std::vector<int64_t>{1, 2, 3}));

  /* The point of fixed-width parsing: ids with no separator at all. */
  out.clear();
  ASSERT_TRUE(chunk_fixed_width("1234567890", 5, &out));
  EXPECT_EQ(out, (std::vector<int64_t>{12345, 67890}));

  out.clear();
  ASSERT_TRUE(chunk_fixed_width("     12345     67890", 10, &out));
  EXPECT_EQ(out, (std::vector<int64_t>{12345, 67890}));
}

TEST(TextTest, AChunkWithAnInteriorSpaceIsNotAnInteger) {
  /* "    1    2" is one ten-wide chunk, and Python's int() refuses it: the
   * space is inside the field, not around it. Reading it as 12 -- which a
   * whitespace-tolerant parser would -- silently invents a node id, so the
   * refusal is the behaviour, and the caller's fallback is what recovers. */
  std::vector<int64_t> out;
  EXPECT_FALSE(chunk_fixed_width("    1    2", 10, &out));
  EXPECT_TRUE(out.empty());
}

TEST(TextTest, ChunkFixedWidthIsAllOrNothing) {
  /* A single bad chunk discards the whole line, because the reference builds
   * the list in one comprehension. Appending the good chunks first would
   * leave the element holding nodes PyVista never gave it -- and the element
   * would then look complete, so nothing downstream would notice. */
  std::vector<int64_t> out{99};
  EXPECT_FALSE(chunk_fixed_width("    1badch", 5, &out));
  EXPECT_EQ(out, std::vector<int64_t>{99});
}

TEST(TextTest, ChunkFixedWidthSkipsBlankChunks) {
  std::vector<int64_t> out;
  ASSERT_TRUE(chunk_fixed_width("    1          2     ", 5, &out));
  EXPECT_EQ(out, (std::vector<int64_t>{1, 2}));
}

TEST(LineReaderTest, UniversalNewlines) {
  const char *cases[] = {"a\nb\nc", "a\r\nb\r\nc", "a\rb\rc"};
  for (const char *text : cases) {
    LineReader reader(text);
    std::string_view line;
    std::vector<std::string> got;
    while (reader.next(&line)) got.emplace_back(line);
    EXPECT_EQ(got, (std::vector<std::string>{"a", "b", "c"})) << "input: " << text;
  }
}

TEST(LineReaderTest, MixedTerminatorsInOneBuffer) {
  LineReader reader("a\r\nb\rc\nd");
  std::string_view line;
  std::vector<std::string> got;
  while (reader.next(&line)) got.emplace_back(line);
  EXPECT_EQ(got, (std::vector<std::string>{"a", "b", "c", "d"}));
}

TEST(LineReaderTest, LineNumbersAreOneBasedAndContinuous) {
  LineReader reader("a\nb\nc\n");
  std::string_view line;
  reader.next(&line);
  EXPECT_EQ(reader.line_number(), 1);
  reader.next(&line);
  EXPECT_EQ(reader.line_number(), 2);
  reader.next(&line);
  EXPECT_EQ(reader.line_number(), 3);
  EXPECT_FALSE(reader.next(&line));
  EXPECT_EQ(reader.line_number(), 3);
}

TEST(LineReaderTest, TrailingNewlineDoesNotProduceAnEmptyLine) {
  /* Python's file iteration yields three lines for "a\nb\nc\n", not four. */
  LineReader reader("a\nb\nc\n");
  std::string_view line;
  int count = 0;
  while (reader.next(&line)) ++count;
  EXPECT_EQ(count, 3);
}

TEST(LineReaderTest, EmptyBufferYieldsNothing) {
  LineReader reader("");
  std::string_view line;
  EXPECT_FALSE(reader.next(&line));
}

TEST(LineReaderTest, SeekRestoresPositionAndNumbering) {
  LineReader reader("a\nb\nc\n");
  std::string_view line;
  reader.next(&line);
  const size_t mark = reader.line_start();
  const int64_t marked_number = reader.line_number();
  reader.next(&line);
  reader.next(&line);

  reader.seek(mark, marked_number - 1);
  ASSERT_TRUE(reader.next(&line));
  EXPECT_EQ(line, "a");
  EXPECT_EQ(reader.line_number(), marked_number);
}

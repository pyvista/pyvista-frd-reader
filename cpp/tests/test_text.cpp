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
  /* Documented narrowings from Python's int(). */
  EXPECT_FALSE(parse_int("1_000", &value));
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

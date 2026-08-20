/* Parser behaviour, stated as documents rather than as calls.
 *
 * Every case here is a small FRD file written inline, so what is being
 * claimed is legible without opening a fixture. The corpus files are for the
 * Python parity sweep, which compares against PyVista; these state what the
 * behaviour *is*, so that a change to it is a deliberate act and not
 * something noticed later as a parity failure with no explanation.
 */

#include <gtest/gtest.h>

#include <cmath>
#include <string>
#include <vector>

#include "pvfrd/pvfrd.h"

namespace {

/* An open document that closes itself. */
class Doc {
 public:
  explicit Doc(const std::string &text, int32_t wedge = PVFRD_WEDGE_ASIS) {
    pvfrd_open_options options = {wedge, 0};
    status_ = pvfrd_open_memory(text.data(), text.size(), &options, &file_);
  }
  ~Doc() { pvfrd_close(file_); }
  Doc(const Doc &) = delete;
  Doc &operator=(const Doc &) = delete;

  pvfrd_status status() const { return status_; }
  pvfrd_file *get() const { return file_; }

  std::vector<int64_t> connectivity() const {
    const int64_t *offsets = pvfrd_cell_offsets(file_);
    const int64_t *conn = pvfrd_cell_connectivity(file_);
    const uint64_t n = pvfrd_n_cells(file_);
    return std::vector<int64_t>(conn, conn + (n ? offsets[n] : 0));
  }

  std::vector<pvfrd_diagnostic> diagnostics() const {
    std::vector<pvfrd_diagnostic> out;
    for (uint64_t i = 0; i < pvfrd_n_diagnostics(file_); ++i) {
      pvfrd_diagnostic d;
      if (pvfrd_diagnostic_at(file_, i, &d) == PVFRD_OK) out.push_back(d);
    }
    return out;
  }

 private:
  pvfrd_file *file_ = nullptr;
  pvfrd_status status_ = PVFRD_OK;
};

const char *kFourNodes =
    "2C\n"
    " -1    1 0.0 0.0 0.0\n"
    " -1    2 1.0 0.0 0.0\n"
    " -1    3 0.0 1.0 0.0\n"
    " -1    4 0.0 0.0 1.0\n"
    " -3\n";

}  // namespace

TEST(ParseTest, PointsAreOrderedByNodeIdNotByAppearance) {
  /* The file lists 30, 10, 20; the mesh must be 10, 20, 30. Point order has
   * to be a property of the ids, or two files describing the same mesh with
   * the nodes written in a different order produce different arrays. */
  Doc doc(
      "2C\n"
      " -1   30 3.0 0.0 0.0\n"
      " -1   10 1.0 0.0 0.0\n"
      " -1   20 2.0 0.0 0.0\n"
      " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  ASSERT_EQ(pvfrd_n_points(doc.get()), 3u);

  const int64_t *ids = pvfrd_node_ids(doc.get());
  EXPECT_EQ(ids[0], 10);
  EXPECT_EQ(ids[1], 20);
  EXPECT_EQ(ids[2], 30);

  const double *points = pvfrd_points(doc.get());
  EXPECT_DOUBLE_EQ(points[0], 1.0);
  EXPECT_DOUBLE_EQ(points[3], 2.0);
  EXPECT_DOUBLE_EQ(points[6], 3.0);
}

TEST(ParseTest, ARepeatedNodeIdOverwritesInPlace) {
  Doc doc(
      "2C\n"
      " -1    1 1.0 0.0 0.0\n"
      " -1    2 2.0 0.0 0.0\n"
      " -1    1 9.0 0.0 0.0\n"
      " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  ASSERT_EQ(pvfrd_n_points(doc.get()), 2u);
  EXPECT_DOUBLE_EQ(pvfrd_points(doc.get())[0], 9.0);
}

TEST(ParseTest, ShortNodeRecordsAreDroppedSilently) {
  /* Fewer than four fields is not a node. FRD files carry free text that
   * happens to begin with the nodal marker, so this cannot be an error. */
  Doc doc(
      "2C\n"
      " -1    1 0.0 0.0\n"
      " -1    2 1.0 0.0 0.0\n"
      " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  EXPECT_EQ(pvfrd_n_points(doc.get()), 1u);
  EXPECT_EQ(pvfrd_n_diagnostics(doc.get()), 0u);
}

TEST(ParseTest, GluedNegativeCoordinatesAreSplit) {
  Doc doc(
      "2C\n"
      " -1    1-1.00000E+00-2.00000E+00-3.00000E+00\n"
      " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  ASSERT_EQ(pvfrd_n_points(doc.get()), 1u);
  const double *p = pvfrd_points(doc.get());
  EXPECT_DOUBLE_EQ(p[0], -1.0);
  EXPECT_DOUBLE_EQ(p[1], -2.0);
  EXPECT_DOUBLE_EQ(p[2], -3.0);
}

TEST(ParseTest, LongFormatIsDetectedFromTheFirstFaceRecord) {
  /* Eight ten-wide ids is an eighty-character record, so long format is what
   * gets detected. Read five-wide, each id would split in two and the
   * element would come out with sixteen nodes instead of eight. */
  std::string document = "2C\n";
  std::string connectivity;
  for (int i = 0; i < 8; ++i) {
    const int64_t id = 1000100 + i;
    document += " -1 " + std::to_string(id) + " " + std::to_string(i) + ".0 0.0 0.0\n";
    const std::string field = std::to_string(id);
    connectivity += std::string(10 - field.size(), ' ') + field;
  }
  ASSERT_GT(connectivity.size(), 50u) << "the fixture must actually be long format";
  document += " -3\n3C\n -1    1    1\n -2" + connectivity + "\n -3\n";

  Doc doc(document);
  ASSERT_EQ(doc.status(), PVFRD_OK);
  EXPECT_EQ(pvfrd_n_points(doc.get()), 8u);
  ASSERT_EQ(pvfrd_n_cells(doc.get()), 1u);
  EXPECT_EQ(doc.connectivity(), (std::vector<int64_t>{0, 1, 2, 3, 4, 5, 6, 7}));
  EXPECT_EQ(pvfrd_n_diagnostics(doc.get()), 0u);
}

TEST(ParseTest, AShortRecordUnderFiftyCharactersStaysShortFormat) {
  /* The threshold is the record's length, not the number of fields. Four
   * ten-wide ids is forty characters, which is short format -- and read
   * five-wide those fields still parse, because each is blank-padded. This
   * is the case that makes the threshold a real decision rather than a
   * formality. */
  std::string document = std::string(kFourNodes) + "3C\n -1    1    3\n -2";
  for (int i = 1; i <= 4; ++i) {
    const std::string field = std::to_string(i);
    document += std::string(10 - field.size(), ' ') + field;
  }
  document += "\n -3\n";

  Doc doc(document);
  ASSERT_EQ(doc.status(), PVFRD_OK);
  ASSERT_EQ(pvfrd_n_cells(doc.get()), 1u);
  EXPECT_EQ(doc.connectivity(), (std::vector<int64_t>{0, 1, 2, 3}));
}

TEST(ParseTest, FormatIsDecidedOnceForTheWholeFile) {
  /* A long first record fixes the width at ten for everything after it. The
   * second element's record is "1234512345" with no separator: at width ten
   * that is one id, at width five it is two. The element needs two nodes, so
   * the width chosen by the *first* record decides whether it is built or
   * reported as short -- which is what makes this observable at all. */
  std::string document = "2C\n";
  for (int64_t id : {1, 2, 3, 4, 12345, 1234512345}) {
    document += " -1 " + std::to_string(id) + " 0.0 0.0 0.0\n";
  }
  document += " -3\n3C\n -1    1    1\n -2";
  for (int i : {1, 2, 3, 4, 1, 2, 3, 4}) {
    const std::string field = std::to_string(i);
    document += std::string(10 - field.size(), ' ') + field;
  }
  document += "\n -1    2   11\n -21234512345\n -3\n";

  Doc doc(document);
  ASSERT_EQ(doc.status(), PVFRD_OK);
  ASSERT_EQ(pvfrd_n_cells(doc.get()), 1u) << "only the hexahedron should survive";
  EXPECT_EQ(pvfrd_cell_types(doc.get())[0], 12);

  const auto diagnostics = doc.diagnostics();
  ASSERT_EQ(diagnostics.size(), 1u);
  EXPECT_EQ(diagnostics[0].kind, PVFRD_DIAG_TOO_FEW_POINTS);
  EXPECT_EQ(diagnostics[0].element_type, PVFRD_BE2);
  EXPECT_EQ(diagnostics[0].n_actual, 1) << "read ten-wide, the record held one id";
  EXPECT_EQ(diagnostics[0].n_expected, 2);
}

TEST(ParseTest, UnparseableChunkFallsBackToWhitespaceSplitting) {
  Doc doc(std::string(kFourNodes) +
          "3C\n"
          " -1    1    7\n"
          " -2    1badch\n"
          " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  /* "    1badch" fails fixed-width parsing, so the line is retried as
   * whitespace fields: "1badch" is not an integer either, leaving the
   * element with no nodes at all.
   *
   * Noted because it matters: this case does *not* discriminate whether the
   * fallback exists -- both paths end with no nodes. It pins the outcome, and
   * WhitespaceFallbackRescuesAPaddedWideRecord below is what pins the
   * fallback itself. */
  EXPECT_EQ(pvfrd_n_cells(doc.get()), 0u);
  const auto diagnostics = doc.diagnostics();
  ASSERT_EQ(diagnostics.size(), 1u);
  EXPECT_EQ(diagnostics[0].kind, PVFRD_DIAG_TOO_FEW_POINTS);
  EXPECT_EQ(diagnostics[0].n_actual, 0);
  EXPECT_EQ(diagnostics[0].n_expected, 3);
}

TEST(ParseTest, TooManyPointsIsReportedAndTruncated) {
  Doc doc(std::string(kFourNodes) +
          "3C\n"
          " -1    1    7\n"
          " -2    1    2    3    4\n"
          " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  ASSERT_EQ(pvfrd_n_cells(doc.get()), 1u);
  /* A triangle keeps three of the four. */
  EXPECT_EQ(doc.connectivity(), (std::vector<int64_t>{0, 1, 2}));

  const auto diagnostics = doc.diagnostics();
  ASSERT_EQ(diagnostics.size(), 1u);
  EXPECT_EQ(diagnostics[0].kind, PVFRD_DIAG_TOO_MANY_POINTS);
  EXPECT_EQ(diagnostics[0].element_type, PVFRD_TR3);
  EXPECT_EQ(diagnostics[0].n_expected, 3);
  EXPECT_EQ(diagnostics[0].n_actual, 4);
}

TEST(ParseTest, UnknownElementTypeIsReportedWithItsRawCode) {
  Doc doc(std::string(kFourNodes) +
          "3C\n"
          " -1    1  999\n"
          " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  const auto diagnostics = doc.diagnostics();
  ASSERT_EQ(diagnostics.size(), 1u);
  EXPECT_EQ(diagnostics[0].kind, PVFRD_DIAG_UNSUPPORTED_ELEMENT);
  EXPECT_EQ(diagnostics[0].element_type, 999);
  /* Node counts are unknowable for a type nothing recognises, and -1 is how
   * the ABI says so. Reporting 0 would read as "an element with no nodes". */
  EXPECT_EQ(diagnostics[0].n_expected, -1);
  EXPECT_EQ(diagnostics[0].n_actual, -1);
}

TEST(ParseTest, UnparseableElementTypeIsNotReportedAtAll) {
  /* A type field that is not a number abandons the element in silence, while
   * a number nothing recognises is reported. The reference draws the line
   * there, and a warning this reader raises where PyVista raises none is a
   * difference users see. */
  Doc doc(std::string(kFourNodes) +
          "3C\n"
          " -1    1 bad_t\n"
          " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  EXPECT_EQ(pvfrd_n_diagnostics(doc.get()), 0u);
}

TEST(ParseTest, DiagnosticLineNumbersCountFromTheStartOfTheFile) {
  Doc doc(
      "1C header\n"            /* 1 */
      "2C\n"                   /* 2 */
      " -1    1 0.0 0.0 0.0\n" /* 3 */
      " -3\n"                  /* 4 */
      "3C\n"                   /* 5 */
      " -1    1  999\n"        /* 6 */
      " -3\n");                /* 7 */
  ASSERT_EQ(doc.status(), PVFRD_OK);
  const auto diagnostics = doc.diagnostics();
  ASSERT_EQ(diagnostics.size(), 1u);
  EXPECT_EQ(diagnostics[0].line, 6);
}

TEST(ParseTest, AnElementSpanningTwoFaceRecordsIsAssembled) {
  Doc doc(std::string(kFourNodes) +
          "3C\n"
          " -1    1    3\n"
          " -2    1    2\n"
          " -2    3    4\n"
          " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  ASSERT_EQ(pvfrd_n_cells(doc.get()), 1u);
  EXPECT_EQ(doc.connectivity(), (std::vector<int64_t>{0, 1, 2, 3}));
  EXPECT_EQ(pvfrd_n_diagnostics(doc.get()), 0u);
}

TEST(ParseTest, ElementsReferringToMissingNodesAreDropped) {
  Doc doc(std::string(kFourNodes) +
          "3C\n"
          " -1    1    3\n"
          " -2    1    2    3   99\n"
          " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  EXPECT_EQ(pvfrd_n_cells(doc.get()), 0u);
  /* Dropped without a diagnostic: the reference catches the lookup failure
   * and moves on, and adding a warning here would be a new behaviour. */
  EXPECT_EQ(pvfrd_n_diagnostics(doc.get()), 0u);
}

TEST(ParseTest, WedgeOrderOptionSwapsOnlyTheWedge) {
  const std::string wedge =
      "2C\n"
      " -1    1 0.0 0.0 0.0\n"
      " -1    2 1.0 0.0 0.0\n"
      " -1    3 0.0 1.0 0.0\n"
      " -1    4 0.0 0.0 1.0\n"
      " -1    5 1.0 0.0 1.0\n"
      " -1    6 0.0 1.0 1.0\n"
      " -3\n"
      "3C\n"
      " -1    1    2\n"
      " -2    1    2    3    4    5    6\n"
      " -3\n";

  Doc asis(wedge, PVFRD_WEDGE_ASIS);
  Doc swapped(wedge, PVFRD_WEDGE_SWAP);
  ASSERT_EQ(asis.status(), PVFRD_OK);
  ASSERT_EQ(swapped.status(), PVFRD_OK);

  EXPECT_EQ(asis.connectivity(), (std::vector<int64_t>{0, 1, 2, 3, 4, 5}));
  EXPECT_EQ(swapped.connectivity(), (std::vector<int64_t>{0, 2, 1, 3, 5, 4}));
}

TEST(ParseTest, StepsSharingATimeValueBecomeOneStep) {
  Doc doc(std::string(kFourNodes) +
          "100CL 1 0.5\n"
          " -4 ALPHA 1\n"
          " -1    1 1.0\n"
          " -3\n"
          "100CL 2 0.5\n"
          " -4 BETA 1\n"
          " -1    1 2.0\n"
          " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  ASSERT_EQ(pvfrd_n_steps(doc.get()), 1u);

  uint64_t n = 0;
  ASSERT_EQ(pvfrd_n_arrays(doc.get(), 0, &n), PVFRD_OK);
  EXPECT_EQ(n, 2u);
  EXPECT_EQ(pvfrd_find_array(doc.get(), 0, "ALPHA"), 0);
  EXPECT_EQ(pvfrd_find_array(doc.get(), 0, "BETA"), 1);
}

TEST(ParseTest, ARepeatedArrayNameKeepsItsFirstPositionAndItsLastValues) {
  Doc doc(std::string(kFourNodes) +
          "100CL 1 0.5\n"
          " -4 ALPHA 1\n"
          " -1    1 1.0\n"
          " -3\n"
          "100CL 2 0.5\n"
          " -4 BETA 1\n"
          " -1    1 2.0\n"
          " -3\n"
          "100CL 3 0.5\n"
          " -4 ALPHA 1\n"
          " -1    1 9.0\n"
          " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  uint64_t n = 0;
  ASSERT_EQ(pvfrd_n_arrays(doc.get(), 0, &n), PVFRD_OK);
  EXPECT_EQ(n, 2u);
  EXPECT_EQ(pvfrd_find_array(doc.get(), 0, "ALPHA"), 0);

  const double *data = nullptr;
  ASSERT_EQ(pvfrd_array_data(doc.get(), 0, 0, &data), PVFRD_OK);
  EXPECT_DOUBLE_EQ(data[0], 9.0);
}

TEST(ParseTest, StepTimesComeOutAscending) {
  Doc doc(std::string(kFourNodes) +
          "100CL 1 2.0\n -4 A 1\n -1    1 1.0\n -3\n"
          "100CL 2 0.5\n -4 A 1\n -1    1 1.0\n -3\n"
          "100CL 3 1.0\n -4 A 1\n -1    1 1.0\n -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  ASSERT_EQ(pvfrd_n_steps(doc.get()), 3u);
  double t = 0.0;
  pvfrd_step_time(doc.get(), 0, &t);
  EXPECT_DOUBLE_EQ(t, 0.5);
  pvfrd_step_time(doc.get(), 1, &t);
  EXPECT_DOUBLE_EQ(t, 1.0);
  pvfrd_step_time(doc.get(), 2, &t);
  EXPECT_DOUBLE_EQ(t, 2.0);
}

TEST(ParseTest, AnEmptyBlockStillCreatesItsStep) {
  /* The step list is a property of the headers. A block that turns out to
   * hold nothing must not remove the time value from the file. */
  Doc doc(std::string(kFourNodes) +
          "100CL 1 0.5\n"
          " -4 EMPTY 1\n"
          " -5 component info\n"
          " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  EXPECT_EQ(pvfrd_n_steps(doc.get()), 1u);
  uint64_t n = 1;
  ASSERT_EQ(pvfrd_n_arrays(doc.get(), 0, &n), PVFRD_OK);
  EXPECT_EQ(n, 0u);
}

TEST(ParseTest, AnUnparseableStepHeaderBecomesTimeZero) {
  Doc doc(std::string(kFourNodes) +
          "100CL BAD_STEP BAD_TIME\n"
          " -4 ALPHA 1\n"
          " -1    1 1.0\n"
          " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  ASSERT_EQ(pvfrd_n_steps(doc.get()), 1u);
  double t = -1.0;
  pvfrd_step_time(doc.get(), 0, &t);
  EXPECT_DOUBLE_EQ(t, 0.0);
}

TEST(ParseTest, ValuesForUnknownNodesAreIgnoredAndMissingNodesAreZero) {
  Doc doc(std::string(kFourNodes) +
          "100CL 1 0.5\n"
          " -4 ALPHA 1\n"
          " -1    1 10.0\n"
          " -1   99 99.0\n"
          " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  const double *data = nullptr;
  ASSERT_EQ(pvfrd_array_data(doc.get(), 0, 0, &data), PVFRD_OK);
  EXPECT_DOUBLE_EQ(data[0], 10.0);
  EXPECT_DOUBLE_EQ(data[1], 0.0);
  EXPECT_DOUBLE_EQ(data[2], 0.0);
  EXPECT_DOUBLE_EQ(data[3], 0.0);
}

TEST(ParseTest, ARecordWithOneBadFieldIsDiscardedWhole) {
  /* Not partially stored. The reference builds the value list in a single
   * comprehension, so a bad field at the end throws away the good ones in
   * front of it -- and the node keeps its zeros. */
  Doc doc(std::string(kFourNodes) +
          "100CL 1 0.5\n"
          " -4 ALPHA 3\n"
          " -1    1 1.0 2.0 3.0\n"
          " -1    2 4.0 bad_f 6.0\n"
          " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  const double *data = nullptr;
  ASSERT_EQ(pvfrd_array_data(doc.get(), 0, 0, &data), PVFRD_OK);
  EXPECT_DOUBLE_EQ(data[3], 0.0);
  EXPECT_DOUBLE_EQ(data[4], 0.0);
  EXPECT_DOUBLE_EQ(data[5], 0.0);
}

TEST(ParseTest, ComponentCountComesFromTheFirstRecordNotTheHeader) {
  /* CalculiX writes a component count in the -4 header that does not always
   * match what the records carry: the DISP block of a real file says 4 and
   * writes 3. The data wins, which is what the reference does. */
  Doc doc(std::string(kFourNodes) +
          "100CL 1 0.5\n"
          " -4 DISP 4\n"
          " -1    1 1.0 2.0 3.0\n"
          " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  pvfrd_array_info info;
  ASSERT_EQ(pvfrd_array_info_at(doc.get(), 0, 0, &info), PVFRD_OK);
  EXPECT_EQ(info.n_components, 3u);
}

TEST(ParseTest, ASingleComponentArrayTakesOnlyTheFirstValue) {
  Doc doc(std::string(kFourNodes) +
          "100CL 1 0.5\n"
          " -4 ALPHA 1\n"
          " -1    1 10.0\n"
          " -1    2 20.0 30.0 40.0\n"
          " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  pvfrd_array_info info;
  ASSERT_EQ(pvfrd_array_info_at(doc.get(), 0, 0, &info), PVFRD_OK);
  EXPECT_EQ(info.n_components, 1u);

  const double *data = nullptr;
  ASSERT_EQ(pvfrd_array_data(doc.get(), 0, 0, &data), PVFRD_OK);
  EXPECT_DOUBLE_EQ(data[1], 20.0);
}

TEST(ParseTest, RaggedComponentCountsAreAnError) {
  Doc doc(std::string(kFourNodes) +
          "100CL 1 0.5\n"
          " -4 STRESS 6\n"
          " -1    1 1.0 2.0 3.0 4.0 5.0 6.0\n"
          " -1    2 7.0 8.0 9.0\n"
          " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK); /* the mesh is fine; the block is not */
  uint64_t n = 0;
  EXPECT_EQ(pvfrd_n_arrays(doc.get(), 0, &n), PVFRD_E_RAGGED);
  EXPECT_NE(std::string(pvfrd_last_error(doc.get())).find("components"), std::string::npos);
}

TEST(ParseTest, DerivedArraysFollowTheirTensorInOrder) {
  Doc doc(std::string(kFourNodes) +
          "100CL 1 0.5\n"
          " -4 STRESS 6\n"
          " -1    1 10.0 20.0 30.0 0.0 0.0 0.0\n"
          " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);

  uint64_t n = 0;
  ASSERT_EQ(pvfrd_n_arrays(doc.get(), 0, &n), PVFRD_OK);
  ASSERT_EQ(n, 6u);

  std::vector<pvfrd_array_info> info(n);
  ASSERT_EQ(pvfrd_array_info_range(doc.get(), 0, 0, n, info.data()), PVFRD_OK);
  EXPECT_STREQ(info[0].name, "STRESS");
  EXPECT_STREQ(info[1].name, "STRESS_Mises");
  EXPECT_STREQ(info[2].name, "STRESS_sgMises");
  EXPECT_STREQ(info[3].name, "STRESS_PS3");
  EXPECT_STREQ(info[4].name, "STRESS_PS2");
  EXPECT_STREQ(info[5].name, "STRESS_PS1");

  EXPECT_EQ(info[0].kind, PVFRD_ARRAY_RAW);
  EXPECT_EQ(info[1].kind, PVFRD_ARRAY_DERIVED);
}

TEST(ParseTest, DerivedArraysNeedSixComponentsAndAMatchingName) {
  /* Three conditions, each checked on its own: the name has to contain
   * STRESS or STRAIN, and the array has to be six-wide. */
  const std::string prefix = std::string(kFourNodes) + "100CL 1 0.5\n";

  Doc named_but_narrow(prefix + " -4 STRESS 3\n -1    1 1.0 2.0 3.0\n -3\n");
  uint64_t n = 0;
  ASSERT_EQ(pvfrd_n_arrays(named_but_narrow.get(), 0, &n), PVFRD_OK);
  EXPECT_EQ(n, 1u) << "a three-wide STRESS must not get derived arrays";

  Doc wide_but_unnamed(prefix + " -4 FORCES 6\n -1    1 1.0 2.0 3.0 4.0 5.0 6.0\n -3\n");
  ASSERT_EQ(pvfrd_n_arrays(wide_but_unnamed.get(), 0, &n), PVFRD_OK);
  EXPECT_EQ(n, 1u) << "a six-wide array with an unrelated name must not either";

  Doc lowercase(prefix + " -4 stress 6\n -1    1 1.0 2.0 3.0 4.0 5.0 6.0\n -3\n");
  ASSERT_EQ(pvfrd_n_arrays(lowercase.get(), 0, &n), PVFRD_OK);
  EXPECT_EQ(n, 6u) << "the name test is case-insensitive";
}

TEST(ParseTest, StressWinsWhenANameContainsBoth) {
  /* The reference tests STRESS first and STRAIN in an elif, so a name
   * containing both gets the stress constant. */
  Doc doc(std::string(kFourNodes) +
          "100CL 1 0.5\n"
          " -4 STRESSSTRAIN 6\n"
          " -1    1 0.1 0.2 0.3 0.0 0.0 0.0\n"
          " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  const double *data = nullptr;
  ASSERT_EQ(pvfrd_array_data(doc.get(), 0, 1, &data), PVFRD_OK);
  /* sqrt(0.5 * 0.06) for the stress form; the strain form would be smaller. */
  EXPECT_NEAR(data[0], std::sqrt(0.5 * 0.06), 1e-15);
}

TEST(ParseTest, ADocumentWithNoNodesParsesToAnEmptyMesh) {
  /* Not an error at this layer. Whether an empty mesh is usable is the
   * caller's judgement, and PyVista's reader makes it at read() time. */
  Doc doc("1C Empty File\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  EXPECT_EQ(pvfrd_n_points(doc.get()), 0u);
  EXPECT_EQ(pvfrd_n_cells(doc.get()), 0u);
  EXPECT_EQ(pvfrd_n_steps(doc.get()), 0u);
}

TEST(ParseTest, AFileTruncatedMidBlockDoesNotCrash) {
  Doc nodes(
      "2C\n"
      " -1    1 0.0 0.0 0.0\n"
      " -1    2 1.0 0.0");
  EXPECT_EQ(nodes.status(), PVFRD_OK);
  EXPECT_EQ(pvfrd_n_points(nodes.get()), 1u);

  Doc element(std::string(kFourNodes) + "3C\n -1    1    3\n -2    1    2");
  EXPECT_EQ(element.status(), PVFRD_OK);
  EXPECT_EQ(pvfrd_n_cells(element.get()), 0u);
  /* End of file with an element still open is forgotten silently, matching
   * the reference, whose loop simply ends. */
  EXPECT_EQ(pvfrd_n_diagnostics(element.get()), 0u);

  Doc results(std::string(kFourNodes) + "100CL 1 0.5\n -4 ALPHA 1\n -1    1 1.0\n");
  EXPECT_EQ(results.status(), PVFRD_OK);
  EXPECT_EQ(pvfrd_n_steps(results.get()), 1u);
}

TEST(ParseTest, ShortFormatIdsWithNoSeparatorAreSplitAtFive) {
  /* What CalculiX writes once a mesh passes 9999 nodes: eight five-wide ids
   * run together with no space anywhere. Forty characters, so short format is
   * what must be detected -- and unlike a padded record, there is no
   * whitespace for the fallback to rescue, so choosing the wrong width here
   * produces four ids instead of eight and loses the element.
   *
   * This case is why the width test cannot be "does anything still parse". */
  std::string document = "2C\n";
  std::string connectivity;
  const double coords[8][3] = {{0, 0, 0}, {1, 0, 0}, {1, 1, 0}, {0, 1, 0},
                               {0, 0, 1}, {1, 0, 1}, {1, 1, 1}, {0, 1, 1}};
  for (int i = 0; i < 8; ++i) {
    const int id = 10001 + i;
    document += " -1" + std::to_string(id) + " " + std::to_string(coords[i][0]) + " " +
                std::to_string(coords[i][1]) + " " + std::to_string(coords[i][2]) + "\n";
    connectivity += std::to_string(id);
  }
  ASSERT_EQ(connectivity.size(), 40u);
  ASSERT_EQ(connectivity.find(' '), std::string::npos) << "the ids must be glued";
  document += " -3\n3C\n -1    1    1\n -2" + connectivity + "\n -3\n";

  Doc doc(document);
  ASSERT_EQ(doc.status(), PVFRD_OK);
  EXPECT_EQ(pvfrd_n_points(doc.get()), 8u);
  ASSERT_EQ(pvfrd_n_cells(doc.get()), 1u) << "read ten-wide, this element loses half its nodes";
  EXPECT_EQ(doc.connectivity(), (std::vector<int64_t>{0, 1, 2, 3, 4, 5, 6, 7}));
  EXPECT_EQ(pvfrd_n_diagnostics(doc.get()), 0u);
}

TEST(ParseTest, ABlockWhoseRecordsAllFailContributesNoArray) {
  /* Distinct from a block with no records at all: this one has data lines,
   * they are simply unusable. The step still exists -- it came from the
   * header -- but it holds nothing.
   *
   * Worth its own case because the two states reach different code: a block
   * with no records is never indexed, while this one is indexed and then
   * comes back empty. */
  Doc doc(std::string(kFourNodes) +
          "100CL 1 0.5\n"
          " -4 BAD 1\n"
          " -1bad_f 1.0\n"
          " -1also_bad 2.0\n"
          " -3\n");
  ASSERT_EQ(doc.status(), PVFRD_OK);
  ASSERT_EQ(pvfrd_n_steps(doc.get()), 1u);
  uint64_t n = 99;
  ASSERT_EQ(pvfrd_n_arrays(doc.get(), 0, &n), PVFRD_OK);
  EXPECT_EQ(n, 0u);
}

TEST(ParseTest, WhitespaceFallbackRescuesAPaddedWideRecord) {
  /* A record over fifty characters long that is nonetheless five-wide
   * padded fields -- which is what a twenty-node hexahedron looks like.
   * Long format is detected from the length, ten-wide chunking then fails on
   * every chunk because each one straddles two fields, and only the
   * whitespace fallback recovers the twenty ids.
   *
   * This is the case that makes the fallback load-bearing rather than
   * defensive: without it, every quadratic hexahedron in every file loses
   * its element. */
  std::string document = "2C\n";
  std::string connectivity;
  for (int i = 1; i <= 20; ++i) {
    document += " -1 " + std::to_string(i) + " 0.0 0.0 0.0\n";
    const std::string field = std::to_string(i);
    connectivity += std::string(5 - field.size(), ' ') + field;
  }
  ASSERT_GT(connectivity.size(), 50u) << "must be long format by length";
  document += " -3\n3C\n -1    1    4\n -2" + connectivity + "\n -3\n";

  Doc doc(document);
  ASSERT_EQ(doc.status(), PVFRD_OK);
  ASSERT_EQ(pvfrd_n_cells(doc.get()), 1u) << "the fallback is what builds this element";
  EXPECT_EQ(pvfrd_cell_types(doc.get())[0], 25) << "QUADRATIC_HEXAHEDRON";
  EXPECT_EQ(doc.connectivity().size(), 20u);
  EXPECT_EQ(pvfrd_n_diagnostics(doc.get()), 0u);
}

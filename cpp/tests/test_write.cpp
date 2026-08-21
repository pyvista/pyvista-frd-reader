/* The writer, at the level the Python tier cannot reach.
 *
 * The byte-match gate over real files is the strongest evidence there is that
 * this emitter produces CalculiX's bytes, and it says nothing about the
 * *constructed* path -- a mesh handed in through the builder has no original
 * to be compared against. These are the claims that path rests on.
 */

#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <vector>

#include "pvfrd/pvfrd.h"

namespace {

/* A writer that frees itself. */
class Build {
 public:
  explicit Build(int32_t format) : writer_(pvfrd_writer_new(format)) {}
  ~Build() { pvfrd_writer_free(writer_); }
  Build(const Build &) = delete;
  Build &operator=(const Build &) = delete;

  pvfrd_writer *get() const { return writer_; }
  explicit operator bool() const { return writer_ != nullptr; }

 private:
  pvfrd_writer *writer_ = nullptr;
};

/* An opened document that closes itself. */
class Doc {
 public:
  Doc(const char *data, size_t size) {
    pvfrd_open_options options = {PVFRD_WEDGE_ASIS, 0};
    status_ = pvfrd_open_memory(data, size, &options, &file_);
  }
  ~Doc() { pvfrd_close(file_); }
  Doc(const Doc &) = delete;
  Doc &operator=(const Doc &) = delete;

  pvfrd_status status() const { return status_; }
  pvfrd_file *get() const { return file_; }

 private:
  pvfrd_file *file_ = nullptr;
  pvfrd_status status_ = PVFRD_OK;
};

struct TypeCase {
  uint8_t vtk_type;
  uint32_t n_points;
  const char *name;
};

/* Every type the reader knows, so that "the writer supports what the reader
 * supports" is a statement the suite checks rather than one this comment
 * makes. */
const TypeCase kTypes[] = {
    {12, 8, "HEXAHEDRON"},
    {13, 6, "WEDGE"},
    {10, 4, "TETRA"},
    {25, 20, "QUADRATIC_HEXAHEDRON"},
    {26, 15, "QUADRATIC_WEDGE"},
    {24, 10, "QUADRATIC_TETRA"},
    {5, 3, "TRIANGLE"},
    {22, 6, "QUADRATIC_TRIANGLE"},
    {9, 4, "QUAD"},
    {23, 8, "QUADRATIC_QUAD"},
    {3, 2, "LINE"},
    {21, 3, "QUADRATIC_EDGE"},
    {14, 5, "PYRAMID"},
    {27, 13, "QUADRATIC_PYRAMID"},
};

/* One cell of `type`, with every node in a distinct place so that a
 * permutation applied to the connectivity is visible in the result. */
std::string one_cell(uint8_t vtk_type, uint32_t n_points, int32_t format, int32_t wedge_order) {
  std::vector<double> points;
  std::vector<int64_t> connectivity;
  for (uint32_t i = 0; i < n_points; ++i) {
    points.push_back(static_cast<double>(i));
    points.push_back(static_cast<double>(i) * 2.0);
    points.push_back(static_cast<double>(i) * 4.0);
    connectivity.push_back(i);
  }
  const int64_t offsets[2] = {0, static_cast<int64_t>(n_points)};

  Build build(format);
  EXPECT_TRUE(static_cast<bool>(build));
  EXPECT_EQ(pvfrd_writer_set_nodes(build.get(), n_points, nullptr, points.data()), PVFRD_OK);
  EXPECT_EQ(pvfrd_writer_set_cells(build.get(), 1, &vtk_type, offsets, connectivity.data(), nullptr,
                                   wedge_order),
            PVFRD_OK);
  char *out = nullptr;
  size_t size = 0;
  EXPECT_EQ(pvfrd_writer_finish(build.get(), &out, &size), PVFRD_OK);
  std::string text(out, size);
  pvfrd_free(out);
  return text;
}

}  // namespace

TEST(WriteTest, ReadingBackAWrittenCellRecoversItsConnectivity) {
  /* The property that matters for the node ordering, stated for every type
   * and both wedge conventions.
   *
   * Reading permutes CalculiX's order into VTK's and writing permutes it
   * back. Every one of those permutations happens to be its own inverse
   * today, which is exactly why the writer does not reuse the reader's: a
   * table that inverts itself is a coincidence nobody declared, and the first
   * type whose ordering is a rotation rather than a swap would turn the reuse
   * into a silently wrong file. This is the test that would notice. */
  for (const TypeCase &type : kTypes) {
    for (int32_t wedge : {PVFRD_WEDGE_ASIS, PVFRD_WEDGE_SWAP}) {
      const std::string written =
          one_cell(type.vtk_type, type.n_points, PVFRD_FORMAT_LONG_ASCII, wedge);
      pvfrd_open_options options = {wedge, 0};
      pvfrd_file *file = nullptr;
      ASSERT_EQ(pvfrd_open_memory(written.data(), written.size(), &options, &file), PVFRD_OK)
          << type.name;

      ASSERT_EQ(pvfrd_n_cells(file), 1u) << type.name;
      EXPECT_EQ(pvfrd_cell_types(file)[0], type.vtk_type) << type.name;

      const int64_t *offsets = pvfrd_cell_offsets(file);
      const int64_t *connectivity = pvfrd_cell_connectivity(file);
      ASSERT_EQ(offsets[1] - offsets[0], static_cast<int64_t>(type.n_points)) << type.name;
      for (uint32_t i = 0; i < type.n_points; ++i) {
        EXPECT_EQ(connectivity[i], static_cast<int64_t>(i))
            << type.name << " node " << i << " (wedge order " << wedge << ")";
      }
      pvfrd_close(file);
    }
  }
}

TEST(WriteTest, EveryTypeTheReaderKnowsCanBeWritten) {
  /* Otherwise a type could be quietly write-only-unsupported and the loop
   * above would skip it without saying so. */
  for (const TypeCase &type : kTypes) {
    const std::string written =
        one_cell(type.vtk_type, type.n_points, PVFRD_FORMAT_LONG_ASCII, PVFRD_WEDGE_ASIS);
    EXPECT_FALSE(written.empty()) << type.name;
  }
}

TEST(WriteTest, AnUnknownCellTypeIsRefusedAndNamed) {
  const double points[12] = {0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0};
  const uint8_t polygon = 7; /* VTK_POLYGON: a concept, not an FRD element */
  const int64_t offsets[2] = {0, 4};
  const int64_t connectivity[4] = {0, 1, 2, 3};

  Build build(PVFRD_FORMAT_LONG_ASCII);
  ASSERT_TRUE(static_cast<bool>(build));
  ASSERT_EQ(pvfrd_writer_set_nodes(build.get(), 4, nullptr, points), PVFRD_OK);
  EXPECT_EQ(pvfrd_writer_set_cells(build.get(), 1, &polygon, offsets, connectivity, nullptr,
                                   PVFRD_WEDGE_ASIS),
            PVFRD_E_FORMAT);
  EXPECT_NE(std::string(pvfrd_last_error(nullptr)).find("VTK type 7"), std::string::npos)
      << pvfrd_last_error(nullptr);
}

TEST(WriteTest, ACellWithTheWrongNumberOfPointsIsRefused) {
  /* Writing it anyway would produce an element record whose node count
   * disagrees with its own type code, which the reader would then read as
   * something else entirely. */
  const double points[24] = {0};
  const uint8_t hexahedron = 12;
  const int64_t offsets[2] = {0, 4};
  const int64_t connectivity[4] = {0, 1, 2, 3};

  Build build(PVFRD_FORMAT_LONG_ASCII);
  ASSERT_TRUE(static_cast<bool>(build));
  ASSERT_EQ(pvfrd_writer_set_nodes(build.get(), 8, nullptr, points), PVFRD_OK);
  EXPECT_EQ(pvfrd_writer_set_cells(build.get(), 1, &hexahedron, offsets, connectivity, nullptr,
                                   PVFRD_WEDGE_ASIS),
            PVFRD_E_FORMAT);
}

TEST(WriteTest, ConnectivityPointingOutsideTheMeshIsRefused) {
  const double points[6] = {0, 0, 0, 1, 0, 0};
  const uint8_t line = 3;
  const int64_t offsets[2] = {0, 2};
  const int64_t connectivity[2] = {0, 99};

  Build build(PVFRD_FORMAT_LONG_ASCII);
  ASSERT_TRUE(static_cast<bool>(build));
  ASSERT_EQ(pvfrd_writer_set_nodes(build.get(), 2, nullptr, points), PVFRD_OK);
  EXPECT_EQ(pvfrd_writer_set_cells(build.get(), 1, &line, offsets, connectivity, nullptr,
                                   PVFRD_WEDGE_ASIS),
            PVFRD_E_FORMAT);
}

TEST(WriteTest, ANotAFormatCodeIsRefusedRatherThanDefaulted) {
  EXPECT_EQ(pvfrd_writer_new(9), nullptr);
  EXPECT_EQ(pvfrd_writer_new(-1), nullptr) << "KEEP is meaningless with nothing to keep";
}

TEST(WriteTest, ArraysNeedAStepToBelongTo) {
  const double points[3] = {0, 0, 0};
  const double values[1] = {1.0};
  Build build(PVFRD_FORMAT_LONG_ASCII);
  ASSERT_TRUE(static_cast<bool>(build));
  ASSERT_EQ(pvfrd_writer_set_nodes(build.get(), 1, nullptr, points), PVFRD_OK);
  EXPECT_EQ(pvfrd_writer_add_array(build.get(), "T", 1, nullptr, 0, values), PVFRD_E_INVALID);
}

TEST(WriteTest, TheWrittenFileDoesNotClaimCalculiXWroteIt) {
  /* This repository identifies solver output by the 1UPGM banner, and several
   * of its own gates depend on that being true. A writer that stamped
   * CalculiX's name on its output would make every one of them a lie. */
  const std::string written = one_cell(12, 8, PVFRD_FORMAT_LONG_ASCII, PVFRD_WEDGE_ASIS);
  EXPECT_EQ(written.find("CalculiX"), std::string::npos);
  EXPECT_NE(written.find("pyvista-frd-reader"), std::string::npos);
}

TEST(WriteTest, EveryFormatProducesSomethingTheReaderAccepts) {
  for (int32_t format : {PVFRD_FORMAT_SHORT_ASCII, PVFRD_FORMAT_LONG_ASCII,
                         PVFRD_FORMAT_BINARY_FLOAT, PVFRD_FORMAT_BINARY_DOUBLE}) {
    const std::string written = one_cell(12, 8, format, PVFRD_WEDGE_ASIS);
    Doc doc(written.data(), written.size());
    ASSERT_EQ(doc.status(), PVFRD_OK) << "format " << format;
    EXPECT_EQ(pvfrd_n_points(doc.get()), 8u) << "format " << format;
    EXPECT_EQ(pvfrd_n_cells(doc.get()), 1u) << "format " << format;
  }
}

TEST(WriteTest, RewritingRefusesToConvertWhatItCannotRestamp) {
  /* A header with no format code cannot be re-stamped, so converting its
   * records would leave the header declaring an encoding they no longer use.
   * The file would look plausible and read as nonsense. */
  const std::string document =
      "1C no format code anywhere\n"
      "2C\n"
      " -1    1 0.0 0.0 0.0\n"
      " -3\n";
  char *out = nullptr;
  size_t size = 0;
  EXPECT_EQ(pvfrd_rewrite_memory(document.data(), document.size(), PVFRD_FORMAT_BINARY_DOUBLE, &out,
                                 &size),
            PVFRD_E_FORMAT);
  EXPECT_EQ(out, nullptr);

  /* And keeping the format is still fine, because nothing has to be restamped. */
  EXPECT_EQ(pvfrd_rewrite_memory(document.data(), document.size(), PVFRD_FORMAT_KEEP, &out, &size),
            PVFRD_OK);
  pvfrd_free(out);
}

TEST(WriteTest, NullArgumentsAreRejectedNotDereferenced) {
  char *out = nullptr;
  size_t size = 0;
  EXPECT_EQ(pvfrd_rewrite_memory(nullptr, 4, PVFRD_FORMAT_KEEP, &out, &size), PVFRD_E_INVALID);
  EXPECT_EQ(pvfrd_rewrite_memory("x", 1, PVFRD_FORMAT_KEEP, nullptr, &size), PVFRD_E_INVALID);
  EXPECT_EQ(pvfrd_rewrite_memory("x", 1, 42, &out, &size), PVFRD_E_INVALID);

  EXPECT_EQ(pvfrd_writer_set_nodes(nullptr, 0, nullptr, nullptr), PVFRD_E_INVALID);
  EXPECT_EQ(pvfrd_writer_begin_step(nullptr, 1, 0.0), PVFRD_E_INVALID);
  EXPECT_EQ(pvfrd_writer_add_array(nullptr, "x", 1, nullptr, 0, nullptr), PVFRD_E_INVALID);
  EXPECT_EQ(pvfrd_writer_finish(nullptr, &out, &size), PVFRD_E_INVALID);
  pvfrd_writer_free(nullptr); /* must be a no-op */
  pvfrd_free(nullptr);
}

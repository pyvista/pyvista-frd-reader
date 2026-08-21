/* The binary half of the FRD format.
 *
 * A block header's last field is its format code: 0 and 1 are the two ASCII
 * widths, 2 is binary float32 and 3 is binary float64. This library read only
 * the ASCII codes, and the failure mode was the quiet one -- a `*REFINE MESH`
 * file, which CalculiX writes in binary unconditionally, would declare 2195
 * nodes in its header and hand back a mesh with none of them, without an
 * error. The tests here are inline byte strings rather than fixtures so that
 * the record layout being claimed is legible at the point of the claim.
 *
 * Binary blocks have no ` -3` terminator. CalculiX writes it only in ASCII
 * mode (`frd.c`: `if(strcmp1(output,"asc")==0)fprintf(f1,"%3s\n",m3);`), so a
 * binary payload runs straight into the next header line and every one of
 * these documents is written that way on purpose.
 */

#include <gtest/gtest.h>

#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

#include "pvfrd/pvfrd.h"

namespace {

/* Little-endian, which is what CalculiX's fwrite produces on every platform
 * this library ships wheels for. */
class Bytes {
 public:
  Bytes &text(const std::string &s) {
    buffer_ += s;
    return *this;
  }
  Bytes &i32(int32_t value) { return raw(&value, sizeof(value)); }
  Bytes &f32(float value) { return raw(&value, sizeof(value)); }
  Bytes &f64(double value) { return raw(&value, sizeof(value)); }
  const std::string &str() const { return buffer_; }

 private:
  Bytes &raw(const void *p, size_t n) {
    const char *bytes = static_cast<const char *>(p);
    buffer_.append(bytes, n);
    return *this;
  }
  std::string buffer_;
};

class Doc {
 public:
  explicit Doc(const std::string &text) {
    pvfrd_open_options options = {PVFRD_WEDGE_ASIS, 0};
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

 private:
  pvfrd_file *file_ = nullptr;
  pvfrd_status status_ = PVFRD_OK;
};

/* `    2C` and a count, with the format code last. The intervening fields are
 * CalculiX's and are not read. */
std::string node_header(int count, int format) {
  return "    2C" + std::string(18, ' ') + std::to_string(count) + std::string(37, ' ') +
         std::to_string(format) + "\n";
}

std::string element_header(int count, int format) {
  return "    3C" + std::string(18, ' ') + std::to_string(count) + std::string(37, ' ') +
         std::to_string(format) + "\n";
}

}  // namespace

TEST(BinaryTest, Float64NodesAreDecoded) {
  Bytes doc;
  doc.text(node_header(2, 3))
      .i32(10)
      .f64(1.5)
      .f64(2.5)
      .f64(3.5)
      .i32(20)
      .f64(-1.0)
      .f64(0.0)
      .f64(4.25);

  Doc file(doc.str());
  ASSERT_EQ(file.status(), PVFRD_OK);
  ASSERT_EQ(pvfrd_n_points(file.get()), 2u);

  const int64_t *ids = pvfrd_node_ids(file.get());
  EXPECT_EQ(ids[0], 10);
  EXPECT_EQ(ids[1], 20);

  const double *p = pvfrd_points(file.get());
  EXPECT_DOUBLE_EQ(p[0], 1.5);
  EXPECT_DOUBLE_EQ(p[1], 2.5);
  EXPECT_DOUBLE_EQ(p[2], 3.5);
  EXPECT_DOUBLE_EQ(p[3], -1.0);
  EXPECT_DOUBLE_EQ(p[5], 4.25);
}

TEST(BinaryTest, Float32NodesAreDecoded) {
  /* Format 2 is a 16-byte record where format 3 is 28. Reading one as the
   * other does not fail, it silently produces a different mesh, so the two
   * widths are stated separately. */
  Bytes doc;
  doc.text(node_header(2, 2))
      .i32(7)
      .f32(1.5f)
      .f32(2.5f)
      .f32(3.5f)
      .i32(8)
      .f32(-1.0f)
      .f32(0.0f)
      .f32(4.25f);

  Doc file(doc.str());
  ASSERT_EQ(file.status(), PVFRD_OK);
  ASSERT_EQ(pvfrd_n_points(file.get()), 2u);
  EXPECT_EQ(pvfrd_node_ids(file.get())[0], 7);
  EXPECT_DOUBLE_EQ(pvfrd_points(file.get())[0], 1.5);
  EXPECT_DOUBLE_EQ(pvfrd_points(file.get())[5], 4.25);
}

TEST(BinaryTest, ATruncatedNodeBlockIsAnErrorNotAnEmptyMesh) {
  /* The bug this whole file exists for. The header promises three nodes and
   * the payload holds one; the answer is a refusal, because handing back a
   * one-node mesh from a file that says three would be indistinguishable
   * from having read it correctly. */
  Bytes doc;
  doc.text(node_header(3, 3)).i32(1).f64(0.0).f64(0.0).f64(0.0);

  Doc file(doc.str());
  EXPECT_EQ(file.status(), PVFRD_E_FORMAT);
  const std::string message = pvfrd_last_error(file.get());
  EXPECT_NE(message.find("truncated binary node block"), std::string::npos)
      << "actual: " << message;
}

TEST(BinaryTest, ElementsUseTheSamePermutationAsAscii) {
  /* A binary element record is four int32 of bookkeeping -- number, type,
   * group, material -- and then the connectivity, with the *same* CalculiX
   * ordering the ASCII path already permutes. The claim is checked against an
   * ASCII document describing the same element rather than against a literal,
   * so that a change to the permutation cannot be made to pass here by
   * updating an expected array. */
  const std::string ascii =
      "    2C                   8                                     1\n"
      " -1    1 0.0 0.0 0.0\n"
      " -1    2 1.0 0.0 0.0\n"
      " -1    3 1.0 1.0 0.0\n"
      " -1    4 0.0 1.0 0.0\n"
      " -1    5 0.0 0.0 1.0\n"
      " -1    6 1.0 0.0 1.0\n"
      " -1    7 1.0 1.0 1.0\n"
      " -1    8 0.0 1.0 1.0\n"
      " -3\n"
      "    3C                   1                                     1\n"
      " -1         1    1    0    0\n"
      " -2         1         2         3         4         5         6         7         8\n"
      " -3\n";

  Bytes binary;
  binary.text(node_header(8, 3));
  const double xyz[8][3] = {{0, 0, 0}, {1, 0, 0}, {1, 1, 0}, {0, 1, 0},
                            {0, 0, 1}, {1, 0, 1}, {1, 1, 1}, {0, 1, 1}};
  for (int i = 0; i < 8; ++i) {
    binary.i32(i + 1).f64(xyz[i][0]).f64(xyz[i][1]).f64(xyz[i][2]);
  }
  binary.text(element_header(1, 2)).i32(1).i32(1).i32(0).i32(0);
  for (int i = 1; i <= 8; ++i) binary.i32(i);

  Doc a(ascii);
  Doc b(binary.str());
  ASSERT_EQ(a.status(), PVFRD_OK);
  ASSERT_EQ(b.status(), PVFRD_OK);
  ASSERT_EQ(pvfrd_n_cells(b.get()), pvfrd_n_cells(a.get()));
  EXPECT_EQ(b.connectivity(), a.connectivity());
  EXPECT_EQ(pvfrd_cell_types(b.get())[0], pvfrd_cell_types(a.get())[0]);
}

TEST(BinaryTest, AnUnknownElementTypeStopsTheBlock) {
  /* The ASCII path skips a record it does not understand and carries on. The
   * binary path cannot: the next record's offset is only known from this
   * one's node count, so an unknown type makes everything after it
   * unreadable. Resynchronising would mean decoding numbers out of the middle
   * of other numbers. */
  Bytes doc;
  doc.text(node_header(1, 3)).i32(1).f64(0.0).f64(0.0).f64(0.0);
  doc.text(element_header(1, 2)).i32(1).i32(99).i32(0).i32(0);

  Doc file(doc.str());
  EXPECT_EQ(file.status(), PVFRD_E_FORMAT);
}

TEST(BinaryTest, DerivedComponentsDoNotWidenTheRecord) {
  /* A displacement block declares four components and stores three: ALL is
   * computed by the postprocessor and marked with a trailing `1`, which
   * CalculiX prints hard against the component name as `1ALL`. Counting that
   * as a stored component makes every record 8 bytes too wide and every value
   * after the first comes out of the wrong offset -- so this is the case that
   * decides whether the block is read at all. */
  Bytes doc;
  doc.text(node_header(2, 3)).i32(1).f64(0.0).f64(0.0).f64(0.0).i32(2).f64(1.0).f64(0.0).f64(0.0);
  doc.text(
      "  100CL  101 1.000000000           2                     0    1           3\n"
      " -4  DISP        4    1\n"
      " -5  D1          1    2    1    0\n"
      " -5  D2          1    2    2    0\n"
      " -5  D3          1    2    3    0\n"
      " -5  ALL         1    2    0    0    1ALL\n");
  doc.i32(1).f64(0.25).f64(0.5).f64(0.75);
  doc.i32(2).f64(1.25).f64(1.5).f64(1.75);

  Doc file(doc.str());
  ASSERT_EQ(file.status(), PVFRD_OK);
  ASSERT_EQ(pvfrd_n_steps(file.get()), 1u);
  uint64_t n_arrays = 0;
  ASSERT_EQ(pvfrd_n_arrays(file.get(), 0, &n_arrays), PVFRD_OK);
  ASSERT_EQ(n_arrays, 1u);

  pvfrd_array_info info;
  ASSERT_EQ(pvfrd_array_info_at(file.get(), 0, 0, &info), PVFRD_OK);
  EXPECT_EQ(std::string(info.name), "DISP");
  ASSERT_EQ(info.n_components, 3u) << "the derived ALL component was counted as stored";

  const double *values = nullptr;
  ASSERT_EQ(pvfrd_array_data(file.get(), 0, 0, &values), PVFRD_OK);
  ASSERT_EQ(info.n_tuples, 2u);
  EXPECT_DOUBLE_EQ(values[0], 0.25);
  EXPECT_DOUBLE_EQ(values[2], 0.75);
  EXPECT_DOUBLE_EQ(values[3], 1.25);
  EXPECT_DOUBLE_EQ(values[5], 1.75);
}

TEST(BinaryTest, ABinaryPayloadRunsStraightIntoTheNextHeader) {
  /* No ` -3` between the node block and the element block, because CalculiX
   * does not write one in binary mode. A reader that waited for a terminator
   * would consume the element header looking for it. */
  Bytes doc;
  doc.text(node_header(2, 3)).i32(1).f64(0.0).f64(0.0).f64(0.0).i32(2).f64(1.0).f64(0.0).f64(0.0);
  doc.text(element_header(1, 2)).i32(1).i32(11).i32(0).i32(0).i32(1).i32(2);

  Doc file(doc.str());
  ASSERT_EQ(file.status(), PVFRD_OK);
  EXPECT_EQ(pvfrd_n_points(file.get()), 2u);
  EXPECT_EQ(pvfrd_n_cells(file.get()), 1u);
}

TEST(BinaryTest, AnAsciiHeaderCountIsNotBelievedOverTheRecords) {
  /* The counterpart to the binary rule above, and the reason the two paths
   * differ.
   *
   * A binary block has to trust its header's record count: there is no
   * terminator to scan for and the count is the only statement of where the
   * payload ends. An ASCII block does not have to, and must not. CalculiX
   * expands shell and beam elements into solid elements for output and writes
   * the `3C` header with the count from *before* the expansion, so
   * concretebeam.frd declares 10 elements and holds 110. Measured across its
   * regression suite: node counts agree 784 times out of 784, element counts
   * disagree 5 times out of 784.
   *
   * Refusing the file, or stopping at the tenth element, would lose 100
   * elements CalculiX meant to write and PyVista reads. The records are the
   * truth here; the count is a hint that is sometimes wrong. */
  Doc file(
      "    3C                             1                                     1\n"
      " -1         1   11    0    1\n"
      " -2         1         2\n"
      " -1         2   11    0    1\n"
      " -2         2         3\n"
      " -3\n"
      "    2C                             3                                     1\n"
      " -1    1 0.0 0.0 0.0\n"
      " -1    2 1.0 0.0 0.0\n"
      " -1    3 2.0 0.0 0.0\n"
      " -3\n");
  ASSERT_EQ(file.status(), PVFRD_OK);
  EXPECT_EQ(pvfrd_n_cells(file.get()), 2u)
      << "the header said one element; the block holds two, and both are real";
  EXPECT_EQ(pvfrd_n_points(file.get()), 3u);
}

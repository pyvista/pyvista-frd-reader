/* The C ABI as a foreign caller meets it.
 *
 * Everything here is about the boundary rather than about FRD: null
 * arguments, ranges, lifetimes, and the corpus files being readable at all.
 * A binding written against this header has no compiler checking its calls,
 * so every one of these is a call somebody will make by accident.
 */

#include <gtest/gtest.h>

#include <cstddef>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <string>
#include <thread>
#include <vector>

#include "pvfrd/pvfrd.h"

#ifndef PVFRD_FIXTURE_DIR
#error "PVFRD_FIXTURE_DIR must be defined by the build"
#endif

namespace {

std::string fixture(const std::string &name) {
  return std::string(PVFRD_FIXTURE_DIR) + "/" + name;
}

/* Every file the Python parity sweep grades, so a corpus file that this tier
 * cannot even open is a failure here rather than a surprise there. */
const char *kCorpus[] = {
    "mesh.frd",
    "mock.frd",
    "mock_crlf.frd",
    "mock_cr.frd",
    "comprehensive.frd",
    "no_steps.frd",
    "empty.frd",
    "coverage_edge_cases.frd",
    "pyramids.frd",
    "long_format.frd",
    "glued.frd",
    "ragged.frd",
    "broadcast.frd",
    "duplicate_names.frd",
    "glued_ids_short.frd",
    "unparseable_block.frd",
    "unsorted_nodes.frd",
    "elements/HE8.frd",
    "elements/PE6.frd",
    "elements/TE4.frd",
    "elements/HE20.frd",
    "elements/PE15.frd",
    "elements/TE10.frd",
    "elements/TR3.frd",
    "elements/TR6.frd",
    "elements/QU4.frd",
    "elements/QU8.frd",
    "elements/BE2.frd",
    "elements/BE3.frd",
    "elements/PY5.frd",
    "elements/PY13.frd",
};

}  // namespace

TEST(ApiTest, AbiVersionMatchesTheHeader) {
  EXPECT_EQ(pvfrd_abi_version(), PVFRD_ABI_VERSION);
}

TEST(ApiTest, StatusMessagesAreNeverNull) {
  for (int status = -5; status < 20; ++status) {
    const char *message = pvfrd_status_message(status);
    ASSERT_NE(message, nullptr) << "status " << status;
    EXPECT_GT(std::string(message).size(), 0u) << "status " << status;
  }
}

TEST(ApiTest, NullArgumentsAreRejectedNotDereferenced) {
  pvfrd_file *file = nullptr;
  EXPECT_EQ(pvfrd_open(nullptr, &file), PVFRD_E_INVALID);
  EXPECT_EQ(pvfrd_open("whatever", nullptr), PVFRD_E_INVALID);
  EXPECT_EQ(pvfrd_open_memory(nullptr, 4, nullptr, &file), PVFRD_E_INVALID);
  EXPECT_EQ(pvfrd_open_memory("x", 1, nullptr, nullptr), PVFRD_E_INVALID);

  /* Accessors on a null handle answer rather than crash: a binding that
   * failed to check an open is otherwise a segmentation fault with no
   * diagnosis available to whoever hits it. */
  EXPECT_EQ(pvfrd_n_points(nullptr), 0u);
  EXPECT_EQ(pvfrd_points(nullptr), nullptr);
  EXPECT_EQ(pvfrd_node_ids(nullptr), nullptr);
  EXPECT_EQ(pvfrd_n_cells(nullptr), 0u);
  EXPECT_EQ(pvfrd_cell_types(nullptr), nullptr);
  EXPECT_EQ(pvfrd_cell_offsets(nullptr), nullptr);
  EXPECT_EQ(pvfrd_cell_connectivity(nullptr), nullptr);
  EXPECT_EQ(pvfrd_n_diagnostics(nullptr), 0u);
  EXPECT_EQ(pvfrd_n_steps(nullptr), 0u);
  EXPECT_EQ(pvfrd_find_array(nullptr, 0, "x"), -1);
  EXPECT_NE(pvfrd_last_error(nullptr), nullptr);

  /* `pvfrd_last_error(NULL)` is documented as the last failure recorded on
   * the *calling* thread, so "it is empty" is a claim about that thread's
   * history and not about null-argument handling. Asserting it here passed
   * only for as long as no earlier test in the binary happened to record a
   * failure -- adding a file of tests that open malformed documents was
   * enough to break it, which makes the assertion a statement about link
   * order rather than about the library. A thread that has not failed yet is
   * the precondition, so the test makes one. */
  std::thread([] { EXPECT_STREQ(pvfrd_last_error(nullptr), ""); }).join();

  pvfrd_close(nullptr); /* must be a no-op, not a free of garbage */
}

TEST(ApiTest, MissingFileIsAnIoError) {
  pvfrd_file *file = reinterpret_cast<pvfrd_file *>(0x1);
  EXPECT_EQ(pvfrd_open(fixture("does-not-exist.frd").c_str(), &file), PVFRD_E_IO);
  /* And the out parameter is cleared, so a caller that ignores the status
   * does not go on to use a stale pointer. */
  EXPECT_EQ(file, nullptr);
}

TEST(ApiTest, InvalidOptionsAreRejected) {
  pvfrd_file *file = nullptr;
  const std::string text = "1C\n";

  pvfrd_open_options bad_wedge = {42, 0};
  EXPECT_EQ(pvfrd_open_memory(text.data(), text.size(), &bad_wedge, &file), PVFRD_E_INVALID);

  /* The reserved field is checked so that a future option cannot be silently
   * ignored by an older library: a caller setting it gets an error naming
   * the misuse rather than results computed without it. */
  pvfrd_open_options reserved_set = {PVFRD_WEDGE_ASIS, 1};
  EXPECT_EQ(pvfrd_open_memory(text.data(), text.size(), &reserved_set, &file), PVFRD_E_INVALID);
}

TEST(ApiTest, EmptyBufferOpens) {
  pvfrd_file *file = nullptr;
  ASSERT_EQ(pvfrd_open_memory("", 0, nullptr, &file), PVFRD_OK);
  EXPECT_EQ(pvfrd_n_points(file), 0u);
  pvfrd_close(file);
}

TEST(ApiTest, EveryCorpusFileOpens) {
  for (const char *name : kCorpus) {
    pvfrd_file *file = nullptr;
    EXPECT_EQ(pvfrd_open(fixture(name).c_str(), &file), PVFRD_OK) << name;
    EXPECT_NE(file, nullptr) << name;
    pvfrd_close(file);
  }
}

TEST(ApiTest, TheCorpusListHereCoversTheFixtureDirectory) {
  /* A list of names in a test file goes stale the moment someone adds a
   * fixture. This does not enumerate the directory -- the build has no
   * filesystem walk -- so instead it pins the count, which is the cheapest
   * thing that turns "someone added a file and forgot this list" into a
   * failure rather than into silently reduced coverage. */
  EXPECT_EQ(sizeof(kCorpus) / sizeof(kCorpus[0]), 31u)
      << "add the new fixture to kCorpus and update this count";
}

TEST(ApiTest, RangeErrorsAreReportedNotClamped) {
  pvfrd_file *file = nullptr;
  ASSERT_EQ(pvfrd_open(fixture("mesh.frd").c_str(), &file), PVFRD_OK);

  const uint64_t n_steps = pvfrd_n_steps(file);
  ASSERT_GT(n_steps, 0u);

  double time = 0.0;
  EXPECT_EQ(pvfrd_step_time(file, n_steps, &time), PVFRD_E_RANGE);

  uint64_t n_arrays = 0;
  ASSERT_EQ(pvfrd_n_arrays(file, 0, &n_arrays), PVFRD_OK);
  ASSERT_GT(n_arrays, 0u);

  pvfrd_array_info info;
  EXPECT_EQ(pvfrd_array_info_at(file, 0, n_arrays, &info), PVFRD_E_RANGE);
  EXPECT_EQ(pvfrd_array_info_at(file, n_steps, 0, &info), PVFRD_E_RANGE);

  const double *data = nullptr;
  EXPECT_EQ(pvfrd_array_data(file, 0, n_arrays, &data), PVFRD_E_RANGE);
  EXPECT_EQ(data, nullptr);

  pvfrd_diagnostic diagnostic;
  EXPECT_EQ(pvfrd_diagnostic_at(file, 0, &diagnostic), PVFRD_E_RANGE);

  pvfrd_close(file);
}

TEST(ApiTest, ArrayInfoRangeRejectsAWrappingRequest) {
  pvfrd_file *file = nullptr;
  ASSERT_EQ(pvfrd_open(fixture("mesh.frd").c_str(), &file), PVFRD_OK);

  std::vector<pvfrd_array_info> info(4);
  /* first + count overflows uint64. Checked by subtraction rather than
   * addition, or this request would look like a small one. */
  EXPECT_EQ(pvfrd_array_info_range(file, 0, 2, UINT64_MAX, info.data()), PVFRD_E_RANGE);
  /* A zero count succeeds and writes nothing, so a caller looping over an
   * empty step needs no special case. */
  EXPECT_EQ(pvfrd_array_info_range(file, 0, 0, 0, nullptr), PVFRD_OK);

  pvfrd_close(file);
}

TEST(ApiTest, BatchInfoAgreesWithOneAtATime) {
  pvfrd_file *file = nullptr;
  ASSERT_EQ(pvfrd_open(fixture("mesh.frd").c_str(), &file), PVFRD_OK);

  uint64_t n = 0;
  ASSERT_EQ(pvfrd_n_arrays(file, 0, &n), PVFRD_OK);
  std::vector<pvfrd_array_info> batch(n);
  ASSERT_EQ(pvfrd_array_info_range(file, 0, 0, n, batch.data()), PVFRD_OK);

  for (uint64_t i = 0; i < n; ++i) {
    pvfrd_array_info single;
    ASSERT_EQ(pvfrd_array_info_at(file, 0, i, &single), PVFRD_OK);
    EXPECT_STREQ(batch[i].name, single.name);
    EXPECT_EQ(batch[i].n_components, single.n_components);
    EXPECT_EQ(batch[i].n_tuples, single.n_tuples);
    EXPECT_EQ(batch[i].kind, single.kind);
  }
  pvfrd_close(file);
}

TEST(ApiTest, FindArrayIsExactAndReportsAbsence) {
  pvfrd_file *file = nullptr;
  ASSERT_EQ(pvfrd_open(fixture("mesh.frd").c_str(), &file), PVFRD_OK);

  EXPECT_GE(pvfrd_find_array(file, 0, "DISP"), 0);
  EXPECT_EQ(pvfrd_find_array(file, 0, "disp"), -1) << "lookup must not fold case";
  EXPECT_EQ(pvfrd_find_array(file, 0, "DIS"), -1) << "lookup must not match a prefix";
  EXPECT_EQ(pvfrd_find_array(file, 0, "NOPE"), -1);
  EXPECT_EQ(pvfrd_find_array(file, 999, "DISP"), -1) << "an out-of-range step is absence";

  pvfrd_close(file);
}

TEST(ApiTest, PointersStayValidForTheLifeOfTheReader) {
  /* The header promises this, and a caller holding a pointer across other
   * calls is the normal way to use the ABI. Reading a step reallocates
   * internal storage, so this is not free. */
  pvfrd_file *file = nullptr;
  ASSERT_EQ(pvfrd_open(fixture("mesh.frd").c_str(), &file), PVFRD_OK);

  const double *points = pvfrd_points(file);
  const double first = points[0];

  for (uint64_t step = 0; step < pvfrd_n_steps(file); ++step) {
    uint64_t n = 0;
    ASSERT_EQ(pvfrd_n_arrays(file, step, &n), PVFRD_OK);
    for (uint64_t i = 0; i < n; ++i) {
      const double *data = nullptr;
      ASSERT_EQ(pvfrd_array_data(file, step, i, &data), PVFRD_OK);
      ASSERT_NE(data, nullptr);
    }
  }
  EXPECT_EQ(points, pvfrd_points(file));
  EXPECT_EQ(points[0], first);
  pvfrd_close(file);
}

TEST(ApiTest, RepeatedArrayReadsReturnTheSameBuffer) {
  /* Steps are materialised once. If they were rebuilt per call, a caller
   * holding an earlier pointer would be reading freed memory -- which the
   * sanitiser lane would catch, but only if something exercises it. */
  pvfrd_file *file = nullptr;
  ASSERT_EQ(pvfrd_open(fixture("mesh.frd").c_str(), &file), PVFRD_OK);

  const double *first = nullptr;
  const double *second = nullptr;
  ASSERT_EQ(pvfrd_array_data(file, 0, 0, &first), PVFRD_OK);
  ASSERT_EQ(pvfrd_array_data(file, 0, 0, &second), PVFRD_OK);
  EXPECT_EQ(first, second);
  pvfrd_close(file);
}

TEST(ApiTest, ConcurrentStepReadsAreSafe) {
  /* The header says several threads may read one reader. Materialisation is
   * the only mutation, so it is the only thing that has to be guarded --
   * this drives it from four threads at once, which is what the sanitiser
   * lane needs in order to have anything to find. */
  pvfrd_file *file = nullptr;
  ASSERT_EQ(pvfrd_open(fixture("mesh.frd").c_str(), &file), PVFRD_OK);
  const uint64_t n_steps = pvfrd_n_steps(file);
  ASSERT_GT(n_steps, 0u);

  std::vector<std::thread> workers;
  std::vector<int> failures(4, 0);
  for (int w = 0; w < 4; ++w) {
    workers.emplace_back([file, n_steps, &failures, w]() {
      for (int repeat = 0; repeat < 20; ++repeat) {
        for (uint64_t step = 0; step < n_steps; ++step) {
          uint64_t n = 0;
          if (pvfrd_n_arrays(file, step, &n) != PVFRD_OK) ++failures[w];
          const double *data = nullptr;
          if (n && pvfrd_array_data(file, step, 0, &data) != PVFRD_OK) ++failures[w];
        }
      }
    });
  }
  for (std::thread &worker : workers) worker.join();
  for (int count : failures) EXPECT_EQ(count, 0);
  pvfrd_close(file);
}

TEST(ApiTest, OpeningFromMemoryMatchesOpeningFromDisk) {
  const std::string path = fixture("mesh.frd");
  std::FILE *handle = std::fopen(path.c_str(), "rb");
  ASSERT_NE(handle, nullptr);
  std::string bytes;
  char chunk[4096];
  size_t got = 0;
  while ((got = std::fread(chunk, 1, sizeof(chunk), handle)) > 0) bytes.append(chunk, got);
  std::fclose(handle);

  pvfrd_file *from_disk = nullptr;
  pvfrd_file *from_memory = nullptr;
  ASSERT_EQ(pvfrd_open(path.c_str(), &from_disk), PVFRD_OK);
  ASSERT_EQ(pvfrd_open_memory(bytes.data(), bytes.size(), nullptr, &from_memory), PVFRD_OK);

  ASSERT_EQ(pvfrd_n_points(from_disk), pvfrd_n_points(from_memory));
  const double *a = pvfrd_points(from_disk);
  const double *b = pvfrd_points(from_memory);
  for (uint64_t i = 0; i < pvfrd_n_points(from_disk) * 3; ++i) EXPECT_EQ(a[i], b[i]);

  pvfrd_close(from_disk);
  pvfrd_close(from_memory);
}

TEST(ApiTest, TheCallerMayFreeTheBufferImmediately) {
  /* The header says the bytes are copied. If they were borrowed, this test
   * would read freed memory and the sanitiser lane would say so. */
  std::string *owned = new std::string("2C\n -1    1 1.0 2.0 3.0\n -3\n");
  pvfrd_file *file = nullptr;
  ASSERT_EQ(pvfrd_open_memory(owned->data(), owned->size(), nullptr, &file), PVFRD_OK);
  delete owned;

  ASSERT_EQ(pvfrd_n_points(file), 1u);
  EXPECT_DOUBLE_EQ(pvfrd_points(file)[0], 1.0);
  pvfrd_close(file);
}

TEST(ApiTest, CellOffsetsAlwaysHaveOneMoreEntryThanCells) {
  for (const char *name : kCorpus) {
    pvfrd_file *file = nullptr;
    ASSERT_EQ(pvfrd_open(fixture(name).c_str(), &file), PVFRD_OK) << name;
    const uint64_t n_cells = pvfrd_n_cells(file);
    const int64_t *offsets = pvfrd_cell_offsets(file);
    ASSERT_NE(offsets, nullptr) << name;
    EXPECT_EQ(offsets[0], 0) << name;
    for (uint64_t c = 0; c < n_cells; ++c) {
      EXPECT_LT(offsets[c], offsets[c + 1]) << name << " cell " << c;
    }
    pvfrd_close(file);
  }
}

TEST(ApiTest, PathsAreUtf8OnEveryPlatform) {
  /* The header promises UTF-8 paths everywhere. On Windows that is not what
   * fopen does with its bytes -- it reads them in the active code page, so a
   * path with anything outside ASCII opens the wrong file or none at all.
   *
   * This is written as a test rather than trusted because it is invisible
   * from a POSIX machine, where the bytes go through unchanged and any
   * implementation passes. Only the Windows lane can fail it. */
  const std::filesystem::path directory =
      std::filesystem::temp_directory_path() / "pvfrd-\xC3\xA9\xC3\xA7-test";
  std::error_code error;
  std::filesystem::create_directories(directory, error);
  ASSERT_FALSE(error) << error.message();

  const std::filesystem::path file = directory / "m\xC3\xA4sh.frd";
  {
    std::ofstream out(file, std::ios::binary);
    ASSERT_TRUE(out.is_open());
    out << "2C\n -1    1 1.0 2.0 3.0\n -3\n";
  }

  /* u8string(), not string(): on Windows the native path is UTF-16 and
   * string() would narrow it through the active code page -- reintroducing
   * the very bug this checks for, on the test's side. */
  /* In C++17 this returns a std::string; C++20 changed it to std::u8string,
   * which is why the result is not spelled with auto. */
  const std::string utf8 = file.u8string();
  pvfrd_file *opened = nullptr;
  ASSERT_EQ(pvfrd_open(utf8.c_str(), &opened), PVFRD_OK);
  EXPECT_EQ(pvfrd_n_points(opened), 1u);
  EXPECT_DOUBLE_EQ(pvfrd_points(opened)[1], 2.0);
  pvfrd_close(opened);

  std::filesystem::remove_all(directory, error);
}

TEST(ApiTest, StructSizesAreReportedForEveryStructThatCrossesTheBoundary) {
  /* Reported so a handwritten binding can check itself. The values are not
   * pinned to constants here on purpose: they legitimately differ between
   * 32- and 64-bit builds, and a constant would only record what one platform
   * happened to produce. What must hold is that the function agrees with the
   * compiler. */
  EXPECT_EQ(pvfrd_struct_size(PVFRD_STRUCT_OPEN_OPTIONS), sizeof(pvfrd_open_options));
  EXPECT_EQ(pvfrd_struct_size(PVFRD_STRUCT_ARRAY_INFO), sizeof(pvfrd_array_info));
  EXPECT_EQ(pvfrd_struct_size(PVFRD_STRUCT_DIAGNOSTIC), sizeof(pvfrd_diagnostic));

  /* An unknown id answers zero rather than a plausible size, so a newer
   * binding asking an older library about a struct it does not have gets a
   * mismatch it can report instead of a number it would trust. */
  EXPECT_EQ(pvfrd_struct_size(-1), 0u);
  EXPECT_EQ(pvfrd_struct_size(99), 0u);
}

TEST(ApiTest, StructFieldsAreWhereTheHeaderSaysTheyAre) {
  /* Sizes alone would not catch two fields of equal width swapped. These
   * offsets would, and they are what a binding in a language without ctypes'
   * layout rules has to reproduce by hand. */
  EXPECT_EQ(offsetof(pvfrd_array_info, name), 0u);
  EXPECT_LT(offsetof(pvfrd_array_info, n_tuples), offsetof(pvfrd_array_info, n_components));
  EXPECT_LT(offsetof(pvfrd_array_info, n_components), offsetof(pvfrd_array_info, kind));

  EXPECT_EQ(offsetof(pvfrd_diagnostic, kind), 0u);
  EXPECT_LT(offsetof(pvfrd_diagnostic, element_type), offsetof(pvfrd_diagnostic, line));
  EXPECT_LT(offsetof(pvfrd_diagnostic, line), offsetof(pvfrd_diagnostic, n_expected));
  EXPECT_LT(offsetof(pvfrd_diagnostic, n_expected), offsetof(pvfrd_diagnostic, n_actual));
}

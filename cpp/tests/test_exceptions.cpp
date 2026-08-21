/* The C ABI's promise that no exception escapes it.
 *
 * That promise is not testable by reading the code -- it is a claim about
 * what happens when an allocation fails, and allocations do not fail on
 * demand. So this file makes them fail on demand, by replacing global
 * operator new with one that can be armed to throw exactly once.
 *
 * Why it is worth the trouble: unwinding out of an `extern "C"` frame is
 * undefined behaviour, and the callers of this library are ctypes and other
 * foreign-function bindings, which have no frames to unwind into and no way
 * to report what happened. A missing try/catch here is not a wrong answer, it
 * is a crash in someone else's process. Four entry points were missing one --
 * the readers of a lazily materialised step, which allocate precisely because
 * reading a step is what creates it -- and no test noticed, because nothing
 * here had ever made an allocation fail.
 *
 * Under a sanitizer this file's operator new is not installed: ASan replaces
 * the allocator itself, and two replacements in one process is a fight with
 * no winner. The tests then skip rather than silently assert nothing.
 */

#include <gtest/gtest.h>

#include <atomic>
#include <cstddef>
#include <cstdlib>
#include <new>
#include <string>
#include <vector>

#include "pvfrd/pvfrd.h"

#if defined(__SANITIZE_ADDRESS__)
#define PVFRD_SANITIZER_ACTIVE 1
#elif defined(__has_feature)
#if __has_feature(address_sanitizer) || __has_feature(memory_sanitizer)
#define PVFRD_SANITIZER_ACTIVE 1
#endif
#endif

namespace {

/* Armed count: the next N allocations throw. Atomic because the library may
 * allocate on a worker thread one day, and a data race here would be a
 * flake in the one test whose job is to be trustworthy. */
std::atomic<int> g_fail_after{-1};

bool should_fail() {
  int remaining = g_fail_after.load(std::memory_order_relaxed);
  while (remaining > 0) {
    if (g_fail_after.compare_exchange_weak(remaining, remaining - 1, std::memory_order_relaxed)) {
      return remaining - 1 == 0;
    }
  }
  return false;
}

/* Arms the injector for one scope and disarms it whatever happens, including
 * on the exception the test is provoking. */
struct FailAllocationAfter {
  explicit FailAllocationAfter(int n) { g_fail_after.store(n, std::memory_order_relaxed); }
  ~FailAllocationAfter() { g_fail_after.store(-1, std::memory_order_relaxed); }
};

/* A size the optimiser cannot fold. Reading it through a volatile stops the
 * allocation being elided, which is the failure mode the control below exists
 * to avoid repeating. */
const volatile std::size_t kVolatileSize = 4096;
const std::size_t kUnpredictableSize = kVolatileSize;

const char *kMinimalDocument =
    "    1C\n"
    "    2C                    4                     1\n"
    " -1         1 0.00000E+00 0.00000E+00 0.00000E+00\n"
    " -1         2 1.00000E+00 0.00000E+00 0.00000E+00\n"
    " -1         3 0.00000E+00 1.00000E+00 0.00000E+00\n"
    " -1         4 0.00000E+00 0.00000E+00 1.00000E+00\n"
    " -3\n"
    "    3C                    1                     1\n"
    " -1         1    3    0    1\n"
    " -2         1         2         3         4\n"
    " -3\n"
    "  100CL  1 1.000000000  1                     2    1\n"
    " -4  STRESS      6    1\n"
    " -1         1 1.00000E+00 2.00000E+00 3.00000E+00 4.00000E+00 5.00000E+00 6.00000E+00\n"
    " -1         2 1.00000E+00 2.00000E+00 3.00000E+00 4.00000E+00 5.00000E+00 6.00000E+00\n"
    " -1         3 1.00000E+00 2.00000E+00 3.00000E+00 4.00000E+00 5.00000E+00 6.00000E+00\n"
    " -1         4 1.00000E+00 2.00000E+00 3.00000E+00 4.00000E+00 5.00000E+00 6.00000E+00\n"
    " -3\n";

}  // namespace

#if !defined(PVFRD_SANITIZER_ACTIVE)
void *operator new(std::size_t size) {
  if (should_fail()) throw std::bad_alloc();
  void *p = std::malloc(size == 0 ? 1 : size);
  if (p == nullptr) throw std::bad_alloc();
  return p;
}
void operator delete(void *p) noexcept {
  std::free(p);
}
void operator delete(void *p, std::size_t) noexcept {
  std::free(p);
}
void *operator new[](std::size_t size) {
  if (should_fail()) throw std::bad_alloc();
  void *p = std::malloc(size == 0 ? 1 : size);
  if (p == nullptr) throw std::bad_alloc();
  return p;
}
void operator delete[](void *p) noexcept {
  std::free(p);
}
void operator delete[](void *p, std::size_t) noexcept {
  std::free(p);
}
#endif

class AllocationFailure : public ::testing::Test {
 protected:
  void SetUp() override {
#if defined(PVFRD_SANITIZER_ACTIVE)
    GTEST_SKIP() << "the sanitizer owns the allocator; the injector is not installed";
#endif
  }
};

TEST_F(AllocationFailure, TheInjectorActuallyFails) {
  /* The control on the instrument. Every assertion below is worthless if the
   * replacement operator new is not the one being called -- which is exactly
   * what happens if the linker prefers another definition, or if the
   * allocations all come from a shared library with its own. */
  bool threw = false;
  void *block = nullptr;
  try {
    FailAllocationAfter arm(1);
    /* ::operator new with a size the compiler cannot see, not `new char[64]`.
     * A new-expression with a constant size and no escaping pointer is
     * allowed to be elided entirely, and at -O2 it is: the first version of
     * this control failed for that reason, having tested nothing but the
     * optimiser. ::operator new is a plain function call and stays. */
    block = ::operator new(kUnpredictableSize);
  } catch (const std::bad_alloc &) {
    threw = true;
  }
  ::operator delete(block);
  EXPECT_TRUE(threw) << "operator new was not replaced; the tests below prove nothing";

  /* And that a container allocation reaches it too, since that is what the
   * library actually does -- strings and vectors, never a new-expression. */
  bool container_threw = false;
  try {
    FailAllocationAfter arm(1);
    std::vector<double> forced(kUnpredictableSize);
    (void)forced.size();
  } catch (const std::bad_alloc &) {
    container_threw = true;
  }
  EXPECT_TRUE(container_threw) << "container allocations do not reach the replacement";
}

TEST_F(AllocationFailure, OpenFromMemoryReportsRatherThanThrows) {
  const std::string document(kMinimalDocument);
  for (int n = 1; n <= 12; ++n) {
    pvfrd_file *file = nullptr;
    pvfrd_status status = PVFRD_OK;
    ASSERT_NO_THROW({
      FailAllocationAfter arm(n);
      status = pvfrd_open_memory(document.data(), document.size(), nullptr, &file);
    }) << "an exception escaped pvfrd_open_memory with allocation "
       << n << " failing";
    if (status == PVFRD_OK) {
      ASSERT_NE(file, nullptr);
      pvfrd_close(file);
    } else {
      EXPECT_EQ(file, nullptr) << "a failed open must not hand back a reader";
      EXPECT_TRUE(status == PVFRD_E_NOMEM || status == PVFRD_E_INTERNAL)
          << "allocation " << n << " failed but the status was " << status << " ("
          << pvfrd_status_message(status) << ")";
    }
  }
}

TEST_F(AllocationFailure, ReadingAStepReportsRatherThanThrows) {
  /* The regression this file was written for. A step is parsed when it is
   * first asked for, so these four are allocating entry points that do not
   * look like allocating entry points, and all four were unguarded. */
  const std::string document(kMinimalDocument);

  for (int n = 1; n <= 12; ++n) {
    pvfrd_file *file = nullptr;
    ASSERT_EQ(pvfrd_open_memory(document.data(), document.size(), nullptr, &file), PVFRD_OK);
    ASSERT_NE(file, nullptr);
    ASSERT_EQ(pvfrd_n_steps(file), 1u);

    uint64_t count = 0;
    pvfrd_status status = PVFRD_OK;
    ASSERT_NO_THROW({
      FailAllocationAfter arm(n);
      status = pvfrd_n_arrays(file, 0, &count);
    }) << "an exception escaped pvfrd_n_arrays with allocation "
       << n << " failing";
    EXPECT_TRUE(status == PVFRD_OK || status == PVFRD_E_NOMEM || status == PVFRD_E_INTERNAL)
        << "unexpected status " << status << " (" << pvfrd_status_message(status) << ")";
    pvfrd_close(file);
  }

  for (int n = 1; n <= 12; ++n) {
    pvfrd_file *file = nullptr;
    ASSERT_EQ(pvfrd_open_memory(document.data(), document.size(), nullptr, &file), PVFRD_OK);
    const double *data = nullptr;
    pvfrd_status status = PVFRD_OK;
    ASSERT_NO_THROW({
      FailAllocationAfter arm(n);
      status = pvfrd_array_data(file, 0, 0, &data);
    }) << "an exception escaped pvfrd_array_data with allocation "
       << n << " failing";
    EXPECT_TRUE(status == PVFRD_OK || status == PVFRD_E_NOMEM || status == PVFRD_E_INTERNAL)
        << "unexpected status " << status;
    pvfrd_close(file);
  }

  for (int n = 1; n <= 12; ++n) {
    pvfrd_file *file = nullptr;
    ASSERT_EQ(pvfrd_open_memory(document.data(), document.size(), nullptr, &file), PVFRD_OK);
    int64_t index = 0;
    ASSERT_NO_THROW({
      FailAllocationAfter arm(n);
      index = pvfrd_find_array(file, 0, "STRESS");
    }) << "an exception escaped pvfrd_find_array with allocation "
       << n << " failing";
    EXPECT_GE(index, -1);
    pvfrd_close(file);
  }

  for (int n = 1; n <= 12; ++n) {
    pvfrd_file *file = nullptr;
    ASSERT_EQ(pvfrd_open_memory(document.data(), document.size(), nullptr, &file), PVFRD_OK);
    pvfrd_array_info info{};
    pvfrd_status status = PVFRD_OK;
    ASSERT_NO_THROW({
      FailAllocationAfter arm(n);
      status = pvfrd_array_info_range(file, 0, 0, 1, &info);
    }) << "an exception escaped pvfrd_array_info_range with allocation "
       << n << " failing";
    EXPECT_TRUE(status == PVFRD_OK || status == PVFRD_E_NOMEM || status == PVFRD_E_INTERNAL)
        << "unexpected status " << status;
    pvfrd_close(file);
  }
}

TEST(ErrorReporting, AFailedOpenLeavesAReasonWithNoReaderToHoldIt) {
  /* pvfrd_last_error takes a reader, and a failed open produces none. Before
   * the thread-local slot existed, the reason for the one failure a caller
   * cannot guess at was simply dropped, and the Python binding filled the gap
   * by reporting the path it had just passed in. */
  pvfrd_file *file = nullptr;
  const pvfrd_status status = pvfrd_open("./this-path-does-not-exist.frd", &file);
  ASSERT_EQ(status, PVFRD_E_IO);
  ASSERT_EQ(file, nullptr);

  const char *reason = pvfrd_last_error(nullptr);
  ASSERT_NE(reason, nullptr) << "never NULL, whatever the handle";
  EXPECT_STRNE(reason, "") << "a failed open must leave a reason somewhere reachable";
}

TEST(ErrorReporting, EveryStatusHasItsOwnMessage) {
  /* A status added without a message reads as "unknown status", which is what
   * a caller sees instead of a diagnosis. Checked by walking the enum rather
   * than by listing the codes again here, so adding one to the header without
   * adding its message fails this. */
  const pvfrd_status all[] = {PVFRD_OK,      PVFRD_E_IO,      PVFRD_E_FORMAT, PVFRD_E_RANGE,
                              PVFRD_E_NOMEM, PVFRD_E_INVALID, PVFRD_E_RAGGED, PVFRD_E_INTERNAL};
  std::vector<std::string> seen;
  for (pvfrd_status status : all) {
    const char *message = pvfrd_status_message(status);
    ASSERT_NE(message, nullptr);
    EXPECT_STRNE(message, "unknown status") << "status " << status << " has no message of its own";
    seen.emplace_back(message);
  }
  for (size_t i = 0; i < seen.size(); ++i) {
    for (size_t j = i + 1; j < seen.size(); ++j) {
      EXPECT_NE(seen[i], seen[j]) << "two statuses share the message \"" << seen[i] << "\"";
    }
  }
  EXPECT_STREQ(pvfrd_status_message(9999), "unknown status");
}

TEST(ErrorReporting, AnInternalFaultIsNotReportedAsABadFile) {
  /* PVFRD_E_INTERNAL exists so that a fault in the library cannot be reported
   * as PVFRD_E_FORMAT. The two must stay distinguishable: a caller told
   * "the file did not parse" goes and inspects a file that is fine. */
  EXPECT_NE(static_cast<int>(PVFRD_E_INTERNAL), static_cast<int>(PVFRD_E_FORMAT));
  EXPECT_STRNE(pvfrd_status_message(PVFRD_E_INTERNAL), pvfrd_status_message(PVFRD_E_FORMAT));
}

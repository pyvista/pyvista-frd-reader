/* Feed files to the fuzz entry point without libFuzzer.
 *
 * The fuzzer itself needs Clang, which not every developer or lane has. This
 * driver runs the same LLVMFuzzerTestOneInput over the committed corpus under
 * whatever compiler is to hand -- and, in the sanitizer lane, under ASan and
 * UBSan.
 *
 * Without it, the checks inside the fuzz target would be code that only ever
 * runs in one job on one platform, which is a capability claim rather than a
 * checked one.
 */

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

namespace {

bool read_file(const char *path, std::string *out) {
  std::FILE *handle = std::fopen(path, "rb");
  if (handle == nullptr) return false;
  char chunk[4096];
  size_t got = 0;
  while ((got = std::fread(chunk, 1, sizeof(chunk), handle)) > 0) out->append(chunk, got);
  std::fclose(handle);
  return true;
}

}  // namespace

int main(int argc, char **argv) {
  if (argc < 2) {
    std::fprintf(stderr, "usage: %s FILE...\n", argv[0]);
    return 2;
  }
  for (int i = 1; i < argc; ++i) {
    std::string bytes;
    if (!read_file(argv[i], &bytes)) {
      std::fprintf(stderr, "%s: unreadable\n", argv[i]);
      return 1;
    }
    /* The whole file, then every truncation down to nothing at a coarse
     * stride. Truncation is the cheapest source of malformed input there is,
     * and it is exactly what a partially written result file looks like. */
    LLVMFuzzerTestOneInput(reinterpret_cast<const uint8_t *>(bytes.data()), bytes.size());
    const size_t stride = bytes.size() > 4096 ? bytes.size() / 64 : 7;
    for (size_t cut = 0; cut < bytes.size(); cut += stride) {
      LLVMFuzzerTestOneInput(reinterpret_cast<const uint8_t *>(bytes.data()), cut);
    }
    std::printf("ok %s (%zu bytes)\n", argv[i], bytes.size());
  }
  return 0;
}

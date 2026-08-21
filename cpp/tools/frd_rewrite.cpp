/* Read an FRD document and write it out again.
 *
 * With no format argument this is the byte-match gate: the output of a
 * document read and re-emitted must be the input, byte for byte, over files
 * this project did not write. That is a real check on the writer in a way a
 * round-trip through our own reader is not -- the comparison is against
 * CalculiX's bytes, not against our own idea of them.
 *
 *   frd_rewrite IN [OUT] [--format N]
 *
 * With a format argument it is the conversion the format has always implied
 * and no tool offered: 0 and 1 are the ASCII widths, 2 and 3 the binary ones.
 * A binary FRD that no ASCII-only reader can open becomes one that any of
 * them can, and an ASCII one becomes about a third of the size.
 */

#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

#include "document.h"

int main(int argc, char **argv) {
  const char *in_path = nullptr;
  const char *out_path = nullptr;
  int format = -1;

  for (int i = 1; i < argc; ++i) {
    if (std::strcmp(argv[i], "--format") == 0 && i + 1 < argc) {
      format = std::atoi(argv[++i]);
    } else if (in_path == nullptr) {
      in_path = argv[i];
    } else {
      out_path = argv[i];
    }
  }
  if (in_path == nullptr) {
    std::cerr << "usage: frd_rewrite IN [OUT] [--format 0|1|2|3]\n";
    return 2;
  }

  std::ifstream input(in_path, std::ios::binary);
  if (!input) {
    std::cerr << "cannot open " << in_path << "\n";
    return 2;
  }
  std::ostringstream buffer;
  buffer << input.rdbuf();
  const std::string text = buffer.str();

  pvfrd::RawDocument document;
  std::string error;
  const pvfrd_status status = pvfrd::parse_raw(text, &document, &error);
  if (status != PVFRD_OK) {
    std::cerr << "cannot read " << in_path << ": " << error << "\n";
    return 1;
  }

  const std::string emitted = pvfrd::emit_raw(document, format);

  if (out_path == nullptr) {
    /* Byte-match mode: say whether it round-tripped and, if not, where. */
    if (emitted == text) {
      std::cout << "identical " << text.size() << "\n";
      return 0;
    }
    size_t at = 0;
    while (at < emitted.size() && at < text.size() && emitted[at] == text[at]) ++at;
    size_t line = 1;
    for (size_t i = 0; i < at && i < text.size(); ++i) {
      if (text[i] == '\n') ++line;
    }
    std::cout << "differs at byte " << at << " line " << line << " (in " << text.size() << ", out "
              << emitted.size() << ")\n";
    auto excerpt = [](const std::string &s, size_t from) {
      size_t begin = from;
      while (begin > 0 && s[begin - 1] != '\n') --begin;
      size_t end = from;
      while (end < s.size() && s[end] != '\n') ++end;
      return s.substr(begin, end - begin);
    };
    std::cout << "  file   |" << excerpt(text, at) << "|\n";
    std::cout << "  writer |" << excerpt(emitted, at) << "|\n";
    return 1;
  }

  std::ofstream output(out_path, std::ios::binary);
  if (!output) {
    std::cerr << "cannot write " << out_path << "\n";
    return 2;
  }
  output.write(emitted.data(), static_cast<std::streamsize>(emitted.size()));
  return output ? 0 : 2;
}

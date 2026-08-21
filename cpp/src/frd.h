/* Internal types behind the C ABI. Nothing here crosses the boundary. */

#ifndef PVFRD_FRD_H
#define PVFRD_FRD_H

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

#include "pvfrd/pvfrd.h"

namespace pvfrd {

/* Where a result block's data lives, so a step can be parsed on demand.
 *
 * The alternative -- parsing every value at open -- is what the reference
 * reader does, and it is why reading one time step of a many-step file costs
 * the whole file there. Recording the byte range costs one pass with no
 * number parsing in it. */
struct BlockRef {
  std::string name;
  size_t data_begin = 0;  /* offset of the block's first record */
  size_t data_end = 0;    /* offset just past the last record of the run */
  int64_t first_line = 0; /* line number of data_begin, for error messages */

  /* Binary blocks carry their shape here because it cannot be recovered from
   * the payload. A text record says how many values it has by how many fields
   * it has; a binary record is an undelimited run of bytes, and the only
   * statement of its width is the block header that has already gone past by
   * the time the values are read. */
  int format = 1;            /* 0/1 ASCII, 2 binary float, 3 binary double */
  uint32_t n_components = 0; /* stored components per record, binary only */
};

struct StepRef {
  double time = 0.0;
  std::vector<BlockRef> blocks;
};

struct Array {
  std::string name;
  uint32_t n_components = 0;
  int32_t kind = PVFRD_ARRAY_RAW;
  std::vector<double> data; /* n_points * n_components */
};

struct MaterialisedStep {
  bool done = false;
  pvfrd_status status = PVFRD_OK;
  std::string error;
  std::vector<Array> arrays;
  std::unordered_map<std::string, uint64_t> by_name;
};

class Document {
 public:
  Document(std::string buffer, pvfrd_open_options options);

  pvfrd_status parse();

  /* Mesh */
  uint64_t n_points() const { return static_cast<uint64_t>(node_ids_.size()); }
  const double *points() const { return points_.data(); }
  const int64_t *node_ids() const { return node_ids_.data(); }
  uint64_t n_cells() const { return static_cast<uint64_t>(cell_types_.size()); }
  const uint8_t *cell_types() const { return cell_types_.data(); }
  const int64_t *cell_offsets() const { return cell_offsets_.data(); }
  const int64_t *cell_connectivity() const { return connectivity_.data(); }

  /* Diagnostics */
  const std::vector<pvfrd_diagnostic> &diagnostics() const { return diagnostics_; }

  /* Steps */
  uint64_t n_steps() const { return static_cast<uint64_t>(steps_.size()); }
  double step_time(uint64_t step) const { return steps_[step].time; }

  /* Materialises `step` on first use. Returns nullptr and sets the reader's
   * last error when the step cannot be built. */
  const MaterialisedStep *step_arrays(uint64_t step) const;

  /* How many times a step's values have been parsed. See pvfrd_steps_parsed
   * in the public header for why this is visible. */
  uint64_t steps_parsed() const { return steps_parsed_.load(); }

  const std::string &last_error() const { return last_error_; }
  void set_last_error(std::string message) const { last_error_ = std::move(message); }

 private:
  void index_results(class LineReader &reader, StepRef *step, int64_t declared_records, int format);
  void parse_nodes(class LineReader &reader);
  bool parse_nodes_binary(class LineReader &reader, int64_t count, int format);
  bool parse_elements_binary(class LineReader &reader, int64_t count, int format);
  void parse_elements(class LineReader &reader);
  void build_mesh();
  void materialise(uint64_t step, MaterialisedStep *out) const;

  std::string buffer_;
  pvfrd_open_options options_;

  /* Raw parse products, before node ids are collapsed to indices. */
  std::vector<int64_t> raw_node_ids_;                 /* insertion order */
  std::vector<double> raw_node_xyz_;                  /* 3 per entry */
  std::unordered_map<int64_t, size_t> raw_node_slot_; /* id -> slot, for overwrite */
  std::vector<std::vector<int64_t>> raw_cells_;
  std::vector<uint8_t> raw_cell_types_;

  /* Decided once, by the first element-face line in the file, and then fixed
   * for every element after it. Held on the document rather than passed
   * around because the reference reader stores it on the parse result and
   * the two must go stale at the same moments. */
  bool is_long_format_ = false;
  bool format_detected_ = false;

  /* Mesh */
  std::vector<int64_t> node_ids_; /* ascending */
  std::vector<double> points_;
  std::unordered_map<int64_t, int64_t> node_index_;
  std::vector<uint8_t> cell_types_;
  std::vector<int64_t> cell_offsets_;
  std::vector<int64_t> connectivity_;

  std::vector<pvfrd_diagnostic> diagnostics_;

  std::vector<StepRef> steps_;
  std::map<double, size_t> step_index_; /* time -> index into steps_ */

  mutable std::vector<std::unique_ptr<MaterialisedStep>> materialised_;
  mutable std::mutex materialise_mutex_;
  /* Counts parses, not parsed steps: a re-parse has to be visible, and it
   * would not be if this were derived from how many slots are filled. */
  mutable std::atomic<uint64_t> steps_parsed_{0};
  mutable std::string last_error_;
};

/* Derived tensor quantities, shared with the gtest suite.
 *
 * `tensor` is n * 6, in CalculiX order (xx, yy, zz, xy, yz, zx). Each output
 * is n long. The expression order matches the reference implementation's
 * NumPy expression exactly, which is what makes the values bit-identical
 * rather than merely close -- see doc/divergences.md on why the principal
 * stresses are the one exception. */
void von_mises_stress(const double *tensor, size_t n, double *mises, double *signed_mises);
void von_mises_strain(const double *tensor, size_t n, double *mises, double *signed_mises);

/* Ascending eigenvalues of the symmetric 3x3 built from one tensor row. */
void principal_values(const double *tensor_row, double *ps3, double *ps2, double *ps1);

}  // namespace pvfrd

#endif  // PVFRD_FRD_H

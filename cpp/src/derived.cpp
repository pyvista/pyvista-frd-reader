/* Quantities derived from a 6-component tensor: equivalent stress/strain and
 * the principal values.
 *
 * Two different standards of agreement apply here, and the difference is not
 * cosmetic:
 *
 *   von Mises   a closed-form expression. Written in the same association
 *               order as the reference implementation's NumPy expression, and
 *               compiled with floating-point contraction off, it is
 *               bit-identical. The conformance suite asserts equality, not a
 *               tolerance, and that assertion is what would catch a
 *               well-meaning "simplification" of the expression below.
 *
 *   principals  eigenvalues of a symmetric 3x3. The reference gets these from
 *               LAPACK. Reproducing LAPACK's last bit is not a goal that can
 *               be met, so this uses cyclic Jacobi -- which is backward
 *               stable and, for a 3x3, converges in a handful of sweeps -- and
 *               the conformance suite states a relative tolerance instead.
 *               doc/divergences.md records the measured band.
 */

#include <algorithm>
#include <cmath>
#include <cstddef>

#include "frd.h"

namespace pvfrd {
namespace {

/* The reference writes `x**2`, which NumPy evaluates as a multiplication.
 * Spelled out so no one is tempted to reach for std::pow, which is not
 * required to be correctly rounded and would break the equality assertion. */
inline double sq(double x) {
  return x * x;
}

/* The shared half of both equivalents. Kept in one place so the stress and
 * strain forms cannot drift apart in their association order, which is the
 * only thing making either of them reproducible. */
inline double deviatoric_sum(const double *t) {
  const double xx = t[0], yy = t[1], zz = t[2];
  const double xy = t[3], yz = t[4], zx = t[5];
  return sq(xx - yy) + sq(yy - zz) + sq(zz - xx) + 6.0 * (sq(xy) + sq(yz) + sq(zx));
}

/* NumPy's np.sign for a finite non-zero double. */
inline double sign_of(double x) {
  return x > 0.0 ? 1.0 : (x < 0.0 ? -1.0 : 0.0);
}

}  // namespace

void von_mises_stress(const double *tensor, size_t n, double *mises, double *signed_mises) {
  for (size_t i = 0; i < n; ++i) {
    const double *t = tensor + i * 6;
    const double value = std::sqrt(0.5 * deviatoric_sum(t));
    mises[i] = value;
    const double trace = t[0] + t[1] + t[2];
    /* `np.where(trace != 0, np.sign(trace) * vmises, vmises)`: an exactly
     * zero trace keeps the unsigned magnitude rather than being multiplied
     * by a zero sign. */
    signed_mises[i] = (trace != 0.0) ? sign_of(trace) * value : value;
  }
}

void von_mises_strain(const double *tensor, size_t n, double *mises, double *signed_mises) {
  /* sqrt(2)/3 computed once, as the reference does, and applied after the
   * square root rather than folded into the sum. */
  const double k = std::sqrt(2.0) / 3.0;
  for (size_t i = 0; i < n; ++i) {
    const double *t = tensor + i * 6;
    const double value = k * std::sqrt(deviatoric_sum(t));
    mises[i] = value;
    const double volumetric = t[0] + t[1] + t[2];
    signed_mises[i] = (volumetric != 0.0) ? sign_of(volumetric) * value : value;
  }
}

void principal_values(const double *t, double *ps3, double *ps2, double *ps1) {
  /* Symmetric matrix from the CalculiX ordering (xx, yy, zz, xy, yz, zx). */
  double a[3][3] = {{t[0], t[3], t[5]}, {t[3], t[1], t[4]}, {t[5], t[4], t[2]}};

  /* Cyclic Jacobi. Twelve sweeps is far more than a 3x3 ever needs -- it
   * converges quadratically and in practice finishes in four -- but the bound
   * is here so a pathological input cannot spin.
   *
   * Both thresholds below are scaled by the matrix, not fixed. An earlier
   * version stopped on `off == 0.0` and skipped rotations below 1e-300, which
   * are conditions the off-diagonals reach only by luck: measured over a
   * million random tensors, 21% of them ran all twelve sweeps and the mean
   * was 6.9. The extra sweeps were rotations through angles too small to
   * change a diagonal entry in floating point -- work whose result was
   * discarded by rounding.
   *
   * Replacing them with the textbook criteria is worth 1.65x on this function
   * and about 14% of a whole read, and it is not a trade: the outputs are
   * bit-identical to the previous implementation on a million random tensors
   * and on the degenerate, denormal, infinite and NaN cases pinned in
   * PrincipalValuesTest. Nothing here is an approximation that was loosened. */
  static const double eps = 2.220446049250313e-16; /* DBL_EPSILON */

  for (int sweep = 0; sweep < 12; ++sweep) {
    const double off = std::fabs(a[0][1]) + std::fabs(a[0][2]) + std::fabs(a[1][2]);
    const double diag = std::fabs(a[0][0]) + std::fabs(a[1][1]) + std::fabs(a[2][2]);
    /* Converged: the off-diagonal mass can no longer move a diagonal entry.
     * Written `<=` so an all-zero matrix stops on the first look. */
    if (off <= eps * diag) break;

    for (int p = 0; p < 2; ++p) {
      for (int q = p + 1; q < 3; ++q) {
        if (a[p][q] == 0.0) continue;
        /* Skip a rotation that cannot change the matrix: when the
         * off-diagonal is negligible against both diagonals, the update
         * would be a no-op in floating point and the angle is ill
         * conditioned. */
        const double scale = std::fabs(a[p][p]) + std::fabs(a[q][q]);
        if (std::fabs(a[p][q]) <= scale * eps) continue;

        const double theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q]);
        const double t_rot =
            (theta >= 0.0 ? 1.0 : -1.0) / (std::fabs(theta) + std::sqrt(theta * theta + 1.0));
        const double c = 1.0 / std::sqrt(t_rot * t_rot + 1.0);
        const double s = t_rot * c;

        const double app = a[p][p];
        const double aqq = a[q][q];
        const double apq = a[p][q];
        a[p][p] = app - t_rot * apq;
        a[q][q] = aqq + t_rot * apq;
        a[p][q] = 0.0;
        a[q][p] = 0.0;

        const int r = 3 - p - q; /* the index touched by neither rotation */
        const double arp = a[r][p];
        const double arq = a[r][q];
        a[r][p] = c * arp - s * arq;
        a[p][r] = a[r][p];
        a[r][q] = s * arp + c * arq;
        a[q][r] = a[r][q];
      }
    }
  }

  double e[3] = {a[0][0], a[1][1], a[2][2]};
  std::sort(e, e + 3);
  /* Ascending, matching np.linalg.eigvalsh: PS3 is the smallest principal
   * value and PS1 the largest, which is the convention CalculiX GraphiX
   * uses and the reference reader follows. */
  *ps3 = e[0];
  *ps2 = e[1];
  *ps1 = e[2];
}

}  // namespace pvfrd

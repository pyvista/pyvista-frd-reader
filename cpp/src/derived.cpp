/* Quantities derived from a 6-component tensor. Two standards of agreement
 * apply, and the difference is not cosmetic:
 *
 *   von Mises   closed form, in the reference's NumPy association order and
 *               with contraction off, so it is bit-identical. The conformance
 *               suite asserts equality, which is what catches a well-meaning
 *               "simplification" of the expression below.
 *   principals  eigenvalues of a symmetric 3x3, which the reference takes
 *               from LAPACK. Matching LAPACK's last bit is not achievable, so
 *               this is cyclic Jacobi against a relative tolerance;
 *               doc/divergences.md records the measured band. */

#include <algorithm>
#include <cmath>
#include <cstddef>

#include "frd.h"

namespace pvfrd {
namespace {

/* Not std::pow, which is not required to be correctly rounded. */
inline double sq(double x) {
  return x * x;
}

/* Shared, so the stress and strain forms cannot drift apart in association
 * order -- the only thing making either reproducible. */
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
    /* `np.where(trace != 0, np.sign(trace) * vmises, vmises)`. */
    signed_mises[i] = (trace != 0.0) ? sign_of(trace) * value : value;
  }
}

void von_mises_strain(const double *tensor, size_t n, double *mises, double *signed_mises) {
  /* Once, and after the square root, as the reference does. */
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

  /* Cyclic Jacobi; a 3x3 finishes in about four sweeps, and the bound stops a
   * pathological input spinning. Both thresholds below are scaled by the
   * matrix. An earlier version stopped on `off == 0.0` and skipped rotations
   * below 1e-300, conditions the off-diagonals reach only by luck: 21% of a
   * million random tensors ran all twelve sweeps, rotating through angles too
   * small to move a diagonal entry. The textbook criteria are worth 1.65x
   * here and 14% of a read, at no accuracy cost -- outputs are bit-identical
   * over that million and over the degenerate, denormal, infinite and NaN
   * cases pinned in PrincipalValuesTest. */
  static const double eps = 2.220446049250313e-16; /* DBL_EPSILON */

  for (int sweep = 0; sweep < 12; ++sweep) {
    const double off = std::fabs(a[0][1]) + std::fabs(a[0][2]) + std::fabs(a[1][2]);
    const double diag = std::fabs(a[0][0]) + std::fabs(a[1][1]) + std::fabs(a[2][2]);
    /* `<=` so an all-zero matrix stops on the first look. */
    if (off <= eps * diag) break;

    for (int p = 0; p < 2; ++p) {
      for (int q = p + 1; q < 3; ++q) {
        if (a[p][q] == 0.0) continue;
        /* A no-op in floating point, and an ill-conditioned angle. */
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
  /* Ascending, as np.linalg.eigvalsh and CalculiX GraphiX have it. */
  *ps3 = e[0];
  *ps2 = e[1];
  *ps1 = e[2];
}

}  // namespace pvfrd

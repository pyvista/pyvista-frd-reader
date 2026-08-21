/* Derived tensor quantities, against values worked out by hand.
 *
 * The Python conformance suite already checks these against PyVista. That
 * check is necessary and not sufficient: PyVista's formulas and these could
 * both be wrong in the same way and would still agree. The expectations here
 * come from the definitions, not from either implementation, so they are the
 * half of the evidence that does not depend on the incumbent.
 */

#include <gtest/gtest.h>

#include <cmath>
#include <vector>

#include "frd.h"

using namespace pvfrd;

namespace {

/* Tensor rows in CalculiX order: xx, yy, zz, xy, yz, zx. */
std::vector<double> row(double xx, double yy, double zz, double xy, double yz, double zx) {
  return {xx, yy, zz, xy, yz, zx};
}

}  // namespace

TEST(DerivedTest, UniaxialStressGivesTheAppliedStress) {
  /* One-dimensional tension: the von Mises equivalent is the applied stress
   * itself. If the 0.5 factor or the shear weighting is wrong, this is the
   * first thing that moves. */
  const std::vector<double> t = row(100.0, 0.0, 0.0, 0.0, 0.0, 0.0);
  double mises = 0.0;
  double signed_mises = 0.0;
  von_mises_stress(t.data(), 1, &mises, &signed_mises);
  EXPECT_DOUBLE_EQ(mises, 100.0);
  EXPECT_DOUBLE_EQ(signed_mises, 100.0);
}

TEST(DerivedTest, PureShearGivesSqrtThreeTimesTheShear) {
  /* Pure shear of magnitude tau has a von Mises equivalent of sqrt(3)*tau.
   * This is the case that catches a wrong factor on the shear terms, which
   * uniaxial tension cannot see. */
  const std::vector<double> t = row(0.0, 0.0, 0.0, 50.0, 0.0, 0.0);
  double mises = 0.0;
  double signed_mises = 0.0;
  von_mises_stress(t.data(), 1, &mises, &signed_mises);
  EXPECT_NEAR(mises, std::sqrt(3.0) * 50.0, 1e-12);
}

TEST(DerivedTest, HydrostaticStressHasZeroEquivalent) {
  const std::vector<double> t = row(70.0, 70.0, 70.0, 0.0, 0.0, 0.0);
  double mises = 0.0;
  double signed_mises = 0.0;
  von_mises_stress(t.data(), 1, &mises, &signed_mises);
  EXPECT_DOUBLE_EQ(mises, 0.0);
  /* Trace is positive, so the signed form keeps a positive zero. */
  EXPECT_DOUBLE_EQ(signed_mises, 0.0);
}

TEST(DerivedTest, SignedMisesFollowsTheTrace) {
  double mises = 0.0;
  double signed_mises = 0.0;

  const std::vector<double> tension = row(10.0, 20.0, 30.0, 0.0, 0.0, 0.0);
  von_mises_stress(tension.data(), 1, &mises, &signed_mises);
  EXPECT_GT(signed_mises, 0.0);
  EXPECT_DOUBLE_EQ(signed_mises, mises);

  const std::vector<double> compression = row(-10.0, -20.0, -30.0, 0.0, 0.0, 0.0);
  von_mises_stress(compression.data(), 1, &mises, &signed_mises);
  EXPECT_LT(signed_mises, 0.0);
  EXPECT_DOUBLE_EQ(signed_mises, -mises);
}

TEST(DerivedTest, ZeroTraceKeepsTheUnsignedMagnitude) {
  /* np.where(trace != 0, sign(trace) * v, v): an exactly traceless state
   * keeps the magnitude rather than being multiplied by a zero sign. A
   * reimplementation that just multiplies by sign(trace) returns zero here
   * for every deviatoric state in the file, which is a large and silent
   * difference. */
  const std::vector<double> t = row(10.0, -10.0, 0.0, 0.0, 0.0, 0.0);
  double mises = 0.0;
  double signed_mises = 0.0;
  von_mises_stress(t.data(), 1, &mises, &signed_mises);
  EXPECT_GT(mises, 0.0);
  EXPECT_DOUBLE_EQ(signed_mises, mises);
}

TEST(DerivedTest, StrainEquivalentUsesItsOwnConstant) {
  /* xx=0.1, yy=0.2, zz=0.3, no shear. The strain form is
   * (sqrt(2)/3) * sqrt(sum of squared differences) = sqrt(3)/15. */
  const std::vector<double> t = row(0.1, 0.2, 0.3, 0.0, 0.0, 0.0);
  double mises = 0.0;
  double signed_mises = 0.0;
  von_mises_strain(t.data(), 1, &mises, &signed_mises);
  EXPECT_NEAR(mises, std::sqrt(3.0) / 15.0, 1e-15);
  EXPECT_DOUBLE_EQ(signed_mises, mises);
}

TEST(DerivedTest, StrainAndStressDifferOnTheSameTensor) {
  /* The two forms share their inner sum and differ only in the constant.
   * A copy-paste that left the stress constant in the strain function would
   * pass every test above; this is what separates them. */
  const std::vector<double> t = row(0.1, 0.2, 0.3, 0.0, 0.0, 0.0);
  double stress_mises = 0.0;
  double strain_mises = 0.0;
  double ignored = 0.0;
  von_mises_stress(t.data(), 1, &stress_mises, &ignored);
  von_mises_strain(t.data(), 1, &strain_mises, &ignored);
  EXPECT_NE(stress_mises, strain_mises);
  /* stress uses sqrt(0.5 * S), strain uses (sqrt(2)/3) * sqrt(S), so the
   * ratio is fixed and independent of the tensor. */
  EXPECT_NEAR(strain_mises / stress_mises, (std::sqrt(2.0) / 3.0) * std::sqrt(2.0), 1e-14);
}

TEST(DerivedTest, PrincipalsOfADiagonalTensorAreItsDiagonal) {
  const std::vector<double> t = row(10.0, 20.0, 30.0, 0.0, 0.0, 0.0);
  double ps3 = 0.0;
  double ps2 = 0.0;
  double ps1 = 0.0;
  principal_values(t.data(), &ps3, &ps2, &ps1);
  EXPECT_DOUBLE_EQ(ps3, 10.0);
  EXPECT_DOUBLE_EQ(ps2, 20.0);
  EXPECT_DOUBLE_EQ(ps1, 30.0);
}

TEST(DerivedTest, PrincipalsAreAscendingWhateverTheDiagonalOrder) {
  /* PS3 is the smallest and PS1 the largest, regardless of how the file
   * happened to order the diagonal. */
  const std::vector<double> t = row(30.0, 10.0, 20.0, 0.0, 0.0, 0.0);
  double ps3 = 0.0;
  double ps2 = 0.0;
  double ps1 = 0.0;
  principal_values(t.data(), &ps3, &ps2, &ps1);
  EXPECT_DOUBLE_EQ(ps3, 10.0);
  EXPECT_DOUBLE_EQ(ps2, 20.0);
  EXPECT_DOUBLE_EQ(ps1, 30.0);
}

TEST(DerivedTest, PurePlanarShearHasKnownPrincipals) {
  /* xy shear of tau alone: eigenvalues are -tau, 0, +tau. Analytic, and it
   * exercises an off-diagonal rotation, which a diagonal tensor never does. */
  const double tau = 7.0;
  const std::vector<double> t = row(0.0, 0.0, 0.0, tau, 0.0, 0.0);
  double ps3 = 0.0;
  double ps2 = 0.0;
  double ps1 = 0.0;
  principal_values(t.data(), &ps3, &ps2, &ps1);
  EXPECT_NEAR(ps3, -tau, 1e-13);
  EXPECT_NEAR(ps2, 0.0, 1e-13);
  EXPECT_NEAR(ps1, tau, 1e-13);
}

TEST(DerivedTest, PrincipalsSumToTheTrace) {
  /* An invariant of the eigendecomposition, checked on a tensor with every
   * shear component non-zero -- the case where a rotation bug shows up and
   * a diagonal fixture cannot. */
  const std::vector<double> t = row(3.0, -2.0, 5.0, 1.5, -0.5, 2.25);
  double ps3 = 0.0;
  double ps2 = 0.0;
  double ps1 = 0.0;
  principal_values(t.data(), &ps3, &ps2, &ps1);
  EXPECT_NEAR(ps3 + ps2 + ps1, 3.0 - 2.0 + 5.0, 1e-12);
  EXPECT_LE(ps3, ps2);
  EXPECT_LE(ps2, ps1);
}

TEST(DerivedTest, PrincipalsReproduceTheSecondInvariant) {
  /* Sum of pairwise products equals the second invariant of the matrix. Two
   * invariants pinned together leave a wrong eigensolver nowhere to hide:
   * matching the trace alone is possible with the off-diagonals ignored. */
  const double xx = 3.0, yy = -2.0, zz = 5.0, xy = 1.5, yz = -0.5, zx = 2.25;
  const std::vector<double> t = row(xx, yy, zz, xy, yz, zx);
  double ps3 = 0.0;
  double ps2 = 0.0;
  double ps1 = 0.0;
  principal_values(t.data(), &ps3, &ps2, &ps1);

  const double invariant = xx * yy + yy * zz + zz * xx - (xy * xy + yz * yz + zx * zx);
  EXPECT_NEAR(ps3 * ps2 + ps2 * ps1 + ps1 * ps3, invariant, 1e-11);
}

TEST(DerivedTest, PrincipalsReproduceTheDeterminant) {
  /* The third invariant, completing the set. Trace, second invariant and
   * determinant are the coefficients of the characteristic polynomial, so a
   * triple matching all three is the eigenvalue multiset and not merely three
   * numbers with the right sum and spread. */
  const double xx = 3.0, yy = -2.0, zz = 5.0, xy = 1.5, yz = -0.5, zx = 2.25;
  const std::vector<double> t = row(xx, yy, zz, xy, yz, zx);
  double ps3 = 0.0;
  double ps2 = 0.0;
  double ps1 = 0.0;
  principal_values(t.data(), &ps3, &ps2, &ps1);

  const double determinant =
      xx * (yy * zz - yz * yz) - xy * (xy * zz - yz * zx) + zx * (xy * yz - yy * zx);
  EXPECT_NEAR(ps3 * ps2 * ps1, determinant, 1e-11);
}

TEST(DerivedTest, PrincipalsSatisfyTheirCharacteristicPolynomial) {
  /* The gate on convergence, as opposed to on ordering or on invariants of
   * the triple taken together. Each returned value is put back into
   * p(x) = x^3 - I1 x^2 + I2 x - I3, whose exact roots are the eigenvalues,
   * and the residual is required to be small.
   *
   * This exists because the Jacobi stopping rule is a threshold, and a
   * threshold is the kind of thing that gets loosened by someone chasing the
   * function's cost -- it is 23% of a read, so someone will. Nothing else
   * here would notice: ordering still holds, the trace still holds exactly
   * because rotations preserve it, and an under-converged solver still
   * returns three plausible numbers.
   *
   * The bound is calibrated, not guessed. Measured over 200k random tensors
   * at scales 1, 1e8 and 1e-20 the shipped rule's worst residual is 7.5 in
   * these units. Loosening the rule to 1e-6 takes it to 41400 and to 1e-3
   * takes it to 4.2e10. A bound of 100 therefore has 13x headroom over the
   * real distribution and still fails a 1e-6 loosening by a factor of 400.
   *
   * The residual is scaled by ||A||^3 because p is cubic in a quantity of
   * order ||A||; scaling by the eigenvalue instead would report nonsense for
   * a tensor with an eigenvalue near zero, which is the same mistake
   * doc/divergences.md records for the conformance band. */
  const double eps = 2.220446049250313e-16;
  const double kBound = 100.0;

  struct Case {
    const char *name;
    double t[6];
  };
  const Case cases[] = {
      {"general", {3.0, -2.0, 5.0, 1.5, -0.5, 2.25}},
      {"all shear, zero diagonal", {0.0, 0.0, 0.0, 1.0, 2.0, 3.0}},
      {"near-degenerate pair", {1.0, 1.0 + 1e-15, 2.0, 1e-16, 0.0, 0.0}},
      {"stress magnitudes", {2.4e8, -1.1e8, 7.7e7, 3.2e7, -9.4e7, 1.8e7}},
      {"strain magnitudes", {2.4e-20, -1.1e-20, 7.7e-21, 3.2e-21, -9.4e-21, 1.8e-21}},
      {"one dominant shear", {1.0, 1.0, 1.0, 1e6, 0.0, 0.0}},
      {"wide spread", {1e-8, 1.0, 1e8, 1.0, 1.0, 1.0}},
  };

  for (const Case &c : cases) {
    const double xx = c.t[0], yy = c.t[1], zz = c.t[2];
    const double xy = c.t[3], yz = c.t[4], zx = c.t[5];
    const double i1 = xx + yy + zz;
    const double i2 = xx * yy + yy * zz + zz * xx - (xy * xy + yz * yz + zx * zx);
    const double i3 =
        xx * (yy * zz - yz * yz) - xy * (xy * zz - yz * zx) + zx * (xy * yz - yy * zx);

    double norm = 0.0;
    for (double v : c.t) norm += v * v;
    norm = std::sqrt(norm);
    ASSERT_GT(norm, 0.0) << c.name;

    const std::vector<double> t = row(xx, yy, zz, xy, yz, zx);
    double values[3] = {0.0, 0.0, 0.0};
    principal_values(t.data(), &values[0], &values[1], &values[2]);

    for (double lambda : values) {
      const double residual = ((lambda - i1) * lambda + i2) * lambda - i3;
      const double scaled = std::fabs(residual) / (eps * norm * norm * norm);
      EXPECT_LT(scaled, kBound) << c.name << ": lambda " << lambda << " leaves residual " << scaled
                                << " eps*||A||^3, bound " << kBound
                                << ". The Jacobi stopping rule is under-converged.";
    }
  }
}

TEST(DerivedTest, PrincipalsOfAZeroTensorAreExactlyZero) {
  const std::vector<double> t = row(0.0, 0.0, 0.0, 0.0, 0.0, 0.0);
  double ps3 = 1.0;
  double ps2 = 1.0;
  double ps1 = 1.0;
  principal_values(t.data(), &ps3, &ps2, &ps1);
  EXPECT_EQ(ps3, 0.0);
  EXPECT_EQ(ps2, 0.0);
  EXPECT_EQ(ps1, 0.0);
}

TEST(DerivedTest, PrincipalsSurviveAHugeDynamicRange) {
  /* Real strain arrays run to 1e-20 while stress runs to 1e8. A solver that
   * scales badly turns the small one into noise, and a relative comparison
   * against the reference would then be measuring the noise. */
  const double small = 1e-20;
  const std::vector<double> t = row(small, 2 * small, 3 * small, 0.0, 0.0, 0.0);
  double ps3 = 0.0;
  double ps2 = 0.0;
  double ps1 = 0.0;
  principal_values(t.data(), &ps3, &ps2, &ps1);
  EXPECT_DOUBLE_EQ(ps3, small);
  EXPECT_DOUBLE_EQ(ps2, 2 * small);
  EXPECT_DOUBLE_EQ(ps1, 3 * small);
}

TEST(DerivedTest, BatchAgreesWithElementwise) {
  /* The batch entry points are what the parser calls. A loop bug there would
   * be invisible to every single-row test above. */
  std::vector<double> tensor;
  for (int i = 0; i < 5; ++i) {
    const double s = static_cast<double>(i + 1);
    const std::vector<double> r = row(s, 2 * s, 3 * s, 0.5 * s, -0.25 * s, 0.125 * s);
    tensor.insert(tensor.end(), r.begin(), r.end());
  }

  std::vector<double> mises(5), signed_mises(5);
  von_mises_stress(tensor.data(), 5, mises.data(), signed_mises.data());
  for (int i = 0; i < 5; ++i) {
    double one = 0.0;
    double one_signed = 0.0;
    von_mises_stress(tensor.data() + i * 6, 1, &one, &one_signed);
    EXPECT_EQ(mises[i], one) << "row " << i;
    EXPECT_EQ(signed_mises[i], one_signed) << "row " << i;
  }
}

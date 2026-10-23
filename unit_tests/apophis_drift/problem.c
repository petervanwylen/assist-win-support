/**
 * Compare *relative drift* between the SPK (.bsp) and ASCII-derived binary (.440)
 * planets backends for the same Apophis setup as unit_tests/apophis_spk and
 * unit_tests/apophis_ascii.
 *
 * Unlike the single-epoch accuracy tests, this samples multiple checkpoints so
 * regressions (e.g. missing asteroid masses in the .440 path) show up clearly as
 * accumulated drift.
 */
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
#include <math.h>
#include <string.h>

#include "rebound.h"
#include "assist.h"

static const double AU2M = 149597870700.0;

static struct reb_particle integrate_to(struct assist_ephem* ephem,
                                        struct reb_particle apophis_initial_bary,
                                        double t0,
                                        double t){
    struct reb_simulation* r = reb_simulation_create();
    struct assist_extras* ax = assist_attach(r, ephem);

    // Turn on GR from all planets
    ax->gr_eih_sources = ASSIST_BODY_NPLANETS;

    // Define non-gravitational parameters A1, A2, A3
    static double params[] = {4.999999873689E-13, -2.901085508711E-14, 0.0};
    ax->particle_params = params;

    r->t = t0;
    r->ri_ias15.min_dt = 0.001; // in days

    reb_simulation_add(r, apophis_initial_bary);
    reb_simulation_integrate(r, t);

    struct reb_particle out = r->particles[0];

    assist_free(ax);
    reb_simulation_free(r);
    return out;
}

int main(int argc, char* argv[]){
    struct assist_ephem* ephem_spk = assist_ephem_create(
            "../../data/de440.bsp",
            "../../data/sb441-n16.bsp");
    if (ephem_spk == NULL){
        fprintf(stderr,"Error initializing SPK ephem.\n");
        exit(1);
    }

    struct assist_ephem* ephem_ascii = assist_ephem_create(
            "../../data/linux_p1550p2650.440",
            "../../data/sb441-n16.bsp");
    if (ephem_ascii == NULL){
        fprintf(stderr,"Error initializing ASCII (.440/.441) ephem.\n");
        exit(1);
    }

    // Epochs in JD, mirroring the existing Apophis tests.
    double t0_jd = 2.4621385359989386E+06;
    double t1_jd = 2.4625030372426095E+06;

    double t0 = t0_jd - ephem_spk->jd_ref;
    double t1 = t1_jd - ephem_spk->jd_ref;

    // Initial heliocentric state (AU, AU/day)
    struct reb_particle p_initial_helio = {
                    .x = -5.5946538550488512E-01,
                    .y =  8.5647564757574512E-01,
                    .z =  3.0415066217102493E-01,
                    .vx= -1.3818324735921638E-02,
                    .vy= -6.0088275597939191E-03,
                    .vz= -2.5805044631309632E-03};

    // Use the SPK Sun shift to define a single shared barycentric initial condition.
    struct reb_particle sun0 = assist_get_particle(ephem_spk, 0, t0);
    reb_particle_iadd(&p_initial_helio, &sun0);
    struct reb_particle p_initial_bary = p_initial_helio;

    struct {
        const char* name;
        double t;
    } checkpoints[] = {
        {"t0", t0},
        {"t0+120d", t0 + 120.0},
        {"t0+240d", t0 + 240.0},
        {"t0+330d", t0 + 330.0},
        {"t1", t1},
    };

    // Track whether the residual direction takes both signs over the window.
    // We deliberately do not record which checkpoint holds which sign: this
    // residual is a roundoff-scale difference between two nearly identical
    // integrations, so its per-checkpoint sign is compiler dependent (see the
    // note on the assertions below).
    const double eps = 1e-3; // 1 mm
    int dy_pos = 0, dy_neg = 0, dz_pos = 0, dz_neg = 0;

    double r0 = -1.0;
    double r_final = -1.0;

    for (size_t i=0; i<sizeof(checkpoints)/sizeof(checkpoints[0]); i++){
        struct reb_particle ps = integrate_to(ephem_spk, p_initial_bary, t0, checkpoints[i].t);
        struct reb_particle pj = integrate_to(ephem_ascii, p_initial_bary, t0, checkpoints[i].t);

        double dx_m = (ps.x - pj.x) * AU2M;
        double dy_m = (ps.y - pj.y) * AU2M;
        double dz_m = (ps.z - pj.z) * AU2M;
        double r_m  = sqrt(dx_m*dx_m + dy_m*dy_m + dz_m*dz_m);

        printf("%s: dx=%.6f m dy=%.6f m dz=%.6f m |d|=%.6f m\n",
               checkpoints[i].name, dx_m, dy_m, dz_m, r_m);

        if (i == 0){
            r0 = r_m;
        }
        if (i > 0){
            if (dy_m >  eps) dy_pos = 1;
            if (dy_m < -eps) dy_neg = 1;
            if (dz_m >  eps) dz_pos = 1;
            if (dz_m < -eps) dz_neg = 1;
        }
        if (strcmp(checkpoints[i].name, "t1") == 0){
            r_final = r_m;
        }
    }

    // Same initial condition -> drift at t0 should be ~0.
    assert(r0 >= 0.0);
    assert(r0 < 1e-6);

    // Guardrail: should remain close; catch regressions.
    assert(r_final > 1e-3);   // 1 mm (not exactly zero)
    assert(r_final < 5000.0); // 5 km

    // The direction of the residual rotates over the window, so dy and dz each
    // take both signs. We assert only that, not which checkpoint carries which
    // sign: this residual is dominated by floating-point evaluation order
    // rather than by the ephemeris data. Changing only the MSVC floating-point
    // model (/fp:precise -> /fp:fast) moves the final residual from 1.9 m to
    // 48 m, and GCC on Linux and MSVC on Windows produce opposite signs at the
    // same checkpoints with comparable magnitudes. The absolute-accuracy tests
    // against JPL Horizons (holman_*, apophis_*, 5303_Ceres_*) are what pin
    // the trajectories; this test is a guardrail against big regressions such
    // as missing asteroid masses or the wrong backend being selected.
    //
    // This matches assist/test/test_apophis_drift_spk_vs_ascii.py, which
    // already asserts the sign change this way.
    assert(dy_pos && dy_neg);
    assert(dz_pos && dz_neg);

    assist_ephem_free(ephem_spk);
    assist_ephem_free(ephem_ascii);
}



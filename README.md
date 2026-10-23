[![Version](https://img.shields.io/badge/assist-v1.2.0-green.svg?style=flat)](https://assist.readthedocs.org)
[![GPL](https://img.shields.io/badge/license-GPL-green.svg?style=flat)](https://github.com/matthewholman/blob/main/LICENSE)
[![Python unit tests)](https://github.com/matthewholman/assist/actions/workflows/python.yml/badge.svg)](https://github.com/matthewholman/assist/actions/workflows/python.yml)
[![C unit tests](https://github.com/matthewholman/assist/actions/workflows/c.yml/badge.svg)](https://github.com/matthewholman/assist/actions/workflows/c.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.7778016.svg)](https://doi.org/10.5281/zenodo.7778016)



# ASSIST

ASSIST is a software package for ephemeris-quality integrations of test particles. ASSIST is an extension of the [REBOUND framework](https://github.com/hannorein/rebound) and makes use of its [IAS15 integrator](https://ui.adsabs.harvard.edu/abs/2015MNRAS.446.1424R/abstract) to integrate test particle trajectories in the field of the Sun, Moon, planets, and 16 massive asteroids, with the positions of the masses coming from the JPL DE441 ephemeris and its associated asteroid perturber file. The package incorporates the most significant gravitational harmonics and general relativistic corrections. ASSIST also accounts for position- and velocity-dependent non-gravitational effects according to the [Marsden (1973) model](https://ui.adsabs.harvard.edu/abs/1973AJ.....78..211M/abstract). All components in the equations of motion have been verified to machine precision in a term-by-term comparison with output from JPL's small body integrator. The first order variational equations are included for all terms to support orbit fitting and covariance mapping. This framework is meant to provide an open-source package written in a modern language to enable high-precision orbital analysis and science by the small body community.

## Planet ephemeris formats (DE440)

ASSIST supports both ASCII-derived binary ephemerides (e.g., `linux_p1550p2650.440` / `.441`) and NAIF SPK `.bsp` kernels (e.g., `de440.bsp`) for planets:

- If you pass a planets file, ASSIST auto-detects its format at init and uses the matching provider.
- If you omit the planets path and set `ASSIST_DIR`, ASSIST will try (in order):
  - `ASSIST_DIR/de441.bsp`
  - `ASSIST_DIR/de440.bsp`
  - `ASSIST_DIR/linux_m13000p17000.441`
  - `ASSIST_DIR/linux_p1550p2650.440`

Asteroids continue to use SPK (`sb441-n16.bsp` by default), and their masses are joined from the selected planets ephemeris constants.

Constants (AU, EMRAT, J2E, J3E, J4E, J2SUN, RE, CLIGHT, ASUN) are unified onto the ephemeris object and used consistently across force models. Only the required kernel is loaded in memory.

### Recommended downloads

```bash
# Planets (SPK)
curl https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de440.bsp -o assist/data/de440.bsp
# Asteroids (SPK)
curl https://ssd.jpl.nasa.gov/ftp/eph/small_bodies/asteroids_de441/sb441-n16.bsp -o assist/data/sb441-n16.bsp
```

ASCII-derived binary planets file (smaller coverage) is also supported:

```bash
curl https://ssd.jpl.nasa.gov/ftp/eph/planets/Linux/de440/linux_p1550p2650.440 -o assist/data/linux_p1550p2650.440
```

## Installation (Python)

It's easiest to install ASSIST into a python virtual environment. If you already have a virtual environment or do not want to use one, you can skip this step. Otherwise, run the following command in an empty directory. They will setup and activate a new virtual environment in a directory. 

    python3 -m venv venv
    source venv/bin/activate

Now we can install numpy, REBOUND, and ASSIST:

    pip install numpy
    pip install rebound 
    pip install assist

To use use ASSIST, you also need to download ephemeris data files. One file for planet ephemeris and another suplementary file for asteroid ephemeris. The following commands download these files with curl. You can also manually download them using your browser. Note that these are large files, almost 1GB in size.

    mkdir data
    curl https://ssd.jpl.nasa.gov/ftp/eph/planets/Linux/de440/linux_p1550p2650.440 -o data/linux_p1550p2650.440
    curl https://ssd.jpl.nasa.gov/ftp/eph/small_bodies/asteroids_de441/sb441-n16.bsp -o data/sb441-n16.bsp

Now you can try out if assist works.

    python3

    >>> import assist
    >>> ephem = assist.Ephem("data/linux_p1550p2650.440", "data/sb441-n16.bsp")
    >>> print(ephem.jd_ref)
    >>> ephem.get_particle("Earth", 0)

You should see the default reference Julian date (2451545.0) and the position of the Earth at that time printed on the screen.

## Installation (Windows)

ASSIST builds and runs natively on 64-bit Windows (`win_amd64`). There are no
Windows wheels on PyPI yet, so `pip` compiles ASSIST from source and you need a
C compiler first. This is a one-time setup.

**1. Install the Visual Studio Build Tools** (the C++ compiler `cl.exe`). In
PowerShell:

    winget install --id Microsoft.VisualStudio.2022.BuildTools --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"

You do not need the full Visual Studio IDE, and you do not need to open a
Developer Command Prompt afterwards -- `pip` locates the compiler on its own.

**2. Install ASSIST.** REBOUND 4.x publishes Windows wheels for CPython 3.10,
3.11 and 3.12, so use one of those versions:

    py -3.12 -m venv venv
    venv\Scripts\activate
    pip install assist

REBOUND and numpy are installed automatically.

**3. Download the ephemeris data files.** These are large, roughly 1 GB total:

    mkdir data
    curl.exe https://ssd.jpl.nasa.gov/ftp/eph/planets/Linux/de440/linux_p1550p2650.440 -o data/linux_p1550p2650.440
    curl.exe https://ssd.jpl.nasa.gov/ftp/eph/small_bodies/asteroids_de441/sb441-n16.bsp -o data/sb441-n16.bsp

Then check that it works:

    python

    >>> import assist
    >>> ephem = assist.Ephem("data/linux_p1550p2650.440", "data/sb441-n16.bsp")
    >>> print(ephem.jd_ref)
    >>> ephem.get_particle("Earth", 0)

### Notes and current limitations

- **Supported target:** 64-bit CPython 3.10-3.12 on `win_amd64`, Python API
  only. The physics and the public Python API are identical to Linux and macOS.
- **Python 3.13+** does not work yet, because REBOUND 4.x publishes no Windows
  wheels for it and ASSIST requires `rebound>=4.4.11,<5.0.0`.
- **MSVC only.** MinGW and Cygwin are not supported: ASSIST links against the
  `librebound*.pyd` from the REBOUND wheel, which is built with MSVC.
- **The REBOUND wheel ships no import library.** MSVC cannot link against a DLL
  directly, so `setup.py` reconstructs `rebound*.lib` from the export table of
  `librebound*.pyd` at build time (see `windows_support.py`). This happens
  automatically.
- **Numerical differences.** MSVC has no equivalent of GCC's
  `-fno-strict-aliasing` / `-fstrict-overflow`; it does not perform
  type-based alias analysis, so those flags are unnecessary. ASSIST is compiled
  with `/fp:precise` to keep floating-point evaluation faithful. All accuracy
  tests against JPL Horizons pass with the same tolerances used on Linux.
- **Not yet supported on Windows:** OpenMP, MPI, and the C examples under
  `examples/` (their makefiles are GNU/POSIX). The C *unit tests* do run --
  see below.

### Running the tests on Windows

The Python test suite runs as usual once the ephemeris files are in `data/`
(`de440.bsp` is needed in addition to the two files above):

    set ASSIST_DIR=%CD%
    python -m unittest discover -s assist/test -p "test_*.py"

The C unit tests are normally driven by GNU make, which is not available here.
Use the MSVC driver instead, which builds `libassist.dll` and every
`unit_tests/*/problem.c` and runs them:

    python dev_tools/build_c_tests_windows.py

    # or a subset
    python dev_tools/build_c_tests_windows.py holman_spk apophis_spk

## Installation (C)

To install the C version of ASSIST, first clone the REBOUND and then the ASSIST repositories. In an empty directory, run:

    git clone https://github.com/hannorein/rebound.git
    git clone https://github.com/matthewholman/assist.git

To use use ASSIST, you also need to download ephemeris data files. One file for planet ephemeris and another suplementary file for asteroid ephemeris. The following commands download these files with curl. You can also manually download them using your browser. Note that these are large files, almost 1GB in size.

    curl https://ssd.jpl.nasa.gov/ftp/eph/planets/Linux/de440/linux_p1550p2650.440 -o assist/data/linux_p1550p2650.440
    curl https://ssd.jpl.nasa.gov/ftp/eph/small_bodies/asteroids_de441/sb441-n16.bsp -o assist/data/sb441-n16.bsp

For some of the examples, you will also need the planet ephemeris file with an extended coverage. Note that this file is 2.6GB in size.

    curl https://ssd.jpl.nasa.gov/ftp/eph/planets/Linux/de441/linux_m13000p17000.441 -o assist/data/linux_m13000p17000.441

Next, go to one of the example directories and compile the problem file. This will also trigger the installation of the REBOUND and ASSIST shared libraries.

    cd assist/examples/asteroid
    make

Now, you're ready to run the example with:

    ./rebound


## License
ASSIST is open source, freely distributed under the [GNU General Public license, version 3](https://github.com/matthewholman/blob/main/LICENSE).

## Contributors

* Matthew J. Holman, Center for Astrophysics | Harvard & Smithsonian, <mholman@cfa.harvard.edu>
* Arya Akmal, Montgomery College, Rockville
* Davide Farnocchia, Jet Propulsion Laboratory, California Institute of Technology 
* Hanno Rein, University of Toronto, <hanno@hanno-rein.de>
* Matthew J. Payne, Center for Astrophysics | Harvard & Smithsonian
* Robert Weryk, University of Western Ontario
* Dan Tamayo, Harvey Mudd College, <dtamayo@hmc.edu>
* David M. Hernandez, Center for Astrophysics | Harvard & Smithsonian 



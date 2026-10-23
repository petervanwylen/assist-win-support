"""Build and run the ASSIST C unit tests on Windows with MSVC.

The C unit tests are normally driven by GNU make (``unit_tests/Makefile.common``),
which relies on POSIX tooling -- symlinks, ``-rpath``, ``.so`` naming -- that has
no direct Windows equivalent. This script is the Windows counterpart: it does
the same three things the makefiles do, using the MSVC toolchain that a Windows
source build already requires.

    1. Build ``libassist.dll`` from ``src/*.c``, linking against the REBOUND
       shared library from the installed ``rebound`` wheel.
    2. Compile each ``unit_tests/<name>/problem.c`` and link it against
       ``libassist.lib`` and ``rebound*.lib``.
    3. Run each test executable from its own directory (the tests open
       ephemeris files via relative paths such as ``../../data/de440.bsp``)
       and report pass/fail.

Usage, from the repository root:

    python dev_tools/build_c_tests_windows.py            # build and run all
    python dev_tools/build_c_tests_windows.py holman_spk apophis_spk
    python dev_tools/build_c_tests_windows.py --build-only
    python dev_tools/build_c_tests_windows.py --list

Requires the ephemeris files in ``data/`` (see the README) and a Python
environment with ``rebound`` installed.
"""

from __future__ import annotations

import argparse
import inspect
import os
import shutil
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from windows_support import build_rebound_import_library, find_rebound_library  # noqa: E402

SRC_FILES = ['assist.c', 'spk.c', 'forces.c', 'tools.c', 'ascii_ephem.c']

# Tests that are benchmarks or otherwise not pass/fail assertions.
NON_TEST_DIRS = {'benchmark'}

BUILD_DIR = os.path.join(REPO_ROOT, 'build', 'ctests-win')


def log(msg):
    print(msg, flush=True)


def make_compiler():
    """Return an initialized MSVC compiler object from setuptools."""
    try:
        from setuptools._distutils.ccompiler import new_compiler
    except ImportError:  # pragma: no cover - very old setuptools
        from distutils.ccompiler import new_compiler

    compiler = new_compiler(compiler='msvc', verbose=0)
    compiler.initialize()
    return compiler


def git_hash():
    try:
        out = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO_ROOT)
        return out.decode('ascii').strip()
    except Exception:
        return '0000000000gitnotfound0000000000000000000'


def build_libassist(compiler, rebound_dir, implib_dir):
    """Compile src/*.c into build/ctests-win/libassist.dll.

    Returns (dll_path, import_lib_path).
    """
    obj_dir = os.path.join(BUILD_DIR, 'obj')
    os.makedirs(obj_dir, exist_ok=True)

    sources = [os.path.join('src', name) for name in SRC_FILES]

    # Same flags as the MSVC branch of setup.py, so the C tests exercise a
    # library built exactly like the one pip produces.
    cflags = [
        '/O2',
        '/fp:precise',
        '/std:c11',
        '/D_CRT_SECURE_NO_WARNINGS',
        '/D_CRT_NONSTDC_NO_WARNINGS',
        '/wd4018',                      # signed/unsigned comparison, pre-existing
        '-D_GNU_SOURCE',
        '-DASSISTGITHASH=' + git_hash(),
    ]

    log("Compiling libassist objects ...")
    objects = compiler.compile(
        sources,
        output_dir=obj_dir,
        macros=[('LIBASSIST', None)],
        include_dirs=[os.path.join(REPO_ROOT, 'src'), rebound_dir],
        extra_postargs=cflags,
    )

    rebound_dll = find_rebound_library(rebound_dir)
    rebound_stem = os.path.splitext(os.path.basename(rebound_dll))[0]
    if rebound_stem.startswith('lib'):
        rebound_stem = rebound_stem[3:]

    dll_path = os.path.join(BUILD_DIR, 'libassist.dll')
    log("Linking libassist.dll ...")
    compiler.link_shared_object(
        objects,
        dll_path,
        libraries=[rebound_stem],
        library_dirs=[implib_dir],
        export_symbols=[],   # exports come from __declspec(dllexport) in the headers
    )

    # MSVC writes the /IMPLIB alongside the first object file rather than next
    # to the DLL, so locate it and copy it where the tests link from.
    import_lib = os.path.join(BUILD_DIR, 'libassist.lib')
    if not os.path.exists(import_lib):
        produced = None
        for dirpath, _dirnames, filenames in os.walk(obj_dir):
            if 'libassist.lib' in filenames:
                produced = os.path.join(dirpath, 'libassist.lib')
                break
        if produced is None:
            raise RuntimeError("linker did not produce libassist.lib under %s" % obj_dir)
        shutil.copy2(produced, import_lib)
    return dll_path, import_lib


def discover_tests(selection):
    unit_tests = os.path.join(REPO_ROOT, 'unit_tests')
    names = []
    for name in sorted(os.listdir(unit_tests)):
        d = os.path.join(unit_tests, name)
        if not os.path.isdir(d):
            continue
        if not os.path.exists(os.path.join(d, 'problem.c')):
            continue
        if name in NON_TEST_DIRS:
            continue
        names.append(name)
    if selection:
        unknown = [s for s in selection if s not in names]
        if unknown:
            raise SystemExit("Unknown test(s): %s\nAvailable: %s"
                             % (', '.join(unknown), ', '.join(names)))
        names = [n for n in names if n in selection]
    return names


def build_test(compiler, name, rebound_dir, implib_dir, assist_lib):
    test_dir = os.path.join(REPO_ROOT, 'unit_tests', name)
    obj_dir = os.path.join(BUILD_DIR, 'tests', name)
    os.makedirs(obj_dir, exist_ok=True)

    rebound_dll = find_rebound_library(rebound_dir)
    rebound_stem = os.path.splitext(os.path.basename(rebound_dll))[0]
    if rebound_stem.startswith('lib'):
        rebound_stem = rebound_stem[3:]

    objects = compiler.compile(
        [os.path.join('unit_tests', name, 'problem.c')],
        output_dir=obj_dir,
        include_dirs=[os.path.join(REPO_ROOT, 'src'), rebound_dir],
        extra_postargs=['/O2', '/fp:precise', '/std:c11',
                        '/D_CRT_SECURE_NO_WARNINGS', '/D_CRT_NONSTDC_NO_WARNINGS',
                        # Every C unit test states its tolerance checks as
                        # assert(). distutils hard-codes /DNDEBUG, which would
                        # compile them out and make the tests pass
                        # unconditionally. GNU make builds problem.c without
                        # NDEBUG, so undefine it here to match.
                        '/UNDEBUG'],
    )

    exe_path = os.path.join(obj_dir, name + '.exe')
    compiler.link_executable(
        objects,
        os.path.join(obj_dir, name),
        libraries=['libassist', rebound_stem],
        library_dirs=[BUILD_DIR, implib_dir],
    )
    return test_dir, exe_path


def run_test(name, test_dir, exe_path, dll_dirs):
    """Run one test executable from its own directory."""
    env = dict(os.environ)
    # Windows resolves DLL dependencies of an .exe from its own directory and
    # then from PATH; libassist.dll and librebound*.pyd live elsewhere.
    env['PATH'] = os.pathsep.join(dll_dirs + [env.get('PATH', '')])
    env.setdefault('ASSIST_DIR', REPO_ROOT)

    started = time.time()
    proc = subprocess.run([exe_path], cwd=test_dir, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    elapsed = time.time() - started
    output = proc.stdout.decode('utf-8', 'replace')
    return proc.returncode, elapsed, output


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('tests', nargs='*', help='test directory names (default: all)')
    parser.add_argument('--build-only', action='store_true', help='compile but do not run')
    parser.add_argument('--list', action='store_true', help='list available tests and exit')
    parser.add_argument('--clean', action='store_true', help='remove the build directory first')
    args = parser.parse_args()

    if sys.platform != 'win32':
        raise SystemExit("This script is for Windows. On Linux/macOS run 'make test'.")

    if args.list:
        for name in discover_tests(None):
            print(name)
        return 0

    if args.clean and os.path.isdir(BUILD_DIR):
        shutil.rmtree(BUILD_DIR)

    os.chdir(REPO_ROOT)

    try:
        import rebound
    except ImportError:
        raise SystemExit("The 'rebound' package is required. Install it with:\n"
                         "    pip install \"rebound>=4.4.11,<5.0.0\"")

    rebound_dir = os.path.dirname(inspect.getfile(rebound))
    os.makedirs(BUILD_DIR, exist_ok=True)

    compiler = make_compiler()
    implib_dir = build_rebound_import_library(
        compiler, rebound_dir, os.path.join(BUILD_DIR, 'rebound_implib'))

    dll_path, assist_lib = build_libassist(compiler, rebound_dir, implib_dir)
    log("Built %s" % dll_path)

    names = discover_tests(args.tests)
    log("\nBuilding %d C unit test(s) ...\n" % len(names))

    built = []
    for name in names:
        try:
            test_dir, exe_path = build_test(compiler, name, rebound_dir, implib_dir, assist_lib)
            built.append((name, test_dir, exe_path))
        except Exception as exc:
            log("  BUILD FAIL  %-32s %s" % (name, exc))

    if args.build_only:
        log("\nBuilt %d/%d tests." % (len(built), len(names)))
        return 0 if len(built) == len(names) else 1

    dll_dirs = [BUILD_DIR, os.path.dirname(find_rebound_library(rebound_dir))]

    log("\nRunning C unit tests ...\n")
    failures = []
    for name, test_dir, exe_path in built:
        code, elapsed, output = run_test(name, test_dir, exe_path, dll_dirs)
        status = 'ok' if code == 0 else 'FAIL (exit %d)' % code
        log("  %-34s %6.2fs  %s" % (name, elapsed, status))
        if code != 0:
            failures.append((name, output))

    not_built = [n for n in names if n not in {b[0] for b in built}]

    log("\n" + "-" * 60)
    log("ran %d, passed %d, failed %d, not built %d"
        % (len(built), len(built) - len(failures), len(failures), len(not_built)))

    for name, output in failures:
        log("\n=== %s output ===" % name)
        log(output.strip()[-2000:])

    return 1 if (failures or not_built) else 0


if __name__ == '__main__':
    sys.exit(main())

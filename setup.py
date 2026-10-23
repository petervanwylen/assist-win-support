import inspect
import os
import sys
from codecs import open
from distutils import sysconfig
from distutils.sysconfig import get_python_lib

try:
    from setuptools import Extension, setup
    from setuptools.command.build_ext import build_ext as _build_ext
except ImportError:
    print("Installing ASSIST requires setuptools.  Do 'pip install setuptools'.")
    sys.exit(1)

suffix = sysconfig.get_config_var('EXT_SUFFIX')
if suffix is None:
    suffix = ".so"

# Try to get git hash
try:
    import subprocess
    # `git rev-parse HEAD` includes a trailing newline; strip it so the
    # preprocessor macro doesn't embed a newline (which can confuse compilers).
    ghash = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("ascii").strip()
    ghash_arg = "-DASSISTGITHASH="+ghash
except:
    ghash_arg = "-DASSISTGITHASH=316b413c146b971a2de4aeaa5882ad1acc8e889c" #GITHASHAUTOUPDATE


class build_ext(_build_ext):
    def finalize_options(self):
        _build_ext.finalize_options(self)

        try:
            import rebound
        except ImportError:
            print("ASSIST did not automatically install REBOUND.  Please try first installing REBOUND (https://rebound.readthedocs.org/en/latest/python_quickstart.html")
            sys.exit(1)
        try:
            version = rebound.__version__ # Added in 2.12.1
        except AttributeError:
            print("ASSIST did not automatically install a recent enough version of REBOUND.  Try upgrading REBOUND.  See 5.3 in https://rebound.readthedocs.org/en/latest/python_quickstart.html")
            sys.exit(1)

        rebdir = os.path.dirname(inspect.getfile(rebound))
        # get site-packages dir to add to paths in case REBOUND & ASSIST installed simul in tmp dir
        rebdirsp = get_python_lib()+'/'#[p for p in sys.path if p.endswith('site-packages')][0]+'/'
        self.include_dirs.append(rebdir)
        # Keep this list in sync with libassistmodule.sources below.
        sources = ['src/assist.c', 'src/spk.c', 'src/forces.c', 'src/tools.c', 'src/ascii_ephem.c']

        if not "CONDA_BUILD_CROSS_COMPILATION" in os.environ:
            # Add library directories for build-time linking
            self.library_dirs.append(rebdir+'/../')
            self.library_dirs.append(rebdirsp)
            
            for ext in self.extensions:
                # Clear any existing runtime_library_dirs to avoid conflicts
                ext.runtime_library_dirs = []
                
                # Use loader-relative paths for runtime linking
                if sys.platform == 'darwin':
                    # Primary path: same directory as the loading library
                    ext.extra_link_args.append('-Wl,-rpath,@loader_path')
                    # Backup path: current directory (for compatibility)
                    ext.extra_link_args.append('-Wl,-rpath,@loader_path/.')
                elif sys.platform.startswith('linux'):
                    # Linux equivalent of @loader_path
                    ext.extra_link_args.append('-Wl,-rpath,$ORIGIN')
                    ext.extra_link_args.append('-Wl,-rpath,$ORIGIN/.')
                
                print("Library directories:", self.library_dirs)
                print("Extra link args:", ext.extra_link_args)
        else:
            # For conda-forge cross-compile builds
            rebdir=get_python_lib(prefix=os.environ["PREFIX"])
            self.library_dirs.append(rebdir)
            for ext in self.extensions:
                ext.extra_link_args.append('-Wl,-rpath,'+rebdir)
                print("Cross-compile extra link args:", ext.extra_link_args)

    def get_export_symbols(self, ext):
        # `libassist` is not an importable Python extension module: it is a
        # plain shared library that the package opens with ctypes. setuptools
        # otherwise asks the linker to export `PyInit_libassist`, which does
        # not exist, and MSVC turns that into a hard link error (LNK2001).
        # Unix linkers do not require an entry point, which is why this only
        # ever mattered on Windows.
        if sys.platform == 'win32':
            return ext.export_symbols
        return _build_ext.get_export_symbols(self, ext)

    def build_extensions(self):
        # Windows only: manufacture the REBOUND import library that the wheel
        # does not ship, and point the linker at it. This runs here rather
        # than in finalize_options() because `self.compiler` (and therefore
        # the location of lib.exe) only exists once build_ext.run() has
        # created it.
        if sys.platform == 'win32':
            import rebound

            # pip runs the build backend with this directory as cwd but does
            # not add it to sys.path, so make the helper module importable.
            here = os.path.dirname(os.path.abspath(__file__))
            if here not in sys.path:
                sys.path.insert(0, here)
            from windows_support import build_rebound_import_library

            rebdir = os.path.dirname(inspect.getfile(rebound))
            implib_dir = os.path.join(self.build_temp, 'rebound_implib')
            implib_dir = build_rebound_import_library(self.compiler, rebdir, implib_dir)
            for ext in self.extensions:
                ext.library_dirs.append(implib_dir)

        _build_ext.build_extensions(self)


from distutils.version import LooseVersion

extra_link_args=[]
if sys.platform == 'darwin':
    from distutils import sysconfig
    vars = sysconfig.get_config_vars()
    vars['LDSHARED'] = vars['LDSHARED'].replace('-bundle', '-shared')
    extra_link_args.append('-Wl,-install_name,@rpath/libassist'+suffix)
elif sys.platform.startswith('linux'):
    # Linux doesn't need install_name, but we can add other flags if needed
    pass

libassistmodule = Extension(
    'libassist',
    sources=[
        'src/assist.c',
        'src/spk.c',
        'src/forces.c',
        'src/tools.c',
        'src/ascii_ephem.c',
    ],
    include_dirs=['src'],
    library_dirs=[],
    runtime_library_dirs=[],  # Will be set by build_ext.finalize_options
    libraries=['rebound' + suffix[: suffix.rfind('.')]],
    define_macros=[('LIBASSIST', None)],
    extra_compile_args=(
        # MSVC does not understand any of the GCC/Clang flags below, and has
        # no equivalent for -fno-strict-aliasing / -fstrict-overflow: it does
        # not perform type-based alias analysis, which is exactly the
        # behaviour those flags request from GCC. /fp:precise (the default) is
        # stated explicitly so that nobody "optimises" it to /fp:fast later,
        # which would change long integrations.
        [
            '/O2',
            '/fp:precise',
            '/std:c11',
            # The ephemeris readers use POSIX names (open/read/close) and
            # strdup/sprintf; MSVC deprecates both families by default.
            '/D_CRT_SECURE_NO_WARNINGS',
            '/D_CRT_NONSTDC_NO_WARNINGS',
            '-D_GNU_SOURCE',
            ghash_arg,
        ]
        if sys.platform == 'win32' else
        [
            # `spk.c` reads memory-mapped binary data via typed pointers. This is
            # common practice, but it can become undefined behavior under aggressive
            # strict-aliasing optimizations, and we have observed that it can change
            # long integrations (e.g. Apophis) by O(100 m).
            #
            # Compile ASSIST with strict-aliasing disabled to keep the Python build
            # numerically consistent with the `src/` Makefile build and with the C
            # unit tests.
            '-fno-strict-aliasing',
            # Distutils injects `-fno-strict-overflow` on some platforms (notably
            # macOS). We have observed that this alone can change sensitive long
            # integrations (e.g. Apophis) by O(100 m) because it changes compiler
            # optimizations and therefore floating-point roundoff / adaptive step
            # choices.
            #
            # The `src/Makefile` build (and C unit tests) rely on the compiler
            # default here, which is effectively "strict overflow" at -O3. Add the
            # explicit override so the Python extension matches the Makefile build.
            '-fstrict-overflow',
            '-O3',
            '-std=c99',
            '-fPIC',
            '-D_GNU_SOURCE',
            '-Wpointer-arith',
            ghash_arg,
        ]
    ),
    extra_link_args=extra_link_args,
)

here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(name='assist',
    version='1.2.0',
    description='A library high accuracy ephemeris in REBOUND',
    long_description=long_description,
    long_description_content_type="text/markdown",
    url='https://github.com/matthewholman/assist',
    author='Matthew Holman',
    author_email='mholman@cfa.harvard.edu',
    license='GPL',
    classifiers=[
        # How mature is this project? Common values are
        #   3 - Alpha
        #   4 - Beta
        #   5 - Production/Stable
        'Development Status :: 5 - Production/Stable',

        # Indicate who your project is intended for
        'Intended Audience :: Science/Research',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Build Tools',
        'Topic :: Scientific/Engineering :: Astronomy',

        # Pick your license as you wish (should match "license" above)
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',

        # Specify the Python versions you support here. In particular, ensure
        # that you indicate whether you support Python 2, Python 3 or both.
        'Programming Language :: Python :: 3',
    ],
    keywords='astronomy astrophysics nbody integrator',
    packages=['assist'],
    package_data={"assist": ["assist.h", "py.typed"]},
    cmdclass={'build_ext':build_ext},
    setup_requires=['rebound>=4.4.11,<5.0.0', 'numpy'],
    install_requires=['rebound>=4.4.11,<5.0.0', 'numpy'],
    tests_require=["numpy","matplotlib","rebound>=4.4.11,<5.0.0"],
    test_suite="assist.test",
    ext_modules = [libassistmodule],
    zip_safe=False) 

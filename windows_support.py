"""Windows build support for ASSIST.

ASSIST links against the REBOUND shared library. On Linux and macOS the linker
can consume the ``librebound*.so`` / ``.dylib`` that ships inside the REBOUND
wheel directly. Windows cannot: MSVC links against an *import library*
(``.lib``), and the REBOUND wheel contains only
``librebound.cpXXX-win_amd64.pyd``.

Rather than requiring users to build REBOUND from source, this module
reconstructs the import library from the DLL itself: it reads the PE export
table, writes a ``.def`` file, and hands that to ``lib.exe`` (which ships with
the MSVC toolchain that is already required to compile ASSIST from source).
The result is an ordinary ``.lib`` that resolves to the very same
``librebound*.pyd`` at run time.

Used by ``setup.py`` (the pip build) and by
``dev_tools/build_c_tests_windows.py`` (the C unit tests), so that both link
against REBOUND in exactly the same way.
"""

import glob
import os
import struct
import subprocess


def pe_exported_symbols(dll_path):
    """Return the exported symbol names of a PE image (``.dll`` / ``.pyd``).

    The PE export directory is walked directly so that the build does not
    depend on ``dumpbin.exe``, which is not always on PATH even inside a
    Developer Command Prompt.
    """
    with open(dll_path, 'rb') as fh:
        data = fh.read()

    if data[:2] != b'MZ':
        raise ValueError("%s is not a PE image" % dll_path)

    pe_off = struct.unpack_from('<I', data, 0x3C)[0]
    if data[pe_off:pe_off + 4] != b'PE\0\0':
        raise ValueError("%s has no PE header" % dll_path)

    coff_off = pe_off + 4
    n_sections, = struct.unpack_from('<H', data, coff_off + 2)
    size_opt_header, = struct.unpack_from('<H', data, coff_off + 16)
    opt_off = coff_off + 20

    magic, = struct.unpack_from('<H', data, opt_off)
    if magic == 0x20B:        # PE32+ (64-bit)
        data_dir_off = opt_off + 112
    elif magic == 0x10B:      # PE32 (32-bit)
        data_dir_off = opt_off + 96
    else:
        raise ValueError("unknown optional header magic 0x%X in %s" % (magic, dll_path))

    export_rva, export_size = struct.unpack_from('<II', data, data_dir_off)
    if export_rva == 0 or export_size == 0:
        return []

    # Section table, used to translate RVAs into file offsets.
    sections = []
    sec_off = opt_off + size_opt_header
    for i in range(n_sections):
        base = sec_off + i * 40
        virtual_size, virtual_address, raw_size, raw_ptr = struct.unpack_from('<IIII', data, base + 8)
        sections.append((virtual_address, max(virtual_size, raw_size), raw_ptr))

    def rva_to_offset(rva):
        for virtual_address, size, raw_ptr in sections:
            if virtual_address <= rva < virtual_address + size:
                return raw_ptr + (rva - virtual_address)
        raise ValueError("RVA 0x%X outside every section of %s" % (rva, dll_path))

    exp_off = rva_to_offset(export_rva)
    n_names, = struct.unpack_from('<I', data, exp_off + 0x18)
    names_rva, = struct.unpack_from('<I', data, exp_off + 0x20)
    if n_names == 0:
        return []

    names_off = rva_to_offset(names_rva)
    symbols = []
    for i in range(n_names):
        name_rva, = struct.unpack_from('<I', data, names_off + 4 * i)
        start = rva_to_offset(name_rva)
        end = data.index(b'\0', start)
        symbols.append(data[start:end].decode('ascii'))
    return symbols


def find_rebound_library(rebound_dir):
    """Return the path to the ``librebound*`` DLL shipped in the REBOUND wheel.

    ``rebound_dir`` is the directory of the imported ``rebound`` package; the
    shared library sits next to it in site-packages.
    """
    site_dir = os.path.dirname(rebound_dir)
    candidates = sorted(glob.glob(os.path.join(site_dir, 'librebound*.pyd')))
    candidates += sorted(glob.glob(os.path.join(site_dir, 'librebound*.dll')))
    if not candidates:
        raise RuntimeError(
            "Could not find 'librebound*.pyd' next to the REBOUND package in "
            "%s. Reinstall REBOUND with: pip install \"rebound>=4.4.11,<5.0.0\""
            % site_dir
        )
    return candidates[0]


def find_lib_exe(compiler):
    """Locate ``lib.exe`` via the MSVC compiler object setuptools configured."""
    from distutils.spawn import find_executable

    if not getattr(compiler, 'initialized', False):
        # Populates compiler.cc / compiler.linker / compiler.lib with full
        # paths and puts the MSVC toolchain on PATH for this process.
        compiler.initialize()

    lib_exe = getattr(compiler, 'lib', None)
    if lib_exe and os.path.exists(lib_exe):
        return lib_exe

    found = find_executable(lib_exe or 'lib.exe')
    if found:
        return found

    raise RuntimeError(
        "Could not find 'lib.exe'. Building ASSIST from source on Windows "
        "requires the Visual Studio Build Tools with the 'Desktop development "
        "with C++' workload. See the Windows section of the README."
    )


def build_rebound_import_library(compiler, rebound_dir, output_dir):
    """Create the REBOUND import library in ``output_dir``.

    Returns ``output_dir``, ready to append to ``library_dirs``. The library is
    regenerated only when it is older than the DLL it describes.
    """
    dll_path = find_rebound_library(rebound_dir)
    dll_name = os.path.basename(dll_path)

    # `libraries=['rebound' + suffix]` makes the linker look for
    # `rebound<suffix>.lib`, so drop the leading 'lib' and the '.pyd'.
    stem = os.path.splitext(dll_name)[0]
    if stem.startswith('lib'):
        stem = stem[3:]

    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    lib_path = os.path.join(output_dir, stem + '.lib')
    if os.path.exists(lib_path) and os.path.getmtime(lib_path) >= os.path.getmtime(dll_path):
        print("Reusing REBOUND import library:", lib_path)
        return output_dir

    symbols = pe_exported_symbols(dll_path)
    if not symbols:
        raise RuntimeError("%s exports no symbols; cannot build an import library." % dll_path)

    def_path = os.path.join(output_dir, stem + '.def')
    with open(def_path, 'w') as fh:
        fh.write("LIBRARY %s\n" % dll_name)
        fh.write("EXPORTS\n")
        for name in symbols:
            fh.write("    %s\n" % name)

    machine = 'X64' if struct.calcsize('P') == 8 else 'X86'
    lib_exe = find_lib_exe(compiler)
    cmd = [lib_exe, '/nologo', '/def:' + def_path, '/machine:' + machine, '/out:' + lib_path]
    print("Generating REBOUND import library from", dll_name)
    subprocess.check_call(cmd)

    return output_dir

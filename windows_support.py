"""Windows build support for ASSIST.

ASSIST links against the REBOUND shared library. On Linux and macOS the linker
consumes the ``librebound*.so`` / ``.dylib`` inside the REBOUND wheel directly.
Windows cannot: MSVC links against an *import library* (``.lib``), and the
REBOUND wheel ships only ``librebound.cpXXX-win_amd64.pyd``.

Rather than make users build REBOUND from source, this module reconstructs the
import library from the DLL: read its PE export table, write a ``.def`` file,
and hand that to ``lib.exe`` from the MSVC toolchain a source build already
requires. The result resolves to the same ``librebound*.pyd`` at run time.

Shared by ``setup.py`` and ``dev_tools/build_c_tests_windows.py`` so both link
against REBOUND identically.
"""

import glob
import os
import shutil
import struct
import subprocess


def pe_exported_symbols(dll_path):
    """Return the exported symbol names of a PE image (``.dll`` / ``.pyd``).

    Walks the export directory directly rather than shelling out to
    ``dumpbin.exe``, which is not always on PATH even in a Developer Prompt.
    """
    with open(dll_path, 'rb') as fh:
        data = fh.read()
    if data[:2] != b'MZ':
        raise ValueError("%s is not a PE image" % dll_path)

    pe = struct.unpack_from('<I', data, 0x3C)[0]
    if data[pe:pe + 4] != b'PE\0\0':
        raise ValueError("%s has no PE header" % dll_path)

    n_sections, = struct.unpack_from('<H', data, pe + 6)
    opt_header_size, = struct.unpack_from('<H', data, pe + 20)
    opt = pe + 24
    magic, = struct.unpack_from('<H', data, opt)
    if magic not in (0x10B, 0x20B):          # PE32, PE32+
        raise ValueError("unknown optional header magic 0x%X in %s" % (magic, dll_path))
    export_rva, export_size = struct.unpack_from('<II', data, opt + (112 if magic == 0x20B else 96))
    if not export_rva or not export_size:
        return []

    # Section table, used to translate RVAs into file offsets.
    sections = []
    for i in range(n_sections):
        base = opt + opt_header_size + i * 40
        vsize, vaddr, rawsize, rawptr = struct.unpack_from('<IIII', data, base + 8)
        sections.append((vaddr, max(vsize, rawsize), rawptr))

    def offset_of(rva):
        for vaddr, size, rawptr in sections:
            if vaddr <= rva < vaddr + size:
                return rawptr + (rva - vaddr)
        raise ValueError("RVA 0x%X outside every section of %s" % (rva, dll_path))

    export_dir = offset_of(export_rva)
    n_names, = struct.unpack_from('<I', data, export_dir + 0x18)
    names_rva, = struct.unpack_from('<I', data, export_dir + 0x20)
    names = offset_of(names_rva)

    symbols = []
    for i in range(n_names):
        rva, = struct.unpack_from('<I', data, names + 4 * i)
        start = offset_of(rva)
        symbols.append(data[start:data.index(b'\0', start)].decode('ascii'))
    return symbols


def find_rebound_library(rebound_dir):
    """Path to the ``librebound*`` DLL that ships beside the REBOUND package."""
    site_dir = os.path.dirname(rebound_dir)
    matches = (sorted(glob.glob(os.path.join(site_dir, 'librebound*.pyd')))
               + sorted(glob.glob(os.path.join(site_dir, 'librebound*.dll'))))
    if not matches:
        raise RuntimeError(
            "Could not find 'librebound*.pyd' beside the REBOUND package in %s. "
            "Reinstall REBOUND with: pip install \"rebound>=4.4.11,<5.0.0\"" % site_dir)
    return matches[0]


def rebound_link_name(rebound_dir):
    """Name to pass to the linker, i.e. ``librebound.cp312-win_amd64.pyd`` ->
    ``rebound.cp312-win_amd64``, matching the ``.lib`` built below."""
    stem = os.path.splitext(os.path.basename(find_rebound_library(rebound_dir)))[0]
    return stem[3:] if stem.startswith('lib') else stem


def _find_lib_exe(compiler):
    if not getattr(compiler, 'initialized', False):
        # Populates compiler.lib with a full path and puts MSVC on PATH.
        compiler.initialize()
    lib_exe = getattr(compiler, 'lib', None) or 'lib.exe'
    found = lib_exe if os.path.exists(lib_exe) else shutil.which(lib_exe)
    if not found:
        raise RuntimeError(
            "Could not find 'lib.exe'. Building ASSIST from source on Windows needs "
            "the Visual Studio Build Tools with the 'Desktop development with C++' "
            "workload; see the Windows section of the README.")
    return found


def build_rebound_import_library(compiler, rebound_dir, output_dir):
    """Create the REBOUND import library in ``output_dir`` and return that path,
    ready to append to ``library_dirs``. Rebuilt only when older than the DLL."""
    dll_path = find_rebound_library(rebound_dir)
    dll_name = os.path.basename(dll_path)
    stem = rebound_link_name(rebound_dir)

    os.makedirs(output_dir, exist_ok=True)
    lib_path = os.path.join(output_dir, stem + '.lib')
    if os.path.exists(lib_path) and os.path.getmtime(lib_path) >= os.path.getmtime(dll_path):
        print("Reusing REBOUND import library:", lib_path)
        return output_dir

    symbols = pe_exported_symbols(dll_path)
    if not symbols:
        raise RuntimeError("%s exports no symbols; cannot build an import library." % dll_path)

    def_path = os.path.join(output_dir, stem + '.def')
    with open(def_path, 'w') as fh:
        fh.write("LIBRARY %s\nEXPORTS\n" % dll_name)
        fh.writelines("    %s\n" % name for name in symbols)

    print("Generating REBOUND import library from", dll_name)
    subprocess.check_call([
        _find_lib_exe(compiler), '/nologo', '/def:' + def_path,
        '/machine:' + ('X64' if struct.calcsize('P') == 8 else 'X86'),
        '/out:' + lib_path,
    ])
    return output_dir

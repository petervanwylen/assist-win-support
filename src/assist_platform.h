/**
 * @file    assist_platform.h
 * @brief   Thin platform compatibility layer (POSIX / Win32).
 *
 * @section     LICENSE
 * Copyright (c) 2022 Matthew Holman, Hanno Rein
 *
 * This file is part of ASSIST.
 *
 * ASSIST is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * ASSIST is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with ASSIST. If not, see <http://www.gnu.org/licenses/>.
 *
 * @section     PURPOSE
 *
 * ASSIST reads JPL ephemeris kernels (SPK `.bsp` and ASCII-derived `.440`/
 * `.441`) with low-level file descriptor I/O plus a read-only memory map.
 * That is POSIX-only. This header supplies the handful of pieces MSVC does
 * not provide, so that `spk.c`, `ascii_ephem.c` and `assist.c` can keep using
 * the POSIX spelling on every platform.
 *
 * Three things need care on Windows:
 *
 * 1. Text mode. `open()` on Windows defaults to text mode, which translates
 *    CRLF and stops at ^Z. Ephemeris kernels are binary, so every `open()`
 *    call site passes `O_RDONLY | O_BINARY`. `O_BINARY` is defined to 0 on
 *    POSIX so the same expression compiles everywhere.
 *
 * 2. 64-bit offsets. MSVC's `lseek()` and `struct stat` use a 32-bit `long`,
 *    which silently breaks on kernels larger than 2 GiB (`de441.bsp` is about
 *    3.2 GB). We route through `_lseeki64` and `struct __stat64` instead.
 *
 * 3. Memory mapping. Win32 has no `mmap()`, so we wrap
 *    `CreateFileMapping`/`MapViewOfFile`.
 */
#ifndef _ASSIST_PLATFORM_H
#define _ASSIST_PLATFORM_H

#include <stddef.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>

#if defined(_WIN32)

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <io.h>
#include <basetsd.h>

/* MSVC has no <unistd.h> and no ssize_t. `open`, `read` and `close` are
 * declared in <io.h> under their POSIX names; only `lseek` needs replacing,
 * because the MSVC version takes a 32-bit offset. */
typedef SSIZE_T ssize_t;

#undef lseek
#define lseek(fd, offset, origin) _lseeki64((fd), (__int64)(offset), (origin))

#ifndef O_BINARY
#define O_BINARY _O_BINARY
#endif

/* access() lives in <io.h> under its POSIX name, but the mode constants are
 * not defined by the MSVC headers. */
#ifndef R_OK
#define R_OK 4
#endif
#ifndef W_OK
#define W_OK 2
#endif
#ifndef F_OK
#define F_OK 0
#endif

/* 64-bit file size. MSVC's `struct stat` truncates st_size to 32 bits. */
typedef struct __stat64 assist_stat_t;
#define assist_fstat(fd, buf) _fstat64((fd), (buf))

/* --- minimal read-only mmap() over the Win32 file mapping API --- */

#define PROT_READ   0x1
#define MAP_SHARED  0x01
#define MAP_FAILED  NULL

/**
 * Read-only, whole-file equivalent of mmap(NULL, len, PROT_READ, MAP_SHARED, fd, 0).
 *
 * Returns NULL on failure. ASSIST checks the result against NULL rather than
 * against MAP_FAILED, so MAP_FAILED is defined as NULL above to keep the
 * existing error handling correct on both platforms.
 *
 * The mapping handle is closed immediately: Windows keeps the mapping alive
 * as long as a view of it is open, so nothing extra needs to be tracked and
 * munmap() only needs the base address.
 */
static __inline void* assist_mmap_win32(void* addr, size_t len, int prot, int flags, int fd, long long offset)
{
    HANDLE file_handle;
    HANDLE mapping;
    void* view;

    (void)addr;
    (void)prot;
    (void)flags;

    if (offset != 0 || len == 0) {
        return NULL;   /* ASSIST only ever maps whole files from offset 0. */
    }

    file_handle = (HANDLE)_get_osfhandle(fd);
    if (file_handle == INVALID_HANDLE_VALUE) {
        return NULL;
    }

    /* Passing 0 for the size maps the entire file. */
    mapping = CreateFileMappingW(file_handle, NULL, PAGE_READONLY, 0, 0, NULL);
    if (mapping == NULL) {
        return NULL;
    }

    view = MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, 0);
    CloseHandle(mapping);

    return view;   /* NULL if MapViewOfFile failed. */
}

static __inline int assist_munmap_win32(void* addr, size_t len)
{
    (void)len;
    return UnmapViewOfFile(addr) ? 0 : -1;
}

#define mmap(addr, len, prot, flags, fd, off) assist_mmap_win32((addr), (len), (prot), (flags), (fd), (off))
#define munmap(addr, len)                     assist_munmap_win32((addr), (len))

/* Win32 has no madvise(). Access-pattern hints are advisory only, so the
 * call sites are compiled out via the MADV_RANDOM guard. */

#else  /* POSIX */

#include <sys/mman.h>
#include <unistd.h>

/* Windows needs O_BINARY to avoid CRLF translation; on POSIX it is a no-op. */
#ifndef O_BINARY
#define O_BINARY 0
#endif

typedef struct stat assist_stat_t;
#define assist_fstat(fd, buf) fstat((fd), (buf))

#endif /* _WIN32 */

#endif /* _ASSIST_PLATFORM_H */

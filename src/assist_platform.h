/**
 * @file    assist_platform.h
 * @brief   Platform compatibility shim (POSIX / Win32).
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
 * ASSIST reads JPL ephemeris kernels with file descriptor I/O plus a read-only
 * memory map, which is POSIX-only. This header supplies the few pieces MSVC
 * lacks, so spk.c, ascii_ephem.c and assist.c keep using the POSIX spelling on
 * every platform. On POSIX it is almost a no-op.
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

/* MSVC has no <unistd.h> and no ssize_t. open(), read(), close() and access()
 * are declared in <io.h> under their POSIX names, so only the items below need
 * supplying. */
typedef SSIZE_T ssize_t;

/* Ephemeris kernels are binary, and Windows opens in text mode by default. */
#ifndef O_BINARY
#define O_BINARY _O_BINARY
#endif

/* MSVC declares access() but not its mode constants. */
#ifndef R_OK
#define R_OK 4
#endif

/* MSVC's lseek() offset and struct stat st_size are a 32-bit long, which
 * silently truncates on kernels larger than 2 GiB (de441.bsp is ~3.2 GB). */
#define lseek(fd, offset, origin) _lseeki64((fd), (__int64)(offset), (origin))

typedef struct __stat64 assist_stat_t;
#define assist_fstat(fd, buf) _fstat64((fd), (buf))

/* Minimal read-only mmap() over the Win32 file mapping API. ASSIST maps whole
 * files from offset 0 and compares the result against NULL, so MAP_FAILED is
 * NULL here and the unused arguments are ignored. Win32 keeps a mapping alive
 * while a view of it is open, so the mapping handle can be closed immediately
 * and munmap() needs only the base address.
 *
 * madvise() has no Win32 equivalent; those call sites compile out via the
 * MADV_RANDOM guard. */
#define PROT_READ  0x1
#define MAP_SHARED 0x1
#define MAP_FAILED NULL

static inline void* assist_mmap_win32(void* addr, size_t len, int prot, int flags, int fd, long long offset)
{
    HANDLE file, mapping;
    void* view;

    (void)addr; (void)prot; (void)flags; (void)len;

    if (offset != 0) {
        return NULL;
    }
    file = (HANDLE)_get_osfhandle(fd);
    if (file == INVALID_HANDLE_VALUE) {
        return NULL;
    }
    mapping = CreateFileMappingW(file, NULL, PAGE_READONLY, 0, 0, NULL); /* 0 size maps the whole file */
    if (mapping == NULL) {
        return NULL;
    }
    view = MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, 0);
    CloseHandle(mapping);
    return view; /* NULL if MapViewOfFile failed */
}

static inline int assist_munmap_win32(void* addr, size_t len)
{
    (void)len;
    return UnmapViewOfFile(addr) ? 0 : -1;
}

#define mmap(addr, len, prot, flags, fd, off) assist_mmap_win32((addr), (len), (prot), (flags), (fd), (off))
#define munmap(addr, len)                     assist_munmap_win32((addr), (len))

#else /* POSIX */

#include <sys/mman.h>
#include <unistd.h>

#ifndef O_BINARY
#define O_BINARY 0 /* Windows-only flag; a no-op here. */
#endif

typedef struct stat assist_stat_t;
#define assist_fstat(fd, buf) fstat((fd), (buf))

#endif /* _WIN32 */

#endif /* _ASSIST_PLATFORM_H */

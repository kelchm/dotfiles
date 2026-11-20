#!/usr/bin/env python3
"""Read-only APFS storage measurement for the disk-cleanup skill (macOS only).

`volume` reports container capacity and snapshots. `footprint` ranks live
roots by mapped file data. `scan` investigates a specific deletion set with lstat,
getattrlist (ATTR_CMNEXT_PRIVATESIZE, EXT_FLAGS), SEEK_DATA/SEEK_HOLE and
F_LOG2PHYS_EXT on data and resource forks. It never writes, flushes, deletes
or materializes files. Field meanings are in references/macos.md.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import fcntl
import json
import os
import platform
import plistlib
import stat
import struct
import subprocess
import sys
import time

SCHEMA = 'disk-cleanup/apfs-measure/2'

# <sys/fcntl.h>, <sys/attr.h>, <sys/stat.h>, <sys/xattr.h>, <sys/resource.h>
F_LOG2PHYS_EXT = 65
LOG2PHYS = struct.Struct('=Iqq')  # pack(4): flags, contigbytes, devoffset
ATTR_CMN_RETURNED_ATTRS = 0x80000000
ATTR_FILE_LINKCOUNT = 0x00000001
ATTR_FILE_RSRCLENGTH = 0x00001000
ATTR_CMNEXT_PRIVATESIZE = 0x00000008
ATTR_CMNEXT_EXT_FLAGS = 0x00000200
FSOPT_NOFOLLOW, FSOPT_PACK_INVAL_ATTRS, FSOPT_ATTR_CMN_EXTENDED = 0x1, 0x8, 0x20
ATTR_REPLY = struct.Struct('=I5IqqQ')  # length, returned attribute_set_t, rsrc length, private size, ext flags
LINK_COUNT_REPLY = struct.Struct('=I5II')
MAX_STAT_LINKS = (1 << 16) - 1  # Darwin's nlink_t
EF_MAY_SHARE_BLOCKS, EF_NO_XATTRS, EF_IS_PURGEABLE = 0x1, 0x2, 0x8
UF_COMPRESSED, SF_DATALESS = 0x20, 0x40000000
XATTR_NOFOLLOW = 0x1
RESOURCE_FORK_XATTR = b'com.apple.ResourceFork'

ALL = ('logical_bytes', 'allocated_bytes', 'unique_physical_bytes', 'private_bytes_sum',
       'exclusive_within_coverage_bytes', 'reclaim_if_deleted_bytes', 'xattr_bytes')
RECLAIM = ('exclusive_within_coverage_bytes', 'reclaim_if_deleted_bytes')
MAPPING = ('unique_physical_bytes',) + RECLAIM
PRIVATE = ('private_bytes_sum', 'reclaim_if_deleted_bytes')
OTHER, MULTI = -2, -1  # inode labels besides "every link is in candidate i"
COMPRESSED, DATALESS, INLINE = 0x100, 0x200, 0x400  # Inode.flags bits alongside the EF_* flags kept

NOT_MEASURED = [
    'Filesystem metadata: inodes, directory records, inline extended attributes, extent trees.',
    'Blocks retained only by snapshots of deleted or rewritten files.',
    'Physical storage for extended attributes other than resource forks.',
    'File data outside the measured roots.',
]


class AttrList(ctypes.Structure):
    _fields_ = [('bitmapcount', ctypes.c_ushort), ('reserved', ctypes.c_uint16)] + [
        (name, ctypes.c_uint32) for name in ('commonattr', 'volattr', 'dirattr', 'fileattr', 'forkattr')]


class StatFS(ctypes.Structure):
    _fields_ = [('f_bsize', ctypes.c_uint32), ('f_iosize', ctypes.c_int32), ('f_blocks', ctypes.c_uint64),
                ('f_bfree', ctypes.c_uint64), ('f_bavail', ctypes.c_uint64), ('f_files', ctypes.c_uint64),
                ('f_ffree', ctypes.c_uint64), ('f_fsid', ctypes.c_int32 * 2), ('f_owner', ctypes.c_uint32),
                ('f_type', ctypes.c_uint32), ('f_flags', ctypes.c_uint32), ('f_fssubtype', ctypes.c_uint32),
                ('f_fstypename', ctypes.c_char * 16), ('f_mntonname', ctypes.c_char * 1024),
                ('f_mntfromname', ctypes.c_char * 1024), ('f_flags_ext', ctypes.c_uint32),
                ('f_reserved', ctypes.c_uint32 * 7)]


libc = ctypes.CDLL(None, use_errno=True)
libc.getattrlist.argtypes = [ctypes.c_char_p, ctypes.POINTER(AttrList), ctypes.c_void_p, ctypes.c_size_t,
                            ctypes.c_uint32]
libc.listxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int]
libc.listxattr.restype = ctypes.c_ssize_t
libc.getxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32,
                          ctypes.c_int]
libc.getxattr.restype = ctypes.c_ssize_t
try:  # Intel builds export the 64-bit-inode layout under a suffixed name.
    _statfs = libc['statfs$INODE64']
except AttributeError:
    _statfs = libc['statfs']
_statfs.argtypes = [ctypes.c_char_p, ctypes.POINTER(StatFS)]


def errname(code):
    return errno.errorcode.get(code, str(code))


def statfs(path):
    buf = StatFS()
    if _statfs(os.fsencode(path), ctypes.byref(buf)) != 0:
        raise OSError(ctypes.get_errno(), 'statfs failed', path)
    return buf


def file_attributes(path):
    """(resource fork length, private size, ext flags); None where the volume did not return one."""
    request = AttrList(5, 0, ATTR_CMN_RETURNED_ATTRS, 0, 0, ATTR_FILE_RSRCLENGTH,
                       ATTR_CMNEXT_PRIVATESIZE | ATTR_CMNEXT_EXT_FLAGS)
    buf = ctypes.create_string_buffer(ATTR_REPLY.size)
    if libc.getattrlist(os.fsencode(path), ctypes.byref(request), buf, ATTR_REPLY.size,
                        FSOPT_NOFOLLOW | FSOPT_PACK_INVAL_ATTRS | FSOPT_ATTR_CMN_EXTENDED) != 0:
        return None, None, None
    _, _, _, _, file_ret, fork_ret, rsrc, private, ext = ATTR_REPLY.unpack(buf.raw)
    return (rsrc if file_ret & ATTR_FILE_RSRCLENGTH else None,
            private if fork_ret & ATTR_CMNEXT_PRIVATESIZE else None,
            ext if fork_ret & ATTR_CMNEXT_EXT_FLAGS else None)


def full_link_count(path):
    """The 32-bit APFS link count, for cases where stat's 16-bit field saturates."""
    request = AttrList(5, 0, ATTR_CMN_RETURNED_ATTRS, 0, 0, ATTR_FILE_LINKCOUNT, 0)
    buf = ctypes.create_string_buffer(LINK_COUNT_REPLY.size)
    if libc.getattrlist(os.fsencode(path), ctypes.byref(request), buf, LINK_COUNT_REPLY.size,
                        FSOPT_NOFOLLOW | FSOPT_PACK_INVAL_ATTRS) != 0:
        return None
    _, _, _, _, file_ret, _, count = LINK_COUNT_REPLY.unpack(buf.raw)
    return count if file_ret & ATTR_FILE_LINKCOUNT and count >= MAX_STAT_LINKS else None


def xattr_bytes(path):
    """Logical size of extended attributes other than the resource fork, or None if unreadable."""
    raw = os.fsencode(path)
    size = libc.listxattr(raw, None, 0, XATTR_NOFOLLOW)
    if size <= 0:
        return 0 if size == 0 else None
    names = ctypes.create_string_buffer(size)
    size = libc.listxattr(raw, names, size, XATTR_NOFOLLOW)
    if size < 0:
        return None
    total = 0
    for name in names.raw[:size].split(b'\0'):
        if name and name != RESOURCE_FORK_XATTR:
            length = libc.getxattr(raw, name, None, 0, 0, XATTR_NOFOLLOW)
            if length < 0:
                return None
            total += length
    return total


def map_fork(fd, size, bsize):
    """Device ranges holding one fork's data. Holes are skipped; unallocated or unmappable data is a gap."""
    ranges, gap, pos = [], None, 0
    while pos < size:
        try:
            start = os.lseek(fd, pos, os.SEEK_DATA)
        except OSError as e:
            if e.errno == errno.ENXIO:  # only holes remain
                break
            return ranges, 'seek_failed:' + errname(e.errno)
        if start >= size:
            break
        try:
            end = min(os.lseek(fd, start, os.SEEK_HOLE), size)
        except OSError as e:
            return ranges, 'seek_failed:' + errname(e.errno)
        if end <= start:
            return ranges, 'seek_failed:empty_region'
        offset = start
        while offset < end:
            try:
                _, contig, device = LOG2PHYS.unpack(
                    fcntl.fcntl(fd, F_LOG2PHYS_EXT, LOG2PHYS.pack(0, end - offset, offset)))
            except OSError as e:
                return ranges, 'mapping_failed:' + errname(e.errno)
            if contig <= 0:
                return ranges, 'mapping_failed:empty'
            contig = min(contig, end - offset)
            if device < 0:  # data without a device address yet, such as delayed allocation
                gap = gap or 'unallocated_range'
            else:
                ranges.append((device - device % bsize, -(-(device + contig) // bsize) * bsize))
            offset += contig
        pos = end
    return ranges, gap


def map_preallocated_tail(fd, size, bsize, missing):
    """APFS can reserve mapped blocks beyond EOF, which SEEK_DATA will not visit."""
    offset = -(-size // bsize) * bsize
    ranges = []
    while missing > 0:
        try:
            _, contig, device = LOG2PHYS.unpack(
                fcntl.fcntl(fd, F_LOG2PHYS_EXT, LOG2PHYS.pack(0, missing, offset)))
        except OSError:
            break  # The allocation check will report any bytes left without a map.
        if contig <= 0:
            break
        if device >= 0:
            lo = device - device % bsize
            hi = -(-(device + contig) // bsize) * bsize
            ranges.append((lo, hi))
            missing -= hi - lo
        offset += contig
    return ranges


def merged_length(ranges):
    total, cur_lo, cur_hi = 0, None, None
    for lo, hi in sorted(ranges):
        if cur_hi is None or lo > cur_hi:
            if cur_hi is not None:
                total += cur_hi - cur_lo
            cur_lo, cur_hi = lo, hi
        else:
            cur_hi = max(cur_hi, hi)
    return total + (cur_hi - cur_lo if cur_hi is not None else 0)


class Inode:
    __slots__ = ('nlink', 'links', 'logical', 'allocated', 'private', 'flags', 'xattr', 'data_mapped', 'gap',
                 'private_partial', 'xattr_failed', 'allocation_without_map')

    def __init__(self, st):
        self.nlink, self.links = st.st_nlink, []
        self.allocated = st.st_blocks * 512
        self.logical, self.private, self.flags, self.xattr, self.data_mapped = st.st_size, None, 0, 0, 0
        self.gap, self.private_partial, self.xattr_failed = None, False, False
        self.allocation_without_map = 0


class Group:
    def __init__(self, kind, path, given):
        self.kind, self.path, self.given = kind, path, given
        self.directories = self.symlinks = self.other = 0
        self.entry_gaps = {}  # reason -> count
        self.samples = {}  # reason -> paths

    def sample(self, reason, path, limit):
        paths = self.samples.setdefault(reason, [])
        if len(paths) < limit:
            paths.append(path)


def same_or_inside(path, root):
    return path == root or path.startswith(root.rstrip('/') + '/')


class Scan:
    def __init__(self, candidates, references, samples, footprint=False):
        self.groups = [Group('candidate', p, g) for g, p in candidates] + [
            Group('reference', p, g) for g, p in references]
        self.n = len(candidates)
        self.limit = samples
        self.footprint = footprint
        self.inodes, self.index = [], {}
        self.extents = {}  # st_dev -> [(lo, hi, inode * 2 + fork)]

    def run(self):
        candidate_dirs, candidate_paths = set(), {g.path for g in self.groups[:self.n]}
        for group in self.groups[:self.n]:
            st = os.lstat(group.path)
            if stat.S_ISDIR(st.st_mode):
                candidate_dirs.add((st.st_dev, st.st_ino))
        for gid, group in enumerate(self.groups):
            skip = (set(), set()) if gid < self.n else (candidate_dirs, candidate_paths)
            self.walk(gid, group, *skip)

    def walk(self, gid, group, skip_dirs, skip_paths):
        st = os.lstat(group.path)
        fs = statfs(group.path)
        group.volume = fs.f_mntonname.decode()
        if fs.f_fstypename != b'apfs':
            self.entry_gap(group, 'not_apfs', group.path)
            return
        bsize, root_dev = fs.f_bsize, st.st_dev
        stack = []
        self.visit(gid, group, group.path, st, root_dev, bsize, stack, skip_dirs, skip_paths)
        while stack:
            directory = stack.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        try:
                            st = entry.stat(follow_symlinks=False)
                        except OSError as e:
                            self.entry_gap(group, 'lstat_failed:' + errname(e.errno), entry.path)
                            continue
                        self.visit(gid, group, entry.path, st, root_dev, bsize, stack, skip_dirs, skip_paths)
            except OSError as e:
                self.entry_gap(group, 'unreadable_directory:' + errname(e.errno), directory)

    def entry_gap(self, group, reason, path):
        group.entry_gaps[reason] = group.entry_gaps.get(reason, 0) + 1
        group.sample(reason, path, self.limit)

    def visit(self, gid, group, path, st, root_dev, bsize, stack, skip_dirs, skip_paths):
        if path in skip_paths or (stat.S_ISDIR(st.st_mode) and (st.st_dev, st.st_ino) in skip_dirs):
            return
        if stat.S_ISDIR(st.st_mode):
            if st.st_dev != root_dev:
                self.entry_gap(group, 'other_filesystem', path)
                return
            group.directories += 1
            if st.st_flags & SF_DATALESS:
                self.entry_gap(group, 'dataless_directory', path)
                return
            stack.append(path)
        elif stat.S_ISREG(st.st_mode):
            key = (st.st_dev, st.st_ino)
            iid = self.index.get(key)
            if iid is None:
                iid = self.index[key] = len(self.inodes)
                inode = Inode(st)
                if inode.nlink == MAX_STAT_LINKS:
                    inode.nlink = full_link_count(path)
                self.inodes.append(inode)
                self.measure(iid, inode, path, st, bsize)
                for reason in (inode.gap, 'private_size_unavailable' if inode.private is None else None,
                               'private_excludes_resource_fork' if inode.private_partial else None,
                               'xattr_list_failed' if inode.xattr_failed else None):
                    if reason:
                        group.sample(reason, path, self.limit)
            self.inodes[iid].links.append(gid)
        elif stat.S_ISLNK(st.st_mode):
            group.symlinks += 1
        else:
            group.other += 1

    def measure(self, iid, inode, path, st, bsize):
        rsrc, inode.private, ext = file_attributes(path)
        ext = ext or 0
        compressed = bool(st.st_flags & UF_COMPRESSED)
        inode.logical += rsrc or 0
        inode.flags = (ext & (EF_MAY_SHARE_BLOCKS | EF_IS_PURGEABLE) | (COMPRESSED if compressed else 0)
                       | (DATALESS if st.st_flags & SF_DATALESS else 0))
        if not self.footprint and not ext & EF_NO_XATTRS:
            size = xattr_bytes(path)
            inode.xattr, inode.xattr_failed = size or 0, size is None
        if st.st_flags & SF_DATALESS:  # opening could download it; any local blocks stay unmapped
            if inode.allocated:
                inode.gap = 'dataless'
            return
        has_rsrc = compressed or bool(rsrc)
        inode.private_partial = has_rsrc
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        except OSError as e:
            inode.gap = 'open_failed:' + errname(e.errno)
            return
        try:
            before = os.fstat(fd)
            if (before.st_dev, before.st_ino) != (st.st_dev, st.st_ino):
                inode.gap = 'replaced_during_scan'
                return
            data, resource = [], []
            gap = 'resource_fork_size_unavailable' if rsrc is None else None
            if not compressed:  # compressed data lives in the resource fork or inline in metadata
                data, data_gap = map_fork(fd, before.st_size, bsize)
                gap = gap or data_gap
            if has_rsrc:
                try:
                    rfd = os.open(path + '/..namedfork/rsrc', os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
                except OSError as e:
                    rgap = 'resource_fork_open_failed:' + errname(e.errno)
                    if compressed and e.errno == errno.ENOENT:  # data is inline in the decmpfs attribute
                        inode.flags |= INLINE
                        rgap = 'compressed_without_resource_stream' if inode.allocated else None
                else:
                    try:
                        if os.fstat(rfd).st_ino != st.st_ino:
                            rgap = 'replaced_during_scan'
                        else:
                            resource, rgap = map_fork(rfd, os.fstat(rfd).st_size, bsize)
                    finally:
                        os.close(rfd)
                gap = gap or rgap
            inode.data_mapped = merged_length(data)
            mapped = inode.data_mapped + merged_length(resource)
            if not gap and not compressed and not has_rsrc and mapped < inode.allocated:
                tail = map_preallocated_tail(fd, before.st_size, bsize, inode.allocated - mapped)
                if tail:
                    data.extend(tail)
                    inode.data_mapped = mapped = merged_length(data)
            after = os.fstat(fd)
            if (after.st_size, after.st_blocks, after.st_mtime_ns, after.st_ctime_ns) != (
                    st.st_size, st.st_blocks, st.st_mtime_ns, st.st_ctime_ns):
                inode.gap = 'changed_during_scan'
                return
            if mapped > inode.allocated:
                inode.gap = 'mapped_exceeds_allocation'
                return
            inode.allocation_without_map = inode.allocated - mapped
            if inode.allocation_without_map:
                gap = gap or 'allocated_blocks_not_mapped'
            inode.gap = gap
            sink = self.extents.setdefault(st.st_dev, [])
            sink.extend((lo, hi, iid * 2) for lo, hi in data)
            sink.extend((lo, hi, iid * 2 + 1) for lo, hi in resource)
        finally:
            os.close(fd)

    def label(self, inode):
        """Candidate index when every link is inside one candidate; MULTI for several; otherwise OTHER."""
        if len(inode.links) != inode.nlink or any(g >= self.n for g in inode.links):
            return OTHER
        first = inode.links[0]
        return first if all(g == first for g in inode.links) else MULTI

    def sweep(self, labels):
        """Attribute every mapped device block to the groups and inodes that reference it."""
        n, groups = self.n, len(self.groups)
        presence = [frozenset(inode.links) for inode in self.inodes]
        out = {'physical': [0] * groups, 'exclusive': [0] * n, 'shared_refs': [0] * groups,
               'all_physical': 0, 'all_exclusive': 0, 'all_shared_refs': 0, 'between': 0}
        shared_data = {}
        for ranges in self.extents.values():
            events = []
            for lo, hi, key in ranges:
                events.append((lo, 1, key))
                events.append((hi, -1, key))
            events.sort()
            keys, inodes, present, active_groups = {}, {}, [0] * groups, set()
            cand_label, other, active, prev = [0] * n, 0, 0, None
            for pos, delta, key in events:
                if active and pos != prev:
                    self.segment(out, shared_data, pos - prev, keys, active, active_groups, cand_label, other)
                prev = pos
                count = keys.get(key, 0) + delta
                if count:
                    keys[key] = count
                else:
                    del keys[key]
                if count != (1 if delta > 0 else 0):
                    continue
                iid = key >> 1
                icount = inodes.get(iid, 0) + delta
                if icount:
                    inodes[iid] = icount
                else:
                    del inodes[iid]
                if icount != (1 if delta > 0 else 0):
                    continue
                active += delta
                for g in presence[iid]:
                    present[g] += delta
                    if present[g]:
                        active_groups.add(g)
                    else:
                        active_groups.discard(g)
                lab = labels[iid]
                if lab >= 0:
                    cand_label[lab] += delta
                elif lab == OTHER:
                    other += delta
        return out, shared_data

    def segment(self, out, shared_data, length, keys, active, active_groups, cand_label, other):
        cands = [g for g in active_groups if g < self.n]
        refs = len(cands) < len(active_groups)
        for g in active_groups:
            out['physical'][g] += length
        if cands:
            out['all_physical'] += length
            if len(cands) > 1:
                out['between'] += length
            if refs:
                out['all_shared_refs'] += length
                for g in active_groups:
                    out['shared_refs'][g] += length
            if not other:
                out['all_exclusive'] += length
            if len(cands) == 1 and cand_label[cands[0]] == active:
                out['exclusive'][cands[0]] += length
        if active > 1 and not self.footprint:
            for key in keys:
                if not key & 1:
                    shared_data[key >> 1] = shared_data.get(key >> 1, 0) + length

    def report(self):
        labels = [self.label(inode) for inode in self.inodes]
        out, shared_data = self.sweep(labels)
        totals = [self.blank() for _ in self.groups]
        combined = self.blank()
        for iid, inode in enumerate(self.inodes):
            lab = labels[iid]
            members = sorted(set(inode.links))
            retained = 0
            if (not self.footprint and lab != OTHER and inode.private is not None
                    and inode.gap is None and inode.data_mapped):
                retained = max(0, inode.data_mapped - inode.private - shared_data.get(iid, 0))
            for g in members:
                self.add(totals[g], inode, lab == g, retained)
            if lab != OTHER or any(g < self.n for g in members):
                self.add(combined, inode, lab != OTHER, retained)
        results = []
        for gid, group in enumerate(self.groups):
            t = totals[gid]
            entry = {'path': group.path}
            if group.given != group.path:
                entry['given_path'] = group.given
            entry['volume'] = group.volume
            entry.update(self.measures(t, out['physical'][gid]))
            if group.kind == 'candidate':
                entry['shared_with_references_bytes'] = out['shared_refs'][gid]
                entry.update(self.reclaim(t, out['exclusive'][gid]))
            else:
                entry['shared_with_candidates_bytes'] = out['shared_refs'][gid]
            entry['counts'] = self.counts(t, group.directories, group.symlinks, group.other)
            entry.update(self.gaps(t, group.entry_gaps, group.samples, group.kind == 'candidate'))
            if group.kind == 'candidate':
                self.check_bounds(entry)
            results.append((group.kind, entry))
        candidates = [e for kind, e in results if kind == 'candidate']
        cand_groups = self.groups[:self.n]
        entry_gaps, samples = {}, {}
        for group in cand_groups:
            for reason, count in group.entry_gaps.items():
                entry_gaps[reason] = entry_gaps.get(reason, 0) + count
            for reason, paths in group.samples.items():
                samples.setdefault(reason, []).extend(paths)
        samples = {k: v[:self.limit] for k, v in samples.items()}
        all_entry = self.measures(combined, out['all_physical'])
        all_entry['shared_between_candidates_bytes'] = out['between']
        all_entry['shared_with_references_bytes'] = out['all_shared_refs']
        all_entry.update(self.reclaim(combined, out['all_exclusive']))
        all_entry['counts'] = self.counts(combined, *[sum(getattr(g, a) for g in cand_groups)
                                                      for a in ('directories', 'symlinks', 'other')])
        all_entry.update(self.gaps(combined, entry_gaps, samples, True))
        self.check_bounds(all_entry)
        return candidates, all_entry, [e for kind, e in results if kind == 'reference']

    @staticmethod
    def check_bounds(entry):
        bounds = entry['reclaim_if_deleted_bytes']
        if bounds['at_most'] < bounds['at_least']:
            entry['gaps'].append({'reason': 'inconsistent_reclaim_bounds',
                                  'affects': ['reclaim_if_deleted_bytes']})
            entry['complete']['reclaim_if_deleted_bytes'] = False
            bounds['at_least'] = None
        if not entry['complete']['reclaim_if_deleted_bytes']:
            bounds['at_most'] = None

    @staticmethod
    def blank():
        counters = ('files', 'logical', 'allocated', 'private', 'xattr', 'hardlinked', 'links_outside', 'compressed',
                    'dataless', 'inline', 'rsrc', 'may_share', 'purgeable', 'purgeable_allocated', 'at_least',
                    'retained', 'allocation_without_map')
        return {**dict.fromkeys(counters, 0), 'gaps': {}}

    @staticmethod
    def add(t, inode, owned, retained):
        t['files'] += 1
        t['logical'] += inode.logical
        t['allocated'] += inode.allocated
        t['xattr'] += inode.xattr
        t['allocation_without_map'] += inode.allocation_without_map
        t['private'] += inode.private or 0
        t['hardlinked'] += inode.nlink is None or inode.nlink > 1
        t['links_outside'] += inode.nlink is not None and len(inode.links) < inode.nlink
        t['compressed'] += bool(inode.flags & COMPRESSED)
        t['dataless'] += bool(inode.flags & DATALESS)
        t['inline'] += bool(inode.flags & INLINE)
        t['rsrc'] += inode.private_partial
        t['may_share'] += bool(inode.flags & EF_MAY_SHARE_BLOCKS)
        if inode.flags & EF_IS_PURGEABLE:
            t['purgeable'] += 1
            t['purgeable_allocated'] += inode.allocated
        if owned:
            if inode.gap is None and inode.private is not None and inode.private <= inode.data_mapped:
                t['at_least'] += inode.private
            t['retained'] += retained
        gaps = []
        if inode.gap:
            affects = (ALL if inode.gap in ('changed_during_scan', 'replaced_during_scan') else
                       ('logical_bytes',) + MAPPING if inode.gap == 'resource_fork_size_unavailable' else MAPPING)
            gaps.append((inode.gap, affects))
        if inode.private is None:
            gaps.append(('private_size_unavailable', PRIVATE))
        if inode.private is not None and inode.gap is None and inode.private > inode.data_mapped:
            gaps.append(('private_exceeds_mapped_data', PRIVATE))
        if inode.private_partial:
            gaps.append(('private_excludes_resource_fork', ('private_bytes_sum',)))
        if inode.xattr_failed:
            gaps.append(('xattr_list_failed', ('xattr_bytes',)))
        if inode.nlink is None:
            gaps.append(('link_count_unavailable', RECLAIM))
        elif len(inode.links) > inode.nlink:
            gaps.append(('path_aliasing', ALL))
        for reason, affects in gaps:
            gap = t['gaps'].setdefault(reason, {'files': 0, 'allocated_bytes': 0, 'affects': affects})
            gap['files'] += 1
            gap['allocated_bytes'] += inode.allocated

    @staticmethod
    def measures(t, physical):
        return {'logical_bytes': t['logical'], 'allocated_bytes': t['allocated'], 'unique_physical_bytes': physical,
                'private_bytes_sum': t['private'], 'xattr_bytes': t['xattr'],
                'allocation_without_map_bytes': t['allocation_without_map']}

    @staticmethod
    def reclaim(t, exclusive):
        return {'exclusive_within_coverage_bytes': exclusive,
                'retained_elsewhere_bytes': t['retained'],
                'reclaim_if_deleted_bytes': {'at_least': t['at_least'],
                                             'at_most': exclusive - t['retained']}}

    @staticmethod
    def counts(t, directories, symlinks, other):
        return {'files': t['files'], 'directories': directories, 'symlinks': symlinks, 'other': other,
                'hardlinked_files': t['hardlinked'], 'files_with_links_outside_roots': t['links_outside'],
                'files_that_may_share_blocks': t['may_share'], 'compressed_files': t['compressed'],
                'compressed_in_metadata_files': t['inline'], 'dataless_files': t['dataless'],
                'files_with_resource_or_compressed_stream': t['rsrc'], 'purgeable_files': t['purgeable'],
                'purgeable_allocated_bytes': t['purgeable_allocated']}

    @staticmethod
    def gaps(t, entry_gaps, samples, candidate):
        measures = ALL if candidate else [m for m in ALL if m not in RECLAIM]
        gaps = [{'reason': r, 'entries': c, 'affects': list(measures), 'samples': samples.get(r, [])}
                for r, c in sorted(entry_gaps.items())]
        for reason, gap in sorted(t['gaps'].items()):
            gaps.append({'reason': reason, 'files': gap['files'], 'allocated_bytes': gap['allocated_bytes'],
                         'affects': [m for m in gap['affects'] if m in measures],
                         'samples': samples.get(reason, [])})
        affected = {m for gap in gaps for m in gap['affects']}
        return {'complete': {m: m not in affected for m in measures}, 'gaps': gaps}


def run(argv):
    try:
        return subprocess.run(argv, capture_output=True, timeout=60, check=True).stdout
    except (OSError, subprocess.SubprocessError) as e:
        return e


IMPORTANT_USE_JXA = '''ObjC.import("Foundation");
function run(argv) {
  var keys = ["NSURLVolumeAvailableCapacityForImportantUsageKey", "NSURLVolumeAvailableCapacityForOpportunisticUsageKey"];
  var values = $.NSURL.fileURLWithPath(argv[0]).resourceValuesForKeysError($(keys), null);
  var out = {};
  keys.forEach(function (k) { var v = values.isNil() ? null : values.objectForKey(k);
    out[k] = (v === null || v.isNil()) ? null : String(v.longLongValue); });
  return JSON.stringify(out);
}'''


def volume_context(path):
    fs = statfs(path)
    mount = fs.f_mntonname.decode()
    ctx = {'mount_point': mount, 'device': fs.f_mntfromname.decode(), 'filesystem': fs.f_fstypename.decode(),
           'block_size': fs.f_bsize, 'volume_name': None, 'container': None, 'container_size_bytes': None,
           'container_free_bytes': None, 'important_use_available_bytes': None,
           'opportunistic_use_available_bytes': None, 'snapshots': None, 'snapshot_retained_bytes': None}
    unavailable = {'snapshot_retained_bytes': 'The built-in commands used here do not report it. Use Disk Utility or a dedicated '
                                              'snapshot tool; never derive it from available minus free space.'}
    info = run(['/usr/sbin/diskutil', 'info', '-plist', mount])
    if isinstance(info, bytes):
        info = plistlib.loads(info)
        ctx['volume_name'] = info.get('VolumeName')
        ctx['container'] = info.get('APFSContainerReference')
        ctx['container_size_bytes'] = info.get('APFSContainerSize')
        ctx['container_free_bytes'] = info.get('APFSContainerFree')
    for key in ('container', 'container_size_bytes', 'container_free_bytes'):
        if ctx[key] is None:
            unavailable[key] = 'diskutil info did not report it' + ('' if isinstance(info, dict) else f': {info}')
    capacity = run(['/usr/bin/osascript', '-l', 'JavaScript', '-e', IMPORTANT_USE_JXA, mount])
    try:
        values = json.loads(capacity)
        for field, usage in (('important_use_available_bytes', 'Important'),
                             ('opportunistic_use_available_bytes', 'Opportunistic')):
            value = values.get(f'NSURLVolumeAvailableCapacityFor{usage}UsageKey')
            ctx[field] = int(value) if value is not None else None
    except (TypeError, ValueError):
        pass
    for field in ('important_use_available_bytes', 'opportunistic_use_available_bytes'):
        if ctx[field] == 0 and ctx['container_free_bytes']:  # seen on hidden disk images
            ctx[field] = None
            unavailable[field] = 'macOS reported 0 although the container has free space'
        elif ctx[field] is None:
            unavailable[field] = 'NSURL volume capacity query failed: ' + str(capacity)[:200]
    snapshots = run(['/usr/sbin/diskutil', 'apfs', 'listSnapshots', '-plist', mount])
    if isinstance(snapshots, bytes):
        ctx['snapshots'] = [{'name': s.get('SnapshotName'), 'xid': s.get('SnapshotXID'), 'purgeable': s.get('Purgeable'),
                             'limits_container_shrink': s.get('LimitingContainerShrink')}
                            for s in plistlib.loads(snapshots).get('Snapshots', [])]
    else:
        unavailable['snapshots'] = f'diskutil apfs listSnapshots failed: {snapshots}'
    if ctx['container']:
        listing = run(['/usr/sbin/diskutil', 'apfs', 'list', '-plist', ctx['container']])
        if isinstance(listing, bytes):
            containers = plistlib.loads(listing).get('Containers', [])
            for container in containers:
                if container.get('ContainerReference') == ctx['container']:
                    ctx['container_volumes'] = [
                        {'name': v.get('Name'), 'device': v.get('DeviceIdentifier'), 'roles': v.get('Roles', []),
                         'mount_point': v.get('MountPoint'), 'used_bytes': v.get('CapacityInUse')}
                        for v in container.get('Volumes', [])]
                    break
    ctx['unavailable'] = unavailable
    return ctx


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S%z')


def header(command):
    return {'schema': SCHEMA, 'command': command, 'measured_at': now(),
            'host': {'os': 'macOS ' + platform.mac_ver()[0], 'machine': platform.machine()}}


def resolve(paths, kind):
    resolved = []
    for given in paths:
        path = os.path.realpath(given)
        if not os.path.lexists(path):
            sys.exit(f'apfs-measure: {kind} does not exist: {given}')
        resolved.append((given, path))
    return resolved


def scan(args):
    candidates = resolve(args.candidates, 'candidate')
    references = resolve(args.reference, 'reference')
    roots = [('candidate', p) for _, p in candidates] + [('reference', p) for _, p in references]
    for i, (kind_a, a) in enumerate(roots):
        for kind_b, b in roots[i + 1:]:
            outer, inner = (a, b) if same_or_inside(b, a) else (b, a) if same_or_inside(a, b) else (None, None)
            if outer is None:
                continue
            outer_kind = kind_a if outer == a else kind_b
            inner_kind = kind_b if outer == a else kind_a
            if not (outer_kind == 'reference' and inner_kind == 'candidate' and outer != inner):
                sys.exit(f'apfs-measure: {inner_kind} {inner} overlaps {outer_kind} {outer}. Only a reference '
                         'root may contain candidates.')
    # Never trigger downloads of dataless (cloud placeholder) files. Their flag is also checked before opening.
    if libc.setiopolicy_np(3, 0, 1) != 0:  # VFS_MATERIALIZE_DATALESS_FILES, PROCESS, OFF
        sys.exit('apfs-measure: cannot disable dataless file materialization')
    started = time.monotonic()
    result = header(args.command)
    result['method'] = ('lstat; getattrlist; SEEK_DATA/SEEK_HOLE; F_LOG2PHYS_EXT on data and resource '
                        'forks with an allocation check and preallocation probe; union of device ranges per volume')
    result['dataless_materialization_disabled'] = True
    result['not_measured'] = NOT_MEASURED
    footprint = args.command == 'footprint'
    measure = Scan(candidates, references, args.samples, footprint=footprint)
    if not footprint:
        result['volumes'] = [volume_context(p) for p in {statfs(p).f_mntonname.decode(): p for _, p in roots}.values()]
    measure.run()
    rows, combined, refs = measure.report()
    if footprint:
        result['roots'] = sorted(map(footprint_row, rows),
                                 key=lambda row: (not row['complete'], -row['mapped_file_data_bytes']))
        result['combined'] = footprint_row(combined)
        result['shared_between_roots_bytes'] = combined['shared_between_candidates_bytes']
    else:
        result.update(candidates=rows, combined=combined, references=refs)
    result['finished_at'] = now()
    result['duration_seconds'] = round(time.monotonic() - started, 3)
    return result


def footprint_row(entry):
    field = 'unique_physical_bytes'
    row = {key: entry[key] for key in ('path', 'volume') if key in entry}
    row['mapped_file_data_bytes'] = entry[field]
    row['files_seen'] = entry['counts']['files']
    row['complete'] = entry['complete'][field]
    row['allocation_without_map_bytes'] = entry['allocation_without_map_bytes']
    row['gaps'] = [gap for gap in entry['gaps'] if field in gap['affects']]
    return row


def volume(args):
    result = header('volume')
    result['volumes'] = []
    seen = set()
    for path in args.paths:
        if not os.path.exists(path):
            sys.exit(f'apfs-measure: path does not exist: {path}')
        mount = statfs(path).f_mntonname.decode()
        if mount not in seen:
            seen.add(mount)
            result['volumes'].append(volume_context(path))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    v = sub.add_parser('volume', help='container capacity, availability estimates, and snapshots')
    v.add_argument('paths', nargs='*', default=[os.path.expanduser('~')])
    s = sub.add_parser('scan', help='measure candidate paths against optional reference roots')
    s.add_argument('candidates', nargs='+', help='paths that might be deleted')
    s.add_argument('--reference', action='append', default=[], metavar='ROOT',
                   help='root that may share blocks with the candidates (repeatable; may contain candidates)')
    s.add_argument('--samples', type=int, default=5, help='example paths kept per gap reason')
    f = sub.add_parser('footprint', help='rank disjoint roots by mapped live file data')
    f.add_argument('candidates', nargs='+', metavar='ROOT')
    f.add_argument('--samples', type=int, default=5, help='example paths kept per gap reason')
    f.set_defaults(reference=[])
    args = parser.parse_args()
    if sys.platform != 'darwin':
        sys.exit('apfs-measure: macOS only')
    json.dump(volume(args) if args.command == 'volume' else scan(args), sys.stdout, indent=2)
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()

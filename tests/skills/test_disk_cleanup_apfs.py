#!/usr/bin/env python3
"""APFS fixtures for the disk-cleanup measurement helper. macOS only.

Scans run under a sandbox that denies writes and network access. The reclaim
test uses its own disk image, so no real volume or snapshot is touched.
"""

import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'home/dot_agents/skills/disk-cleanup/scripts/apfs-measure.py'
SANDBOX = '/usr/bin/sandbox-exec'
READ_ONLY = '(version 1) (allow default) (deny file-write*) (deny network*)'
MIB = 1024 * 1024


def write(path, data, sync=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as f:
        f.write(data)
        if sync:
            f.flush()
            os.fsync(f.fileno())


def clone(src, dst):
    subprocess.run(['/bin/cp', '-c', str(src), str(dst)], check=True)


def measure(*args, check=True, unavailable_attributes=False):
    argv = [sys.executable, '-B', str(SCRIPT), *map(str, args)]
    if unavailable_attributes:
        driver = '''import importlib.util, sys
spec = importlib.util.spec_from_file_location("apfs_measure", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.file_attributes = lambda path: (None, None)
sys.argv = sys.argv[1:]
module.main()
'''
        argv = [sys.executable, '-B', '-c', driver, str(SCRIPT), *map(str, args)]
    if os.path.exists(SANDBOX):
        argv = [SANDBOX, '-p', READ_ONLY, *argv]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    if check:
        if result.returncode:
            raise AssertionError(result.stderr)
        return json.loads(result.stdout)
    return result


def gap_reasons(entry):
    return {gap['reason'] for gap in entry['gaps']}


@unittest.skipUnless(sys.platform == 'darwin', 'APFS measurement is macOS only')
class MeasureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='apfs-measure-')
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self):
        for path in self.root.rglob('*'):
            if not path.is_symlink():
                path.chmod(0o700)
        self.temporary.cleanup()

    def scan(self, *args):
        return measure('scan', *args)

    def test_sparse_holes_are_not_physical_data(self):
        path = self.root / 'sparse.bin'
        with path.open('wb') as f:
            os.ftruncate(f.fileno(), 64 * MIB)
            f.write(os.urandom(4096))
            f.seek(64 * MIB - 4096)
            f.write(os.urandom(4096))
            f.flush()
            os.fsync(f.fileno())
        allocated = path.stat().st_blocks * 512
        self.assertLess(allocated, 64 * MIB)
        c = self.scan(path)['candidates'][0]
        self.assertEqual(c['logical_bytes'], 64 * MIB)
        self.assertEqual(c['unique_physical_bytes'], allocated)
        self.assertTrue(all(c['complete'].values()), c['gaps'])

    def test_preallocation_past_eof_is_mapped(self):
        import fcntl

        path = self.root / 'reserved.bin'
        write(path, os.urandom(4096))
        with path.open('r+b') as f:
            # F_PREALLOCATE, F_ALLOCATEALL, F_PEOFPOSMODE: reserve 8 MiB past EOF.
            fcntl.fcntl(f.fileno(), 42, struct.pack('=Iiqqq', 4, 3, 0, 8 * MIB, 0))
            os.fsync(f.fileno())
            c = self.scan(path)['candidates'][0]
            allocated = os.fstat(f.fileno()).st_blocks * 512
        self.assertEqual(c['logical_bytes'], 4096)
        self.assertGreaterEqual(allocated, 8 * MIB)
        self.assertEqual(c['unique_physical_bytes'], allocated)
        self.assertEqual(c['reclaim_if_deleted_bytes'], {'at_least': allocated, 'at_most': allocated})
        self.assertTrue(c['complete']['reclaim_if_deleted_bytes'], c['gaps'])

    def test_footprint_ranks_by_mapped_data(self):
        pair, larger = self.root / 'clones', self.root / 'larger'
        write(pair / 'original', os.urandom(4 * MIB))
        clone(pair / 'original', pair / 'copy')
        write(larger / 'unique', os.urandom(6 * MIB))
        result = measure('footprint', pair, larger)
        self.assertEqual([row['path'] for row in result['roots']], [str(larger), str(pair)])
        self.assertEqual([row['mapped_file_data_bytes'] for row in result['roots']], [6 * MIB, 4 * MIB])
        self.assertEqual(result['combined']['mapped_file_data_bytes'], 10 * MIB)
        self.assertTrue(result['combined']['complete'])

    def test_resource_fork_data_is_mapped(self):
        path = self.root / 'fork.bin'
        path.touch()
        with open(str(path) + '/..namedfork/rsrc', 'wb') as f:
            f.write(os.urandom(128 * 1024))
            f.flush()
            os.fsync(f.fileno())
        c = self.scan(path)['candidates'][0]
        self.assertEqual(c['allocated_bytes'], 128 * 1024)
        self.assertEqual(c['unique_physical_bytes'], 128 * 1024)
        # Private size covers only the data fork, so it is marked incomplete rather than read as zero.
        self.assertIn('private_excludes_resource_fork', gap_reasons(c))
        self.assertFalse(c['complete']['private_bytes_sum'])
        self.assertTrue(c['complete']['unique_physical_bytes'])
        self.assertEqual(c['reclaim_if_deleted_bytes']['at_most'], 128 * 1024)

    def test_compressed_file_is_measured_through_its_stream(self):
        plain, packed = self.root / 'plain.txt', self.root / 'packed.txt'
        write(plain, b'abc' * 700_000)
        subprocess.run(['/usr/bin/ditto', '--hfsCompression', str(plain), str(packed)], check=True)
        if not packed.stat().st_flags & 0x20:
            self.skipTest('ditto did not compress the fixture')
        c = self.scan(packed)['candidates'][0]
        self.assertEqual(c['counts']['compressed_files'], 1)
        self.assertEqual(c['logical_bytes'], 2_100_000)
        self.assertEqual(c['unique_physical_bytes'], packed.stat().st_blocks * 512)
        self.assertGreater(c['unique_physical_bytes'], 0)
        self.assertTrue(c['complete']['unique_physical_bytes'], c['gaps'])

    def test_private_sum_is_not_joint_reclaim_for_clones(self):
        left, right = self.root / 'pair/left.bin', self.root / 'pair/right.bin'
        write(left, os.urandom(8 * MIB))
        clone(left, right)
        whole = self.scan(left.parent)['candidates'][0]
        self.assertEqual(whole['allocated_bytes'], 16 * MIB)
        self.assertEqual(whole['unique_physical_bytes'], 8 * MIB)
        self.assertEqual(whole['private_bytes_sum'], 0)
        self.assertEqual(whole['reclaim_if_deleted_bytes'], {'at_least': 0, 'at_most': 8 * MIB})

        separately = self.scan(left, right)
        for c in separately['candidates']:
            self.assertEqual(c['reclaim_if_deleted_bytes']['at_most'], 0)
        self.assertEqual(separately['combined']['shared_between_candidates_bytes'], 8 * MIB)
        self.assertEqual(separately['combined']['reclaim_if_deleted_bytes']['at_most'], 8 * MIB)

    def test_clone_partner_outside_candidate_is_retained(self):
        left, right = self.root / 'keep/left.bin', self.root / 'drop/right.bin'
        write(left, os.urandom(8 * MIB))
        right.parent.mkdir()
        clone(left, right)
        # Unscanned partner: the block map alone looks exclusive, but private size shows it is held elsewhere.
        alone = self.scan(right.parent)['candidates'][0]
        self.assertEqual(alone['exclusive_within_coverage_bytes'], 8 * MIB)
        self.assertEqual(alone['retained_elsewhere_bytes'], 8 * MIB)
        self.assertEqual(alone['reclaim_if_deleted_bytes']['at_most'], 0)
        # Scanned partner: the sharing is attributed to the reference.
        result = self.scan(right.parent, '--reference', left.parent)
        c, ref = result['candidates'][0], result['references'][0]
        self.assertEqual(c['shared_with_references_bytes'], 8 * MIB)
        self.assertEqual(c['exclusive_within_coverage_bytes'], 0)
        self.assertEqual(ref['shared_with_candidates_bytes'], 8 * MIB)

    def test_partially_rewritten_clone_owns_only_its_changes(self):
        left, right = self.root / 'base.bin', self.root / 'work/copy.bin'
        write(left, os.urandom(8 * MIB))
        right.parent.mkdir()
        clone(left, right)
        with right.open('r+b') as f:
            f.seek(4 * MIB)
            f.write(os.urandom(64 * 1024))
            f.flush()
            os.fsync(f.fileno())
        c = self.scan(right.parent, '--reference', self.root)['candidates'][0]
        self.assertEqual(c['unique_physical_bytes'], 8 * MIB)
        self.assertEqual(c['shared_with_references_bytes'], 8 * MIB - 64 * 1024)
        self.assertEqual(c['reclaim_if_deleted_bytes'], {'at_least': 64 * 1024, 'at_most': 64 * 1024})

    def test_hard_link_outside_roots_keeps_data(self):
        inside, outside = self.root / 'drop/a.bin', self.root / 'b.bin'
        write(inside, os.urandom(MIB))
        os.link(inside, outside)
        c = self.scan(inside.parent)['candidates'][0]
        self.assertEqual(c['counts']['files_with_links_outside_roots'], 1)
        self.assertEqual(c['unique_physical_bytes'], MIB)
        self.assertEqual(c['reclaim_if_deleted_bytes'], {'at_least': 0, 'at_most': 0})

    @unittest.skipIf(os.geteuid() == 0, 'root bypasses permissions')
    def test_unreadable_entries_are_gaps_not_zero(self):
        locked_file, locked_dir = self.root / 'c/locked.bin', self.root / 'c/sealed'
        write(locked_file, os.urandom(MIB))
        write(locked_dir / 'inner.bin', os.urandom(MIB))
        locked_file.chmod(0)
        locked_dir.chmod(0)
        c = self.scan(self.root / 'c')['candidates'][0]
        self.assertIn('open_failed:EACCES', gap_reasons(c))
        self.assertIn('unreadable_directory:EACCES', gap_reasons(c))
        self.assertFalse(c['complete']['unique_physical_bytes'])
        self.assertFalse(c['complete']['allocated_bytes'])
        self.assertEqual(c['allocated_bytes'], MIB)  # the locked file's own allocation is still known
        self.assertIsNone(c['reclaim_if_deleted_bytes']['at_most'])
        footprint = measure('footprint', self.root / 'c')['roots'][0]
        self.assertFalse(footprint['complete'])
        self.assertIn('unreadable_directory:EACCES', gap_reasons(footprint))

    def test_unavailable_fork_attributes_mark_coverage_incomplete(self):
        path = self.root / 'fork.bin'
        path.touch()
        with open(str(path) + '/..namedfork/rsrc', 'wb') as f:
            f.write(os.urandom(128 * 1024))
            f.flush()
            os.fsync(f.fileno())
        result = measure('scan', path, unavailable_attributes=True)
        for c in (result['candidates'][0], result['combined']):
            self.assertIn('resource_fork_size_unavailable', gap_reasons(c))
            self.assertFalse(c['complete']['logical_bytes'])
            self.assertFalse(c['complete']['unique_physical_bytes'])
            self.assertFalse(c['complete']['reclaim_if_deleted_bytes'])
            self.assertIsNone(c['reclaim_if_deleted_bytes']['at_most'])

    def test_unflushed_data_is_never_silently_zero(self):
        path = self.root / 'busy.bin'
        with path.open('wb') as f:
            f.write(os.urandom(MIB))
            f.flush()  # Python buffer only; the kernel may not have allocated blocks yet.
            c = self.scan(path)['candidates'][0]
        if c['unique_physical_bytes'] < MIB:
            self.assertIn('unallocated_range', gap_reasons(c))
            self.assertFalse(c['complete']['unique_physical_bytes'])

    def test_scan_leaves_fixtures_unchanged(self):
        write(self.root / 'a/one.bin', os.urandom(MIB))
        clone(self.root / 'a/one.bin', self.root / 'a/two.bin')
        before = {p: (s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_ino)
                  for p in self.root.rglob('*') for s in [p.lstat()]}
        self.scan(self.root / 'a')
        after = {p: (s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_ino)
                 for p in self.root.rglob('*') for s in [p.lstat()]}
        self.assertEqual(before, after)

    def test_rejects_overlapping_roots(self):
        (self.root / 'a/b').mkdir(parents=True)
        result = measure('scan', self.root / 'a', self.root / 'a/b', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('overlaps', result.stderr)
        result = measure('scan', self.root / 'a/b', '--reference', self.root / 'a', check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('hdiutil'), 'needs macOS disk images')
class IsolatedVolumeTests(unittest.TestCase):
    """Compare the predicted reclaim with the container's observed free-space change on a private volume."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='apfs-volume-')
        work = Path(self.temporary.name).resolve()
        self.mount = work / 'mnt'
        self.mount.mkdir()
        try:
            subprocess.run(['hdiutil', 'create', '-size', '128m', '-fs', 'APFS', '-volname', 'dcfixture',
                            '-type', 'SPARSE', str(work / 'fixture')], check=True, capture_output=True, timeout=60)
            subprocess.run(['hdiutil', 'attach', '-nobrowse', '-noautoopen', '-owners', 'on', '-mountpoint',
                            str(self.mount), str(work / 'fixture.sparseimage')],
                           check=True, capture_output=True, timeout=60)
        except (subprocess.SubprocessError, OSError) as e:
            self.temporary.cleanup()
            self.skipTest(f'cannot attach a disk image: {e}')

    def tearDown(self):
        for args in (['hdiutil', 'detach', str(self.mount)], ['hdiutil', 'detach', '-force', str(self.mount)]):
            if subprocess.run(args, capture_output=True, timeout=60).returncode == 0:
                break
        self.temporary.cleanup()

    def free(self):
        return measure('volume', self.mount)['volumes'][0]['container_free_bytes']

    def test_observed_free_change_is_within_predicted_bounds(self):
        drop, keep = self.mount / 'drop', self.mount / 'keep'
        write(drop / 'pair-a.bin', os.urandom(8 * MIB))
        clone(drop / 'pair-a.bin', drop / 'pair-b.bin')
        write(drop / 'shared.bin', os.urandom(4 * MIB))
        keep.mkdir()
        clone(drop / 'shared.bin', keep / 'shared.bin')
        write(drop / 'own.bin', os.urandom(MIB))
        subprocess.run(['sync'], check=True)

        volume = measure('volume', self.mount)['volumes'][0]
        self.assertEqual(volume['snapshots'], [])
        self.assertIsNone(volume['snapshot_retained_bytes'])
        self.assertIn('snapshot_retained_bytes', volume['unavailable'])

        c = measure('scan', drop, '--reference', keep)['candidates'][0]
        bounds = c['reclaim_if_deleted_bytes']
        self.assertEqual(c['unique_physical_bytes'], 13 * MIB)
        self.assertEqual(c['shared_with_references_bytes'], 4 * MIB)
        self.assertEqual(bounds, {'at_least': MIB, 'at_most': 9 * MIB})

        before = self.free()
        shutil.rmtree(drop)
        subprocess.run(['sync'], check=True)
        observed = None
        for _ in range(20):  # APFS can release freed blocks shortly after the unlink returns
            observed = self.free() - before
            if observed >= bounds['at_least']:
                break
            time.sleep(0.25)
        # Deleting also frees a little filesystem metadata, which the file-data bounds exclude.
        self.assertGreaterEqual(observed, bounds['at_least'])
        self.assertLessEqual(observed, bounds['at_most'] + 256 * 1024)
        self.assertGreaterEqual(observed, bounds['at_most'] - 64 * 1024)


if __name__ == '__main__':
    unittest.main()

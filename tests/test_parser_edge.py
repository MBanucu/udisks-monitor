"""Edge case tests for MonitorParser — ANSI, state transitions, device names, property values."""

import unittest

from udisks_monitor._events import (
    DevicePropertyChanged,
    InterfaceAdded,
    InterfaceRemoved,
    JobAdded,
    JobCompleted,
    JobProperties,
    JobRemoved,
)
from udisks_monitor._parser import MonitorParser


# ── ANSI escape handling ───────────────────────────────────────

class TestAnsiEdge(unittest.TestCase):
    def setUp(self):
        self.p = MonitorParser()

    def test_ansi_in_job_added(self):
        ev = self.p.feed('\x1b[32mAdded /org/freedesktop/UDisks2/jobs/1\x1b[0m')
        self.assertIsInstance(ev, JobAdded)
        self.assertEqual(ev.job_id, 1)

    def test_ansi_in_job_removed(self):
        ev = self.p.feed('\x1b[31mRemoved /org/freedesktop/UDisks2/jobs/1\x1b[0m')
        self.assertIsInstance(ev, JobRemoved)
        self.assertEqual(ev.job_id, 1)

    def test_ansi_in_job_completed(self):
        ev = self.p.feed(
            '\x1b[37m/org/freedesktop/UDisks2/jobs/1: '
            'org.freedesktop.UDisks2.Job::Completed (true, \'\')\x1b[0m')
        self.assertIsInstance(ev, JobCompleted)
        self.assertTrue(ev.success)

    def test_ansi_in_interface_added(self):
        self.p.feed('\x1b[32m/org/.../block_devices/loop0: '
                     'Added interface org.freedesktop.UDisks2.Filesystem\x1b[0m')
        self.p.feed('  MountPoints:')
        ev = self.p.feed('')
        self.assertIsInstance(ev, InterfaceAdded)
        self.assertEqual(ev.device_name, 'loop0')

    def test_ansi_in_interface_removed(self):
        ev = self.p.feed('\x1b[31m/org/.../block_devices/loop0: '
                          'Removed interface org.freedesktop.UDisks2.Filesystem\x1b[0m')
        self.assertIsInstance(ev, InterfaceRemoved)
        self.assertEqual(ev.device_name, 'loop0')

    def test_ansi_in_properties_changed(self):
        self.p.feed('\x1b[33m/org/.../block_devices/loop0: '
                     'org.freedesktop.UDisks2.Loop: Properties Changed\x1b[0m')
        ev = self.p.feed('\x1b[1m  BackingFile:\x1b[0m  \x1b[1m/tmp/img\x1b[0m')
        self.assertIsInstance(ev, DevicePropertyChanged)
        self.assertEqual(ev.device_name, 'loop0')
        self.assertEqual(ev.property, 'BackingFile')
        self.assertEqual(ev.value, '/tmp/img')

    def test_ansi_mid_text(self):
        # ANSI codes in the middle of a device path
        ev = self.p.feed('\x1b[32mAdded\x1b[0m /org/freedesktop/UDisks2/jobs/42')
        self.assertIsInstance(ev, JobAdded)
        self.assertEqual(ev.job_id, 42)

    def test_multiple_adjacent_escapes(self):
        ev = self.p.feed(
            '\x1b[32m\x1b[1mAdded /org/freedesktop/UDisks2/jobs/1\x1b[0m')
        self.assertIsInstance(ev, JobAdded)
        self.assertEqual(ev.job_id, 1)


# ── Parser state transitions ───────────────────────────────────

class TestParserStateTransitions(unittest.TestCase):
    def setUp(self):
        self.p = MonitorParser()

    def test_device_context_overwritten(self):
        self.p.feed('/org/.../block_devices/loop0: '
                     'org.freedesktop.UDisks2.Loop: Properties Changed')
        self.p.feed('/org/.../block_devices/loop1: '
                     'org.freedesktop.UDisks2.Loop: Properties Changed')
        ev = self.p.feed('  BackingFile:          /tmp/img')
        self.assertEqual(ev.device_name, 'loop1')

    def test_device_context_persists_across_unrelated_lines(self):
        self.p.feed('/org/.../block_devices/loop0: '
                     'org.freedesktop.UDisks2.Loop: Properties Changed')
        self.p.feed('Monitoring the udisks daemon.')
        self.p.feed('12:03:29.940: The udisks-daemon is running')
        ev = self.p.feed('  BackingFile:          /tmp/img')
        self.assertIsInstance(ev, DevicePropertyChanged)
        self.assertEqual(ev.device_name, 'loop0')

    def test_device_context_not_set_by_drive_path(self):
        self.p.feed('/org/freedesktop/UDisks2/drives/ST1000DM010: '
                     'org.freedesktop.UDisks2.Drive: Properties Changed')
        ev = self.p.feed('  Vendor:               Seagate')
        self.assertIsNone(ev)

    def test_device_context_not_set_by_job_path(self):
        ev = self.p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        self.assertIsInstance(ev, JobAdded)
        # Job paths should not set _cur_device
        ev2 = self.p.feed('  BackingFile:          /tmp/img')
        self.assertIsNone(ev2)

    def test_job_added_while_already_in_job(self):
        self.p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        ev = self.p.feed('Added /org/freedesktop/UDisks2/jobs/2')
        self.assertIsInstance(ev, JobAdded)
        self.assertEqual(ev.job_id, 2)

    def test_removed_without_added(self):
        ev = self.p.feed('Removed /org/freedesktop/UDisks2/jobs/1')
        self.assertIsInstance(ev, JobRemoved)
        self.assertEqual(ev.job_id, 1)

    def test_emitted_reset_on_new_job(self):
        self.p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        self.p.feed('    Operation:          filesystem-mount')
        self.p.feed('    Objects:            /org/.../block_devices/loop0')
        # New job should reset emitted flag
        self.p.feed('Added /org/freedesktop/UDisks2/jobs/2')
        self.p.feed('    Operation:          filesystem-unmount')
        ev = self.p.feed('    Objects:            /org/.../block_devices/loop0')
        self.assertIsInstance(ev, JobProperties)
        self.assertEqual(ev.operation, 'filesystem-unmount')
        self.assertEqual(ev.job_id, 2)

    def test_property_feeding_without_device_context(self):
        ev = self.p.feed('  BackingFile:          /tmp/img')
        self.assertIsNone(ev)


# ── Device name extraction ─────────────────────────────────────

class TestDeviceNameExtraction(unittest.TestCase):
    def setUp(self):
        self.p = MonitorParser()

    def test_standard_loop_device(self):
        self.p.feed('/org/.../block_devices/loop0: '
                     'org.freedesktop.UDisks2.Loop: Properties Changed')
        ev = self.p.feed('  BackingFile:          /tmp/img')
        self.assertEqual(ev.device_name, 'loop0')

    def test_nvme_device(self):
        self.p.feed('/org/.../block_devices/nvme0n1: '
                     'org.freedesktop.UDisks2.Block: Properties Changed')
        ev = self.p.feed('  Size:                  512110190592')
        self.assertEqual(ev.device_name, 'nvme0n1')

    def test_nvme_partition(self):
        self.p.feed('/org/.../block_devices/nvme0n1p1: '
                     'org.freedesktop.UDisks2.Block: Properties Changed')
        ev = self.p.feed('  IdUUID:               F758-CF8B')
        self.assertEqual(ev.device_name, 'nvme0n1p1')

    def test_disk_device(self):
        self.p.feed('/org/.../block_devices/sda: '
                     'org.freedesktop.UDisks2.Block: Properties Changed')
        ev = self.p.feed('  Size:                  1000204886016')
        self.assertEqual(ev.device_name, 'sda')

    def test_partition(self):
        self.p.feed('/org/.../block_devices/sda1: '
                     'org.freedesktop.UDisks2.Block: Properties Changed')
        ev = self.p.feed('  IdType:               ext4')
        self.assertEqual(ev.device_name, 'sda1')

    def test_dm_device(self):
        self.p.feed('/org/.../block_devices/dm-0: '
                     'org.freedesktop.UDisks2.Block: Properties Changed')
        ev = self.p.feed('  Size:                  10737418240')
        self.assertEqual(ev.device_name, 'dm-0')

    def test_mmc_device(self):
        self.p.feed('/org/.../block_devices/mmcblk0: '
                     'org.freedesktop.UDisks2.Block: Properties Changed')
        ev = self.p.feed('  Size:                  31104958464')
        self.assertEqual(ev.device_name, 'mmcblk0')

    def test_partial_match_loop0_not_in_loop10(self):
        self.p.feed('/org/.../block_devices/loop10: '
                     'org.freedesktop.UDisks2.Loop: Properties Changed')
        ev = self.p.feed('  BackingFile:          /tmp/img')
        self.assertEqual(ev.device_name, 'loop10')

    def test_sda_not_in_sda1(self):
        self.p.feed('/org/.../block_devices/sda: '
                     'org.freedesktop.UDisks2.Block: Properties Changed')
        self.p.feed('/org/.../block_devices/sda1: '
                     'org.freedesktop.UDisks2.Block: Properties Changed')
        ev = self.p.feed('  IdType:               vfat')
        self.assertEqual(ev.device_name, 'sda1')


# ── Property value parsing ─────────────────────────────────────

class TestPropertyValueParsing(unittest.TestCase):
    def setUp(self):
        self.p = MonitorParser()

    def _start_block(self, device='loop0',
                     iface='org.freedesktop.UDisks2.Loop'):
        self.p.feed(f'/org/.../block_devices/{device}: '
                     f'{iface}: Properties Changed')

    def test_normal_path(self):
        self._start_block()
        ev = self.p.feed('  BackingFile:          /tmp/image.img')
        self.assertEqual(ev.value, '/tmp/image.img')

    def test_path_with_spaces(self):
        self._start_block()
        ev = self.p.feed('  BackingFile:          /tmp/my image.img')
        self.assertEqual(ev.value, '/tmp/my image.img')

    def test_empty_value(self):
        self._start_block()
        ev = self.p.feed('  BackingFile:')
        self.assertEqual(ev.value, '')

    def test_empty_value_with_spaces(self):
        self._start_block()
        ev = self.p.feed('  BackingFile:          ')
        self.assertEqual(ev.value, '')

    def test_value_with_unicode(self):
        self._start_block()
        ev = self.p.feed('  BackingFile:          /tmp/イメージ.img')
        self.assertEqual(ev.value, '/tmp/イメージ.img')

    def test_property_order_multiple_changes(self):
        self._start_block()
        ev1 = self.p.feed('  Autoclear:            true')
        ev2 = self.p.feed('  BackingFile:          /tmp/img')
        self.assertEqual(ev1.property, 'Autoclear')
        self.assertEqual(ev2.property, 'BackingFile')

    def test_backing_file_nonempty_to_empty(self):
        self._start_block()
        self.p.feed('  BackingFile:          /tmp/img')
        # second block
        self.p.feed('/org/.../block_devices/loop0: '
                     'org.freedesktop.UDisks2.Loop: Properties Changed')
        ev = self.p.feed('  BackingFile:')
        self.assertEqual(ev.value, '')

    def test_empty_to_nonempty(self):
        self._start_block()
        self.p.feed('  BackingFile:')
        self.p.feed('/org/.../block_devices/loop0: '
                     'org.freedesktop.UDisks2.Loop: Properties Changed')
        ev = self.p.feed('  BackingFile:          /tmp/new.img')
        self.assertEqual(ev.value, '/tmp/new.img')


# ── Concurrent job interleaving ────────────────────────────────

class TestConcurrentJobInterleaving(unittest.TestCase):
    def setUp(self):
        self.p = MonitorParser()

    def test_two_jobs_concurrent(self):
        self.p.feed('/org/.../block_devices/loop0: '
                     'org.freedesktop.UDisks2.Loop: Properties Changed')
        ev = self.p.feed('  BackingFile:          /tmp/a')
        self.assertEqual(ev.device_name, 'loop0')

        # Job 1 starts
        self.p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        self.p.feed('    Operation:          filesystem-mount')
        ev1 = self.p.feed('    Objects:            /org/.../block_devices/loop0')
        self.assertIsInstance(ev1, JobProperties)
        self.assertEqual(ev1.operation, 'filesystem-mount')
        self.assertEqual(ev1.job_id, 1)

        # Interleaved: another device's events
        self.p.feed('/org/.../block_devices/loop1: '
                     'org.freedesktop.UDisks2.Loop: Properties Changed')
        ev2 = self.p.feed('  BackingFile:          /tmp/b')
        self.assertEqual(ev2.device_name, 'loop1')

        # Job 1 completes
        ev3 = self.p.feed('/org/freedesktop/UDisks2/jobs/1: '
                           'org.freedesktop.UDisks2.Job::Completed (true, \'\')')
        self.assertIsInstance(ev3, JobCompleted)
        self.assertEqual(ev3.job_id, 1)
        self.assertTrue(ev3.success)

        # Job 2 starts (concurrent with job 1 being removed)
        self.p.feed('Added /org/freedesktop/UDisks2/jobs/2')

        # Job 1 removed
        ev4 = self.p.feed('Removed /org/freedesktop/UDisks2/jobs/1')
        self.assertIsInstance(ev4, JobRemoved)

        # Job 2 properties
        self.p.feed('    Operation:          filesystem-unmount')
        ev5 = self.p.feed('    Objects:            /org/.../block_devices/loop0')
        self.assertIsInstance(ev5, JobProperties)
        self.assertEqual(ev5.operation, 'filesystem-unmount')
        self.assertEqual(ev5.job_id, 2)

    def test_job_removed_before_objects_seen(self):
        self.p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        ev = self.p.feed('Removed /org/freedesktop/UDisks2/jobs/1')
        self.assertIsInstance(ev, JobRemoved)
        self.assertEqual(ev.job_id, 1)

    def test_mount_and_unmount_jobs_interleaved(self):
        # Mount job
        self.p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        self.p.feed('    Operation:          filesystem-mount')
        j1 = self.p.feed('    Objects:            /org/.../block_devices/loop0')

        # Unmount job added before mount completes
        self.p.feed('Added /org/freedesktop/UDisks2/jobs/2')
        self.p.feed('    Operation:          filesystem-unmount')
        j2 = self.p.feed('    Objects:            /org/.../block_devices/loop0')

        self.assertEqual(j1.operation, 'filesystem-mount')
        self.assertEqual(j2.operation, 'filesystem-unmount')

    def test_three_concurrent_jobs(self):
        jobs = []
        for i in range(3):
            self.p.feed(f'Added /org/freedesktop/UDisks2/jobs/{i}')
            self.p.feed('    Operation:          loop-delete')
            j = self.p.feed(f'    Objects:            /org/.../block_devices/loop{i}')
            jobs.append(j)

        self.assertEqual(len(jobs), 3)
        for i, j in enumerate(jobs):
            self.assertEqual(j.job_id, i)
            self.assertEqual(j.operation, 'loop-delete')

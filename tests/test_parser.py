"""unit tests for MonitorParser — parsing all udisksctl monitor event types."""

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


class TestJobEvents(unittest.TestCase):
    def setUp(self):
        self.p = MonitorParser()

    def test_job_added(self):
        ev = self.p.feed('Added /org/freedesktop/UDisks2/jobs/10842')
        self.assertIsInstance(ev, JobAdded)
        self.assertEqual(ev.job_path, '/org/freedesktop/UDisks2/jobs/10842')
        self.assertEqual(ev.job_id, 10842)

    def test_job_properties(self):
        self.p.feed('Added /org/freedesktop/UDisks2/jobs/10842')
        self.p.feed('    Operation:          filesystem-mount')
        ev = self.p.feed('    Objects:            /org/.../block_devices/loop3')
        self.assertIsInstance(ev, JobProperties)
        self.assertEqual(ev.operation, 'filesystem-mount')
        self.assertEqual(ev.objects, '/org/.../block_devices/loop3')
        self.assertEqual(ev.job_id, 10842)

    def test_job_completed_success(self):
        ev = self.p.feed(
            '/org/freedesktop/UDisks2/jobs/10842: '
            'org.freedesktop.UDisks2.Job::Completed (true, \'\')')
        self.assertIsInstance(ev, JobCompleted)
        self.assertTrue(ev.success)
        self.assertEqual(ev.message, '')

    def test_job_completed_failure(self):
        ev = self.p.feed(
            '/org/freedesktop/UDisks2/jobs/42: '
            'org.freedesktop.UDisks2.Job::Completed (false, \'device busy\')')
        self.assertIsInstance(ev, JobCompleted)
        self.assertFalse(ev.success)
        self.assertEqual(ev.message, 'device busy')

    def test_job_removed(self):
        ev = self.p.feed('Removed /org/freedesktop/UDisks2/jobs/10842')
        self.assertIsInstance(ev, JobRemoved)
        self.assertEqual(ev.job_id, 10842)

    def test_job_re_emit_prevented(self):
        self.p.feed('Added /org/freedesktop/UDisks2/jobs/1')
        self.p.feed('    Operation:          filesystem-mount')
        self.p.feed('    Objects:            /org/.../block_devices/loop0')
        # second Objects line should not re-emit
        ev = self.p.feed('    Objects:            /org/.../block_devices/loop1')
        self.assertIsNone(ev)


class TestInterfaceEvents(unittest.TestCase):
    def setUp(self):
        self.p = MonitorParser()

    def test_interface_added_with_properties(self):
        self.p.feed('/org/.../block_devices/loop3: '
                     'Added interface org.freedesktop.UDisks2.Filesystem')
        self.p.feed('  MountPoints:')
        self.p.feed('  Size:                 0')
        # next top-level line flushes the buffer
        ev = self.p.feed('Monitoring the udisks daemon.')
        self.assertIsInstance(ev, InterfaceAdded)
        self.assertEqual(ev.device_name, 'loop3')
        self.assertEqual(ev.interface,
                         'org.freedesktop.UDisks2.Filesystem')
        self.assertEqual(ev.properties, {'MountPoints': '', 'Size': '0'})

    def test_interface_removed(self):
        ev = self.p.feed('/org/.../block_devices/loop1: '
                         'Removed interface org.freedesktop.UDisks2.Filesystem')
        self.assertIsInstance(ev, InterfaceRemoved)
        self.assertEqual(ev.device_name, 'loop1')
        self.assertEqual(ev.interface,
                         'org.freedesktop.UDisks2.Filesystem')


class TestDevicePropertyChanged(unittest.TestCase):
    def setUp(self):
        self.p = MonitorParser()

    def test_backing_file_set(self):
        self.p.feed('/org/.../block_devices/loop0: '
                     'org.freedesktop.UDisks2.Loop: Properties Changed')
        ev = self.p.feed('  BackingFile:          /tmp/img')
        self.assertIsInstance(ev, DevicePropertyChanged)
        self.assertEqual(ev.device_name, 'loop0')
        self.assertEqual(ev.interface, 'org.freedesktop.UDisks2.Loop')
        self.assertEqual(ev.property, 'BackingFile')
        self.assertEqual(ev.value, '/tmp/img')

    def test_backing_file_cleared(self):
        self.p.feed('/org/.../block_devices/loop0: '
                     'org.freedesktop.UDisks2.Loop: Properties Changed')
        ev = self.p.feed('  BackingFile:')
        self.assertIsInstance(ev, DevicePropertyChanged)
        self.assertEqual(ev.value, '')

    def test_id_uuid_changed(self):
        self.p.feed('/org/.../block_devices/loop3: '
                     'org.freedesktop.UDisks2.Block: Properties Changed')
        ev = self.p.feed('  IdUUID:               F758-CF8B')
        self.assertIsInstance(ev, DevicePropertyChanged)
        self.assertEqual(ev.interface, 'org.freedesktop.UDisks2.Block')
        self.assertEqual(ev.property, 'IdUUID')
        self.assertEqual(ev.value, 'F758-CF8B')

    def test_multiple_properties(self):
        self.p.feed('/org/.../block_devices/loop3: '
                     'org.freedesktop.UDisks2.Block: Properties Changed')
        ev1 = self.p.feed('  IdUUID:               F758-CF8B')
        ev2 = self.p.feed('  IdType:               vfat')
        self.assertEqual(ev1.property, 'IdUUID')
        self.assertEqual(ev2.property, 'IdType')

    def test_mount_points_changed(self):
        self.p.feed('/org/.../block_devices/loop3: '
                     'org.freedesktop.UDisks2.Filesystem: Properties Changed')
        ev = self.p.feed('  MountPoints:          /run/media/user/VOL')
        self.assertIsInstance(ev, DevicePropertyChanged)
        self.assertEqual(ev.interface,
                         'org.freedesktop.UDisks2.Filesystem')
        self.assertEqual(ev.property, 'MountPoints')
        self.assertEqual(ev.value, '/run/media/user/VOL')

    def test_property_without_device_context(self):
        ev = self.p.feed('  BackingFile:          /tmp/img')
        self.assertIsNone(ev)

    def test_device_context_persists(self):
        self.p.feed('/org/.../block_devices/loop0: '
                     'org.freedesktop.UDisks2.Loop: Properties Changed')
        self.p.feed('  BackingFile:          /tmp/img')
        self.p.feed('Some unrelated preamble line')
        ev = self.p.feed('  Autoclear:            true')
        self.assertIsInstance(ev, DevicePropertyChanged)
        self.assertEqual(ev.device_name, 'loop0')
        self.assertEqual(ev.property, 'Autoclear')

    def test_device_switch_updates_context(self):
        self.p.feed('/org/.../block_devices/loop0: '
                     'org.freedesktop.UDisks2.Loop: Properties Changed')
        self.p.feed('/org/.../block_devices/loop1: '
                     'org.freedesktop.UDisks2.Loop: Properties Changed')
        ev = self.p.feed('  BackingFile:          /tmp/other')
        self.assertEqual(ev.device_name, 'loop1')


class TestJobInterleaving(unittest.TestCase):
    def setUp(self):
        self.p = MonitorParser()

    def test_property_changes_inside_job(self):
        self.p.feed('/org/.../block_devices/loop3: '
                     'org.freedesktop.UDisks2.Block: Properties Changed')
        ev1 = self.p.feed('  IdUUID:               F758-CF8B')
        self.assertIsInstance(ev1, DevicePropertyChanged)
        # job starts
        self.p.feed('Added /org/freedesktop/UDisks2/jobs/10842')
        self.p.feed('    Operation:          filesystem-mount')
        ev2 = self.p.feed('    Objects:            /org/.../block_devices/loop3')
        self.assertIsInstance(ev2, JobProperties)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.p = MonitorParser()

    def test_preamble_ignored(self):
        ev = self.p.feed('Monitoring the udisks daemon.')
        self.assertIsNone(ev)

    def test_empty_line_ignored(self):
        ev = self.p.feed('')
        self.assertIsNone(ev)

    def test_ansi_stripping(self):
        ev = self.p.feed(
            '\x1b[32mAdded /org/freedesktop/UDisks2/jobs/42\x1b[0m')
        self.assertIsInstance(ev, JobAdded)
        self.assertEqual(ev.job_id, 42)

    def test_device_drive_path_not_device_context(self):
        ev = self.p.feed(
            '/org/freedesktop/UDisks2/drives/ST1000DM010_ZZZ: '
            'org.freedesktop.UDisks2.Drive: Properties Changed')
        self.assertIsNone(ev)

    def test_job_completed_with_ansi(self):
        ev = self.p.feed(
            '\x1b[37m/org/freedesktop/UDisks2/jobs/1: '
            'org.freedesktop.UDisks2.Job::Completed (true, \'\')\x1b[0m')
        self.assertIsInstance(ev, JobCompleted)
        self.assertTrue(ev.success)

    def test_job_removed_after_job_completed_emits_both(self):
        c = self.p.feed(
            '/org/freedesktop/UDisks2/jobs/1: '
            'org.freedesktop.UDisks2.Job::Completed (true, \'\')')
        self.assertIsInstance(c, JobCompleted)
        r = self.p.feed('Removed /org/freedesktop/UDisks2/jobs/1')
        self.assertIsInstance(r, JobRemoved)

    def test_interface_added_then_removed(self):
        self.p.feed('/org/.../block_devices/loop3: '
                     'Added interface org.freedesktop.UDisks2.Filesystem')
        self.p.feed('  MountPoints:          /mnt')
        # Any non-indented line flushes the buffered InterfaceAdded
        ev1 = self.p.feed('')
        self.assertIsInstance(ev1, InterfaceAdded)
        self.assertEqual(ev1.properties, {'MountPoints': '/mnt'})
        ev2 = self.p.feed('/org/.../block_devices/loop3: '
                          'Removed interface org.freedesktop.UDisks2.Filesystem')
        self.assertIsInstance(ev2, InterfaceRemoved)
        self.assertEqual(ev2.device_name, 'loop3')

    def test_timestamp_stripping(self):
        """Lines with ``HH:MM:SS.mmm: `` prefix are parsed correctly."""
        ts = '20:23:11.979: '
        self.assertIsInstance(self.p.feed(ts + 'Added /org/freedesktop/UDisks2/jobs/1'),
                              JobAdded)
        self.p.feed(ts + '    Operation:  loop-delete')
        self.assertIsInstance(self.p.feed(ts + '    Objects:    /org/.../loop0'),
                              JobProperties)
        self.assertIsInstance(self.p.feed(ts + '/org/freedesktop/UDisks2/jobs/1: '
                                  'org.freedesktop.UDisks2.Job::Completed (true, \'\')'),
                              JobCompleted)
        self.assertIsInstance(self.p.feed(ts + 'Removed /org/freedesktop/UDisks2/jobs/1'),
                              JobRemoved)

import sandbox  # Isolate paths and guard writes before loading application code.
import contextlib
import datetime
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('pruning_backend', Path(__file__).resolve().parents[1] / 'Resources/backend.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class BackupPruningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'backups'
        self.root.mkdir()
        self.now = datetime.datetime(2026, 9, 30, 12)

    def populate(self, count):
        names = [f'20260901-120000-{i:06x}' for i in range(count)]
        for name in names:
            (self.root / name).mkdir()
            (self.root / name / 'manifest.json').write_text('{}')
        return names

    def test_exact_limit_preserves_all(self):
        names = self.populate(100)
        result = b.prune_backups(self.root, now=self.now, dry_run=False)
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['deleted'], 0)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), names)

    def test_limit_plus_one_deletes_only_oldest(self):
        names = self.populate(101)
        result = b.prune_backups(self.root, now=self.now, dry_run=False)
        self.assertEqual(result['candidates'], names[:1])
        self.assertEqual(result['deleted'], 1)
        self.assertEqual(result['retained'], 100)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), names[1:])

    def age_boundary(self, seconds_outside):
        # All 100 count-retained backups are newer, so only the day rule can
        # preserve the extra backup at the cutoff.
        for i in range(100):
            (self.root / f'20260924-120000-{i:06x}').mkdir()
        stamp = self.now - datetime.timedelta(days=7, seconds=seconds_outside)
        name = stamp.strftime('%Y%m%d-%H%M%S-') + 'abcdef'
        (self.root / name).mkdir()
        return name

    def test_exact_seven_days_preserves_extra_backup(self):
        name = self.age_boundary(0)
        result = b.prune_backups(self.root, now=self.now, dry_run=False)
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['retained_by_count'], 100)
        self.assertEqual(result['retained_by_days_extra'], 1)
        self.assertEqual(result['retained'], 101)
        self.assertTrue((self.root / name).exists())

    def test_seven_days_plus_one_second_deletes_extra_backup(self):
        name = self.age_boundary(1)
        result = b.prune_backups(self.root, now=self.now, dry_run=False)
        self.assertEqual(result['candidates'], [name])
        self.assertEqual(result['retained_by_count'], 100)
        self.assertEqual(result['retained_by_days_extra'], 0)
        self.assertEqual(result['retained'], 100)
        self.assertFalse((self.root / name).exists())

    def test_named_backup_with_timestamp_suffix_is_excluded(self):
        names = self.populate(2)
        named = 'manual-' + names[0]
        (self.root / named).mkdir()
        result = b.prune_backups(self.root, now=self.now, keep=1, dry_run=False)
        self.assertEqual(result['candidates'], names[:1])
        self.assertEqual(result['excluded'], [named])
        self.assertEqual(result['excluded_named'], 1)
        self.assertTrue((self.root / named).is_dir())
        self.assertTrue((self.root / names[-1]).is_dir())

    def test_current_backup_and_latest_survive_random_suffix_order(self):
        names = self.populate(5)
        result = b.prune_backups(self.root, now=self.now, keep=1, dry_run=False, protected=self.root / names[0])
        self.assertEqual(result['candidates'], names[1:-1])
        self.assertTrue((self.root / names[0]).is_dir())
        self.assertTrue((self.root / names[-1]).is_dir())

    def test_default_dry_run_reports_without_removing(self):
        names = self.populate(101)
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            result = b.prune_backups(self.root, now=self.now)
        self.assertTrue(result['dry_run'])
        self.assertEqual(result['candidates'], names[:1])
        self.assertEqual(result['deleted'], 0)
        self.assertEqual(result['retained'], 101)
        self.assertEqual(result['retained_after_prune'], 100)
        self.assertIn('"excluded_named": 0', log.getvalue())
        self.assertEqual(len(list(self.root.iterdir())), 101)

    def test_timestamp_symlink_is_not_traversed(self):
        self.populate(1)
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (outside / 'canary').write_text('keep')
        link = self.root / '20200101-000000-abcdef'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('symlink creation unavailable')
        result = b.prune_backups(self.root, now=self.now, keep=1, dry_run=False)
        self.assertEqual(result['deleted'], 0)
        self.assertTrue(link.is_symlink())
        self.assertEqual((outside / 'canary').read_text(), 'keep')

    def test_removal_failure_is_reported_and_latest_kept(self):
        from unittest.mock import patch
        names = self.populate(2)
        with patch.object(b.shutil, 'rmtree', side_effect=PermissionError):
            result = b.prune_backups(self.root, now=self.now, keep=1, dry_run=False)
        self.assertEqual(result['failed'], names[:1])
        self.assertEqual(result['deleted'], 0)
        self.assertEqual(result['retained'], 2)

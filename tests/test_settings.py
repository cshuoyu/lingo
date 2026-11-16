import datetime as dt
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from compositor import compose
from config import Config, Collection
from rotator import scheduled_rotation_due
from scheduler import sync_schedule


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(collections={'default': Collection('default', Path('/tmp/images'))})

    def test_settings_roundtrip(self):
        self.cfg.fill_style = 'fill'
        self.cfg.update_mode = 'daily'
        self.cfg.daily_time = '18:45'
        self.cfg.autostart = True
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, XDG_CONFIG_HOME=root):
            self.cfg.save()
            self.assertEqual(Config.load(), self.cfg)

    def test_daily_and_manual_schedule(self):
        self.cfg.update_mode = 'daily'
        self.cfg.daily_time = '09:00'
        self.assertFalse(scheduled_rotation_due(self.cfg, '', dt.datetime(2026, 11, 16, 8)))
        self.assertTrue(scheduled_rotation_due(self.cfg, '', dt.datetime(2026, 11, 16, 9)))
        self.assertFalse(scheduled_rotation_due(self.cfg, '2026-11-16T09:00:00', dt.datetime(2026, 11, 16, 15)))
        self.assertTrue(scheduled_rotation_due(self.cfg, '2026-11-15T09:00:00', dt.datetime(2026, 11, 16, 15)))
        self.cfg.update_mode = 'manual'
        self.assertFalse(scheduled_rotation_due(self.cfg, '', dt.datetime.now()))

    def test_fill_styles_have_expected_pixels(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'red.png'
            Image.new('RGB', (20, 40), 'red').save(source)
            for style in ('blur', 'fit', 'fill', 'stretch', 'center'):
                image = compose(source, (100, 60), fill_style=style)
                self.assertEqual(image.size, (100, 60))
                self.assertEqual(image.getpixel((50, 30)), (255, 0, 0))
                self.assertEqual(image.getpixel((0, 0)), (0, 0, 0) if style in ('fit', 'center') else (255, 0, 0))

    def test_schedule_installs_units_and_respects_autostart(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, XDG_CONFIG_HOME=root), patch('scheduler.subprocess.run') as run:
            run.return_value.returncode = 0
            sync_schedule(self.cfg)
            folder = Path(root) / 'systemd/user'
            self.assertIn('tick --startup', (folder / 'lingo-login.service').read_text())
            self.assertIn('OnCalendar=minutely', (folder / 'lingo.timer').read_text())
            self.assertEqual(run.call_args_list[1].args[0][2], 'disable')
            self.cfg.autostart = True
            sync_schedule(self.cfg)
            self.assertEqual(run.call_args_list[-2].args[0][2], 'enable')

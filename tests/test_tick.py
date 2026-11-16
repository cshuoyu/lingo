import argparse
import unittest
from pathlib import Path
from unittest.mock import patch
from config import Config, Collection, State
import main


class TickTests(unittest.TestCase):
    def run_tick(self, cfg, state, startup=False):
        with patch('main.Config.load', return_value=cfg), patch('main.State.load', return_value=state), patch('main.list_images', return_value=[Path('/tmp/a.jpg'), Path('/tmp/b.jpg')]), patch('main.compose_and_apply') as apply, patch.object(state, 'save'):
            main.cmd_tick(argparse.Namespace(startup=startup))
            return apply

    def config(self, **kwargs):
        return Config(collections={'default': Collection('default', Path('/tmp'))}, **kwargs)

    def test_manual_without_clock_does_not_change_wallpaper(self):
        apply = self.run_tick(self.config(update_mode='manual', clock_enabled=False), State())
        apply.assert_not_called()

    def test_manual_clock_refresh_uses_current_image(self):
        apply = self.run_tick(self.config(update_mode='manual'), State(recent={'default': ['a.jpg']}))
        self.assertEqual(apply.call_args.args[2], Path('/tmp/a.jpg'))

    def test_startup_rotation_obeys_preference(self):
        apply = self.run_tick(self.config(update_mode='manual', update_on_start=True), State(), startup=True)
        apply.assert_called_once()
        apply = self.run_tick(self.config(clock_enabled=False, update_on_start=False), State(), startup=True)
        apply.assert_not_called()

"""Optional GTK checks: LINGO_GUI_TEST=1 python -m unittest discover -s tests."""
import os
import tempfile
import unittest
import uuid
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('LINGO_GUI_TEST') == '1', 'requires an isolated graphical test session')
class SearchUiTests(unittest.TestCase):
    def setUp(self):
        import gi
        gi.require_version('Gtk', '4.0')
        gi.require_version('Adw', '1')
        from gi.repository import Gtk, Adw
        Gtk.init()
        Adw.init()
        self.root = tempfile.TemporaryDirectory(prefix='lingo-gui-test-')
        self.addCleanup(self.root.cleanup)
        environment = patch.dict(os.environ, XDG_CONFIG_HOME=self.root.name, XDG_CACHE_HOME=self.root.name, GSETTINGS_BACKEND='memory')
        environment.start()
        self.addCleanup(environment.stop)
        from gui import LingoWindow
        self.app = Adw.Application(application_id='org.lingo.SearchRegressionTest.t' + uuid.uuid4().hex)
        self.app.register(None)
        self.window = LingoWindow(self.app)
        self.addCleanup(self.window.destroy)
        self.window._start_url_thumb_load = lambda *_args: None

    def test_bing_defaults_to_any_size(self):
        self.window.ddg_backend.set_selected(1)
        self.assertEqual(self.window.ddg_size.get_selected(), 4)

    def test_filtered_page_advances_by_source_offset(self):
        from bing_images import BingImage, BingPage
        image = BingImage('test', 'https://example.org/a.jpg', '', 1920, 1080, '', '')
        self.window._ddg_append(BingPage([image], next_start=35, scanned_count=35), None, True)
        self.assertEqual(self.window._ddg_start, 35)
        self.assertEqual(len(self.window._ddg_items), 1)
        self.assertTrue(self.window.ddg_more.get_sensitive())

    def test_empty_size_filtered_page_can_load_more(self):
        from bing_images import BingPage
        self.window._ddg_append(BingPage([], next_start=35, scanned_count=35), None, True)
        self.assertEqual(self.window._ddg_start, 35)
        self.assertTrue(self.window.ddg_more.get_sensitive())
        self.assertIn('choose Any size', self.window.ddg_status.get_label())

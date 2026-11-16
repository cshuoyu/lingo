import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from config import Collection, Config, State
from collection_ops import rename_collection, remove_collection


class CollectionTests(unittest.TestCase):
    def test_rename_roundtrip_preserves_paths_and_history(self):
        cfg = Config(collections={'default': Collection('default', Path('/tmp/images'))})
        state = State(recent={'default': ['a.jpg']})
        name = '旅行 . "favorites"'
        rename_collection(cfg, state, 'default', name)
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, XDG_CONFIG_HOME=root):
            cfg.save()
            loaded = Config.load()
        self.assertEqual(loaded.active_collection, name)
        self.assertEqual(loaded.active().path, Path('/tmp/images'))
        self.assertEqual(state.recent[name], ['a.jpg'])

    def test_delete_active_and_protect_last(self):
        cfg = Config(collections={n: Collection(n, Path('/tmp') / n) for n in ('default', 'other')})
        state = State(last_rotation='now', recent={'default': ['a.jpg']})
        remove_collection(cfg, state, 'default')
        self.assertEqual(cfg.active_collection, 'other')
        self.assertEqual(state.last_rotation, '')
        with self.assertRaises(ValueError):
            remove_collection(cfg, state, 'other')

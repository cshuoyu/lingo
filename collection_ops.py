"""Collection operations shared by the interface and tests."""
from config import Config, State


def validate_name(cfg: Config, name: str) -> None:
    if not name.strip() or name in ('.', '..') or any(c in name for c in '/\\\0\n\r'):
        raise ValueError('Enter a valid collection name without path separators.')
    if name in cfg.collections:
        raise ValueError('A collection with this name already exists.')


def rename_collection(cfg: Config, state: State, old: str, new: str) -> None:
    if old == new:
        return
    validate_name(cfg, new)
    collection = cfg.collections[old]
    collection.name = new
    cfg.collections = {new if key == old else key: value for key, value in cfg.collections.items()}
    if cfg.active_collection == old:
        cfg.active_collection = new
    if old in state.recent:
        state.recent[new] = state.recent.pop(old)


def remove_collection(cfg: Config, state: State, name: str) -> None:
    if len(cfg.collections) <= 1:
        raise ValueError('Keep at least one collection. Create another before deleting this one.')
    del cfg.collections[name]
    state.recent.pop(name, None)
    if cfg.active_collection == name:
        cfg.active_collection = next(iter(cfg.collections))
        state.last_rotation = ''

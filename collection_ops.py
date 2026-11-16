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


def copy_image(source, destination):
    """Copy without overwriting existing images, including same-name conflicts."""
    import shutil
    from pathlib import Path
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / source.name
    if source.resolve() == target.resolve():
        raise ValueError("This image is already in that collection.")
    index = 1
    while True:
        try:
            # Exclusive creation closes the race between checking and writing.
            with target.open("xb") as output:
                try:
                    with source.open("rb") as input_file:
                        shutil.copyfileobj(input_file, output)
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
            return target
        except FileExistsError:
            target = destination / f"{source.stem} ({index}){source.suffix}"
            index += 1

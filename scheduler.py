"""Install and synchronize the current user's wallpaper jobs."""
import os
from pathlib import Path
import subprocess
import sys
from config import Config


def _quote(value) -> str:
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'


def sync_schedule(cfg: Config) -> None:
    root = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'systemd/user'
    root.mkdir(parents=True, exist_ok=True)
    project = Path(__file__).resolve().parent
    command = f'{_quote(sys.executable)} {_quote(project / "main.py")} tick'
    service = '[Unit]\nDescription=Lingo wallpaper update\nAfter=graphical-session.target\nPartOf=graphical-session.target\n\n[Service]\nType=oneshot\nExecStart=' + command + '\n'
    (root / 'lingo.service').write_text(service)
    (root / 'lingo-login.service').write_text(service.replace(command, command + ' --startup') + '\n[Install]\nWantedBy=graphical-session.target\n')
    (root / 'lingo.timer').write_text('[Unit]\nDescription=Lingo wallpaper schedule\nPartOf=graphical-session.target\n\n[Timer]\nOnCalendar=minutely\nAccuracySec=1s\nUnit=lingo.service\n\n[Install]\nWantedBy=graphical-session.target\n')
    def run(*args):
        result = subprocess.run(['systemctl', '--user', *args], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'Could not update user timer')
    run('daemon-reload')
    run('enable' if cfg.autostart else 'disable', 'lingo.timer', 'lingo-login.service')
    # Automatic updates run this session even when login startup is disabled.
    run('restart' if cfg.update_mode != 'manual' or cfg.clock_enabled else 'stop', 'lingo.timer')

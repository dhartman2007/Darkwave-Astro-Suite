"""Shared configuration, catalog links and background collector lifecycle."""
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import threading
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('DARKWAVE_SUITE_DATA', ROOT / 'data'))
LOGGER = ROOT / 'logger'


def read_settings(data=DATA):
    path = Path(data) / 'settings.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def read_suite(data=DATA):
    path = Path(data) / 'suite.json'
    config = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return {'folder': 'Z:/MyWorks' if os.name == 'nt' else '',
            'logs': str(Path(data) / 'logs'), 'poll': 10, 'idle': 300,
            'aircraft': False, 'satellites': False, 'small_bodies': False,
            'contact': '', **config}


def save_suite(config, data=DATA):
    if float(config['poll']) <= 0 or float(config['idle']) <= 0:
        raise ValueError('Polling and idle times must be positive.')
    path = Path(data)
    path.mkdir(parents=True, exist_ok=True)
    temporary = path / 'suite.json.tmp'
    temporary.write_text(json.dumps(config, indent=2), encoding='utf-8')
    temporary.replace(path / 'suite.json')


def logger_environment(config, data=DATA):
    """Materialize private worker configuration; never copy the API key."""
    data = Path(data).resolve()
    runtime = data / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    # Preserve advanced legacy options when importing existing logger configs.
    for name, updates in {
        'aircraft': {'enabled': config['aircraft']},
        'satellite': {'enabled': config['satellites']},
        'small_body': {'enabled': config['small_bodies'], 'contact': config['contact']},
    }.items():
        path = runtime / f'{name}_config.json'
        previous = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        path.write_text(json.dumps({**previous, **updates}), encoding='utf-8')
    zone = read_settings(data).get('tz', 'America/Chicago')
    ZoneInfo(zone)
    return {**os.environ, 'DARKWAVE_DATA': str(data),
            'DARKWAVE_LOGGER_CONFIG': str(runtime), 'DARKWAVE_TIMEZONE': zone}


class Collector:
    """One controller shared by browser sessions; child owns the database lock."""
    def __init__(self):
        self.process = None
        self.guard = threading.Lock()
        self.stop_path = None
        self.output_path = None

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    def start(self, config, data=DATA):
        with self.guard:
            if self.running:
                raise ValueError('The suite collector is already running.')
            folder = Path(config['folder']).expanduser()
            if not config['folder'].strip() or not folder.is_dir():
                raise ValueError('Choose an accessible image folder on the machine running the suite.')
            if float(config['poll']) <= 0 or float(config['idle']) <= 0:
                raise ValueError('Polling and idle times must be positive.')
            environment = logger_environment(config, data)
            runtime = Path(environment['DARKWAVE_LOGGER_CONFIG'])
            self.stop_path = runtime / 'collector.stop'
            self.stop_path.unlink(missing_ok=True)
            self.output_path = runtime / 'collector-output.txt'
            with self.output_path.open('w', encoding='utf-8') as output:
                self.process = subprocess.Popen(
                    [sys.executable, str(LOGGER / 'file_logger.py'), '--folder', str(folder.resolve()),
                     '--output', str(Path(config['logs']).expanduser().resolve()),
                     '--poll', str(config['poll']), '--idle', str(config['idle']),
                     '--stop-file', str(self.stop_path)],
                    cwd=LOGGER, env=environment, stdout=output, stderr=subprocess.STDOUT)

    def stop(self):
        with self.guard:
            if self.running:
                self.stop_path.touch()

    def output(self):
        if not self.output_path or not self.output_path.exists():
            return ''
        with self.output_path.open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 12000))
            return stream.read().decode('utf-8', errors='replace')


def target_candidates(folder, catalog):
    """Suggest exact catalog designations, never fuzzy-mark imaging completion."""
    designations = re.findall(r'(?<![A-Z0-9])(NGC|IC|M)\s*0*(\d+)(?!\d)', folder.upper())
    result = set()
    for prefix, number in designations:
        if prefix == 'M':
            rows = catalog[catalog.M.astype(str).str.lstrip('0') == str(int(number))]
            result.update(rows.Name)
        else:
            expected = f'{prefix}{int(number):04d}'
            result.update(catalog.loc[catalog.Name == expected, 'Name'])
    return sorted(result)


def session_links(logs, data=DATA):
    with sqlite3.connect(Path(data) / 'imaging.sqlite3') as db:
        db.execute('CREATE TABLE IF NOT EXISTS session_targets (source TEXT, session_id INTEGER, object TEXT, PRIMARY KEY(source, session_id))')
        return dict(db.execute('SELECT session_id,object FROM session_targets WHERE source=?', (str(Path(logs).resolve()),)))


def link_session(logs, session_id, name, data=DATA):
    session_links(logs, data)
    with sqlite3.connect(Path(data) / 'imaging.sqlite3') as db:
        db.execute('INSERT OR REPLACE INTO session_targets VALUES (?, ?, ?)',
                   (str(Path(logs).resolve()), int(session_id), name))


def import_logger_config(source, data=DATA):
    """Import config only; use existing log databases in place without copying."""
    source = Path(source).expanduser().resolve()
    if not (source / 'file_logger.py').is_file():
        raise ValueError('Choose the existing SeeStar-Logger installation folder.')
    runtime = Path(data) / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    suite = read_suite(data)
    suite['logs'] = str(source / 'logs')
    for name, setting in [('aircraft', 'aircraft'), ('satellite', 'satellites'), ('small_body', 'small_bodies')]:
        path = source / f'{name}_config.json'
        if not path.exists():
            continue
        values = json.loads(path.read_text(encoding='utf-8-sig'))
        if name == 'satellite' and values.get('tle_file'):
            tle = Path(values['tle_file'])
            if not tle.is_absolute():
                values['tle_file'] = str(source / tle)
        (runtime / path.name).write_text(json.dumps(values), encoding='utf-8')
        suite[setting] = bool(values.get('enabled'))
        if name == 'small_body':
            suite['contact'] = values.get('contact', '')
    save_suite(suite, data)
    return suite

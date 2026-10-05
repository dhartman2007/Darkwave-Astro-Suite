import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

import pandas as pd
import pytest

from suite import (Collector, LOGGER, import_logger_config, link_session,
                   logger_environment, read_suite, save_suite, session_links,
                   target_candidates)


def test_shared_location_and_key_reference(tmp_path, monkeypatch):
    (tmp_path / 'settings.json').write_text(json.dumps(dict(lat=34.7, lon=-86.6, tz='America/New_York', place='Travel')))
    env = logger_environment(read_suite(tmp_path), tmp_path)
    monkeypatch.setenv('DARKWAVE_DATA', env['DARKWAVE_DATA'])
    monkeypatch.setenv('DARKWAVE_LOGGER_CONFIG', env['DARKWAVE_LOGGER_CONFIG'])
    monkeypatch.syspath_prepend(str(LOGGER))
    from conditions import read_config
    config = read_config()
    assert config['location'] == dict(latitude=34.7, longitude=-86.6, name='Travel')
    assert config['astrospheric_key_file'] == str(tmp_path / 'astrospheric_api_key.txt')
    assert env['DARKWAVE_TIMEZONE'] == 'America/New_York'
    assert not (tmp_path / 'runtime' / 'astrospheric_api_key.txt').exists()


def test_catalog_alias_matching():
    objects = pd.DataFrame([dict(Name='NGC0224', M='031'), dict(Name='NGC0869', M=''), dict(Name='IC0507', M='')])
    assert target_candidates('M 31_sub', objects) == ['NGC0224']
    assert target_candidates('NGC 869', objects) == ['NGC0869']
    assert target_candidates('IC507', objects) == ['IC0507']
    assert target_candidates('SH2-108', objects) == []
    assert target_candidates('SOM31', objects) == []


def test_session_link_preserves_imaging_records_and_separates_sources(tmp_path):
    with sqlite3.connect(tmp_path / 'imaging.sqlite3') as db:
        db.execute('CREATE TABLE imaging(object TEXT PRIMARY KEY, imaged INTEGER, reimage INTEGER)')
        db.execute("INSERT INTO imaging VALUES ('NGC0224',0,1)")
    link_session(tmp_path / 'home', 1, 'NGC0224', tmp_path)
    link_session(tmp_path / 'travel', 1, 'NGC0869', tmp_path)
    assert session_links(tmp_path / 'home', tmp_path) == {1: 'NGC0224'}
    assert session_links(tmp_path / 'travel', tmp_path) == {1: 'NGC0869'}
    with sqlite3.connect(tmp_path / 'imaging.sqlite3') as db:
        assert db.execute('SELECT * FROM imaging').fetchall() == [('NGC0224', 0, 1)]


def test_import_retains_logs_and_advanced_config(tmp_path):
    old = tmp_path / 'old'
    old.mkdir()
    (old / 'file_logger.py').touch()
    (old / 'satellite_config.json').write_text(json.dumps(dict(enabled=True, tle_file='catalog.tle')))
    (old / 'small_body_config.json').write_text(json.dumps(dict(enabled=True, contact='test@example.com', magnitude_limit=18)))
    data = tmp_path / 'new'
    config = import_logger_config(old, data)
    assert config['logs'] == str(old / 'logs')
    assert not (data / 'logs').exists()
    logger_environment(config, data)
    satellite = json.loads((data / 'runtime' / 'satellite_config.json').read_text())
    assert satellite['tle_file'] == str(old / 'catalog.tle')
    assert json.loads((data / 'runtime' / 'small_body_config.json').read_text())['magnitude_limit'] == 18


def wait_until(predicate, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.05)
    raise AssertionError('Timed out waiting for collector')


def test_collector_baseline_stop_and_duplicate_lock(tmp_path):
    source = tmp_path / 'images'
    source.mkdir()
    config = {**read_suite(tmp_path), 'folder': str(source), 'poll': .1, 'idle': 1}
    first, duplicate = Collector(), Collector()
    try:
        first.start(config, tmp_path / 'first')
        wait_until(lambda: 'Baseline ready' in first.output())
        duplicate.start(config, tmp_path / 'second')
        wait_until(lambda: not duplicate.running)
        assert duplicate.process.returncode == 1
        assert 'already running' in duplicate.output()
        assert first.running
        first.stop()
        wait_until(lambda: not first.running)
        assert first.process.returncode == 0
        with sqlite3.connect(Path(config['logs']) / 'file_sessions.sqlite') as db:
            assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0
    finally:
        for worker in (first, duplicate):
            if worker.running:
                worker.stop()
                worker.process.wait(timeout=10)


def test_invalid_settings_do_not_start_process(tmp_path):
    config = read_suite(tmp_path)
    config['poll'] = 0
    with pytest.raises(ValueError):
        save_suite(config, tmp_path)
    worker = Collector()
    with pytest.raises(ValueError):
        worker.start(config, tmp_path)
    assert worker.process is None


def test_suite_navigation_and_session_review(tmp_path):
    root = Path(__file__).resolve().parent
    for name in ('NGC.csv', 'addendum.csv'):
        shutil.copy(root / 'data' / name, tmp_path / name)
    script = '''
from pathlib import Path
import os, sys
sys.path.insert(0, str(Path.cwd() / 'logger'))
from file_logger import Monitor
data = Path(os.environ['DARKWAVE_SUITE_DATA'])
monitor = Monitor(data / 'logs', 300)
monitor.process({}, tick=0)
monitor.process({'M31/image.fit': (1000000000, 12)}, now='2026-10-04T20:00:00+00:00', tick=1)
monitor.db.close()
from streamlit.testing.v1 import AppTest
app = AppTest.from_file('app.py', default_timeout=30).run()
assert not app.exception, [x.message for x in app.exception]
for module in ('Logger', 'Sessions', 'Planner', 'Overview', 'Sessions'):
    app.radio(key='suite_module').set_value(module).run()
    assert not app.exception, [x.message for x in app.exception]
    assert app.radio(key='suite_module').value == module
assert app.selectbox(key='catalog-1').value == 'NGC0224'
next(b for b in app.button if b.label == 'Save session link').click().run()
assert not app.exception
from suite import session_links
assert session_links(data / 'logs') == {1: 'NGC0224'}
from core import records
assert records().empty  # Linking a session cannot mark it completed.
for module in ('Overview', 'Planner', 'Sessions', 'Logger'):
    mobile = AppTest.from_file('app.py', default_timeout=30)
    mobile.query_params['view'] = 'mobile'
    mobile.query_params['module'] = module
    mobile.run()
    assert not mobile.exception, [x.message for x in mobile.exception]
    assert mobile.radio(key='suite_module').value == module
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=root,
                            env={**os.environ, 'DARKWAVE_SUITE_DATA': str(tmp_path)},
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr

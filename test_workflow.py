from datetime import datetime, timezone
import json
import multiprocessing
from pathlib import Path
import sqlite3
import time

import pandas as pd
import pytest

from logger.shared_weather import cached_response
from suite import (link_session, link_unambiguous, linked_sessions, review_defaults,
                   save_session_review, session_links)


def model(hour='2026-10-05T20:00:00Z'):
    return {'HourlyForecast': {'Cloud': [{'UTCForecastHour': hour, 'Value': {'ActualValue': 12}}]}}


def test_cache_reuses_snapshot_and_separates_credentials_sites_and_expiry(tmp_path):
    calls = []
    fetch = lambda: calls.append(1) or {**model(), 'APIKey': 'do-not-store'}
    first = cached_response('astro', 30.4, -87.6, 'test', fetch, directory=tmp_path, clock=lambda: 100)
    second = cached_response('astro', 30.4, -87.6, 'test', fetch, directory=tmp_path, clock=lambda: 101)
    assert first == second and len(calls) == 1
    assert 'APIKey' not in first[0]
    cached_response('astro', 30.4, -87.6, 'changed-key', fetch, directory=tmp_path, clock=lambda: 101)
    cached_response('astro', 31.4, -87.6, 'test', fetch, directory=tmp_path, clock=lambda: 101)
    cached_response('astro', 30.4, -87.6, 'test', fetch, directory=tmp_path, clock=lambda: 21701)
    assert len(calls) == 4
    assert b'do-not-store' not in (tmp_path / 'weather-cache.sqlite3').read_bytes()


def test_cache_checks_forecast_hour_coverage_and_does_not_cache_errors(tmp_path):
    count = []
    fetch = lambda: count.append(1) or model()
    cached_response('astro', 30, -80, 'key', fetch, directory=tmp_path)
    cached_response('astro', 30, -80, 'key', fetch, directory=tmp_path,
                    when=datetime(2026, 10, 5, 20, 30, tzinfo=timezone.utc))
    assert len(count) == 1
    cached_response('astro', 30, -80, 'key', fetch, directory=tmp_path,
                    when=datetime(2026, 10, 7, 20, tzinfo=timezone.utc))
    assert len(count) == 2
    with pytest.raises(ValueError):
        cached_response('astro', 30, -80, 'bad', lambda: {'ErrorInfo': 'Denied'}, directory=tmp_path)
    cached_response('astro', 30, -80, 'bad', fetch, directory=tmp_path)
    assert len(count) == 3


def test_open_meteo_cache_has_shorter_ttl(tmp_path):
    calls = []
    fetch = lambda: calls.append(1) or {'current': {'time': '2026-10-05T20:00', 'cloud_cover': 10}}
    for now in (100, 1899, 1900):
        cached_response('weather', 30, -80, '', fetch, directory=tmp_path, clock=lambda: now)
    assert len(calls) == 2


def request_worker(directory, barrier):
    def fetch():
        with (Path(directory) / 'requests.txt').open('a') as stream:
            stream.write('request\n')
        time.sleep(.1)
        return model()
    barrier.wait(timeout=10)
    cached_response('astro', 30, -80, 'test', fetch, directory=directory)


def test_two_processes_only_request_provider_once(tmp_path):
    context = multiprocessing.get_context('spawn')
    barrier = context.Barrier(2)
    workers = [context.Process(target=request_worker, args=(str(tmp_path), barrier)) for _ in range(2)]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=20)
            assert worker.exitcode == 0
        assert (tmp_path / 'requests.txt').read_text().splitlines() == ['request']
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join()


def test_bulk_link_skips_ambiguous_and_preserves_reviewed_links(tmp_path):
    objects = pd.DataFrame([dict(Name='NGC0224', M='031'), dict(Name='NGC0869', M='')])
    rows = [dict(id=1, target_folder='M31'), dict(id=2, target_folder='M31 NGC869'),
            dict(id=3, target_folder='NGC869'), dict(id=4, target_folder='Unknown')]
    link_session(tmp_path / 'logs', 1, 'NGC0869', tmp_path)
    assert link_unambiguous(tmp_path / 'logs', rows, objects, tmp_path) == 1
    assert session_links(tmp_path / 'logs', tmp_path) == {1: 'NGC0869', 3: 'NGC0869'}
    assert link_unambiguous(tmp_path / 'logs', rows, objects, tmp_path) == 0
    assert len(linked_sessions(tmp_path / 'logs', rows, 'NGC0869', tmp_path)) == 2


def test_review_preserves_existing_record_and_source_identity(tmp_path):
    row = dict(id=1, target_folder='M31', start_observed_utc='2026-10-06T02:00:00Z',
               last_activity_utc='2026-10-06T03:00:00Z', status='interrupted',
               conditions={'cloud_percent': 30, 'weather_retrieved_utc': '2026-10-06T02:00:00Z'})
    details = dict(counts=dict(aircraft=None, satellites=0, comets=None, asteroids=None),
                   file_summary=dict(rows=[dict(file_count=2, total_bytes=120)]))
    existing = dict(first_date='2026-09-01', image_url='C:/Images/M31.fit', notes='Keep this note', reimage=1)
    defaults = review_defaults(tmp_path / 'home', row, details, existing, 'America/Chicago')
    assert defaults['first_date'] == '2026-09-01'
    assert defaults['notes'].startswith('Keep this note')
    assert 'aircraft: unavailable' in defaults['notes'] and 'satellites: 0' in defaults['notes']
    assert defaults['snapshot']['duration_seconds'] == 3600
    save_session_review(tmp_path / 'home', 1, 'NGC0224', True, True,
                        defaults['first_date'], defaults['image_url'], defaults['notes'], defaults['snapshot'], tmp_path)
    again = review_defaults(tmp_path / 'home', row, details, {**existing, 'notes': defaults['notes']}, 'America/Chicago')
    assert again['notes'] == defaults['notes']
    fresh = review_defaults(tmp_path / 'travel', row, details, {}, 'America/Chicago')
    assert fresh['first_date'] == '2026-10-05'
    save_session_review(tmp_path / 'travel', 1, 'NGC0869', True, False, fresh['first_date'], '', fresh['notes'], fresh['snapshot'], tmp_path)
    with sqlite3.connect(tmp_path / 'imaging.sqlite3') as db:
        assert db.execute("SELECT imaged,reimage,first_date,image_url FROM imaging WHERE object='NGC0224'").fetchone() == (1, 1, '2026-09-01', 'C:/Images/M31.fit')
        assert db.execute('SELECT count(*) FROM imaging_session_reviews').fetchone()[0] == 2
        saved = json.loads(db.execute("SELECT snapshot_json FROM imaging_session_reviews WHERE object='NGC0224'").fetchone()[0])
        assert saved['candidate_counts']['aircraft'] is None


def test_failed_review_does_not_write(tmp_path):
    with pytest.raises(ValueError):
        save_session_review(tmp_path / 'logs', 1, 'NGC0224', True, False, 'invalid', '', '', {}, tmp_path)
    assert not (tmp_path / 'imaging.sqlite3').exists()


def test_logger_reuses_planner_forecast_without_request(tmp_path, monkeypatch):
    import core
    import sys
    sys.path.insert(0, str(Path(__file__).parent / 'logger'))
    from conditions import Conditions
    monkeypatch.setattr(core, 'DATA', tmp_path)
    monkeypatch.setenv('DARKWAVE_DATA', str(tmp_path))
    class Response:
        def json(self): return model()
        def raise_for_status(self): pass
    calls = []
    monkeypatch.setattr(core.requests, 'post', lambda *args, **kwargs: calls.append(1) or Response())
    forecast, metadata = core.forecast('test', 30, -80)
    worker = Conditions.__new__(Conditions)
    monkeypatch.setattr(worker, 'request', lambda *args: pytest.fail('Duplicate charged request'))
    raw, retrieved = worker.fetch('astro', {'latitude': 30, 'longitude': -80}, 'test',
                                  when=datetime(2026, 10, 5, 20, tzinfo=timezone.utc))
    assert len(calls) == 1 and raw['HourlyForecast']['Cloud']
    assert retrieved == metadata['suite_retrieved_utc']

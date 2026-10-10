from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
import numpy as np
import pytest
import iss_transits as transit

START = datetime(2026, 10, 10, tzinfo=timezone.utc)
TLE = ('1 25544U 98067A   26282.95044904  .00006711  00000+0  13074-3 0  9997',
       '2 25544  51.6315  92.1575 0006672 244.0714 115.9587 15.48795780589546')


def fake_sky(monkeypatch, miss=0.0, altitude=40, center=125.3):
    """A 0.5-second disk crossing centered BETWEEN the ten-second samples."""
    class Clock:
        def from_datetimes(self, dates):
            return np.array([(date-START).total_seconds() for date in dates])
    class Position:
        def __init__(self, times, body='sun'):
            self.times = times
            self.body = body
            self.message = [None] * len(times)
        def separation_from(self, target):
            return NS(degrees=np.hypot((self.times-center)*1.0, miss))
        def distance(self):
            radius = 695700 if self.body == 'sun' else 1737.4
            return NS(km=np.full(len(self.times), radius / np.sin(np.radians(0.25))))
        def altaz(self):
            values = np.full(len(self.times), altitude)
            return NS(degrees=values), NS(degrees=values), NS(km=values+500)
        def observe(self, body):
            return Position(self.times, body)
        def apparent(self):
            return self
    class Observer:
        def __add__(self, site):
            return self
        def at(self, times):
            return Position(times)
    class Satellite(Observer):
        epoch = NS(utc_datetime=lambda: START)
        def __init__(self, *args):
            pass
        def __sub__(self, site):
            return self
    class Loader:
        def __init__(self, *args):
            pass
        def timescale(self):
            return Clock()
        def __call__(self, filename):
            return dict(earth=Observer(), sun='sun', moon='moon')
    monkeypatch.setattr(transit, 'Loader', Loader)
    monkeypatch.setattr(transit, 'EarthSatellite', Satellite)
    monkeypatch.setattr(transit, 'wgs84', NS(latlon=lambda *a, **k: None))


def test_subsecond_transit_between_samples(monkeypatch, tmp_path):
    fake_sky(monkeypatch)
    events, epoch = transit.predict(tmp_path, TLE, START, 1, 30, -87, near_deg=0)
    sun = next(row for row in events if row['body'] == 'Sun')
    assert sun['classification'] == 'Disk transit'
    center = datetime.fromisoformat(sun['closest_utc'])
    assert abs((center-START).total_seconds()-125.3) < .003
    assert sun['duration_s'] == pytest.approx(.5, abs=.005)
    assert datetime.fromisoformat(sun['ingress_utc']) < center < datetime.fromisoformat(sun['egress_utc'])
    moon = next(row for row in events if row['body'] == 'Moon')
    assert moon['classification'] == 'Disk transit'
    assert moon['duration_s'] == pytest.approx(.5, abs=.005)


@pytest.mark.parametrize('center, days', [(.1, 1), (86400.1, 2), (86399.9, 2)])
def test_search_and_chunk_boundaries(monkeypatch, tmp_path, center, days):
    fake_sky(monkeypatch, center=center)
    events, _ = transit.predict(tmp_path, TLE, START, days, 30, -87, near_deg=0)
    assert len(events) == 2
    assert abs((datetime.fromisoformat(events[0]['closest_utc'])-START).total_seconds()-center) < .003


def test_near_miss_is_not_transit(monkeypatch, tmp_path):
    fake_sky(monkeypatch, miss=.4)
    events, _ = transit.predict(tmp_path, TLE, START, 1, 30, -87, near_deg=1)
    assert events
    assert all(row['classification'] == 'Near miss' and row['duration_s'] is None for row in events)
    events, _ = transit.predict(tmp_path, TLE, START, 1, 30, -87, near_deg=0)
    assert events == []


def test_below_horizon_is_excluded(monkeypatch, tmp_path):
    fake_sky(monkeypatch, altitude=-1)
    assert transit.predict(tmp_path, TLE, START, 1, 30, -87)[0] == []


def test_stale_orbit_rejected(monkeypatch, tmp_path):
    fake_sky(monkeypatch)
    with pytest.raises(ValueError, match='seven days'):
        transit.predict(tmp_path, TLE, START+timedelta(days=8), 1, 30, -87)


def test_cache_survives_bad_provider_response(monkeypatch, tmp_path):
    path = tmp_path / 'iss.tle'
    original = '\n'.join(TLE)
    path.write_text(original)
    monkeypatch.setattr(transit.requests, 'get', lambda *a, **k: NS(
        text='<html>Unavailable</html>', raise_for_status=lambda: None))
    with pytest.raises(ValueError, match='element set'):
        transit.load_orbit(tmp_path, refresh=True)
    assert path.read_text() == original


def test_orbit_parser():
    assert transit.parse_orbit('ISS\n'+'\n'.join(TLE)) == TLE
    with pytest.raises(ValueError):
        transit.parse_orbit('1 12345 other\n2 12345 other')

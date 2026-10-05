"""Cross-process model-response cache shared by the suite and standalone logger.

The database lock covers a provider request, preventing simultaneous cache misses
from consuming two requests. No request body or plaintext credential is stored.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time

ASTRO_VARIABLES = ['Cloud', 'Transparency', 'Seeing', 'Temperature', 'DewPoint', 'Wind']


def cache_directory():
    return Path(os.environ.get('DARKWAVE_DATA') or os.environ.get('DARKWAVE_SUITE_DATA')
                or Path(__file__).resolve().parent.parent / 'data') / 'runtime'


def scrub(value):
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()
                if k.lower().replace('_', '') not in ('apikey', 'authorization')}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def astro_times(data):
    envelope = data.get('HourlyForecast', data)
    entries = envelope if isinstance(envelope, list) else [
        row for name in ASTRO_VARIABLES for row in (envelope.get(name) or [])]
    times = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        timestamp = entry.get('UTCForecastHour') or entry.get('ForecastTime') or entry.get('Time')
        try:
            parsed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            if parsed.tzinfo is not None:
                times.append(parsed.timestamp())
        except (AttributeError, ValueError, TypeError):
            continue
    return times


def compatible(data, provider, when=None):
    if not isinstance(data, dict) or data.get('ErrorInfo'):
        return False
    if provider == 'astro':
        times = astro_times(data)
        if not times:
            return False
        return when is None or min(abs(t - when.timestamp()) for t in times) <= 5400
    return isinstance(data.get('current'), dict) and bool(data['current'].get('time'))


def cached_response(provider, lat, lon, credential, fetcher, *, directory=None,
                    when=None, validate=None, clock=time.time):
    lat, lon = float(lat), float(lon)
    if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError('Invalid weather-cache location')
    if provider not in ('astro', 'weather'):
        raise ValueError('Unknown weather provider')
    lifetime = 21600 if provider == 'astro' else 1800
    # Exact coordinates and request-schema version avoid cross-site/schema reuse.
    identity = hashlib.sha256(json.dumps([provider, lat, lon, credential.strip(), 1]).encode()).hexdigest()
    directory = Path(directory) if directory is not None else cache_directory()
    directory.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(directory / 'weather-cache.sqlite3', timeout=60)) as db:
        db.execute('CREATE TABLE IF NOT EXISTS responses (identity TEXT PRIMARY KEY, fetched REAL, payload TEXT)')
        db.execute('BEGIN IMMEDIATE')
        try:
            row = db.execute('SELECT fetched,payload FROM responses WHERE identity=?', (identity,)).fetchone()
            if row and 0 <= clock() - row[0] < lifetime:
                try:
                    data = json.loads(row[1])
                    usable = compatible(data, provider, when)
                    if usable and validate is not None:
                        validate(data)
                    if usable:
                        db.commit()
                        return data, datetime.fromtimestamp(row[0], timezone.utc).isoformat()
                except (ValueError, TypeError, KeyError, AttributeError):
                    pass
            data = scrub(fetcher())
            if not compatible(data, provider):
                raise ValueError('Provider returned no usable model data')
            if validate is not None:
                validate(data)
            fetched = clock()
            db.execute('INSERT OR REPLACE INTO responses VALUES (?,?,?)',
                       (identity, fetched, json.dumps(data, allow_nan=False)))
            db.commit()
            return data, datetime.fromtimestamp(fetched, timezone.utc).isoformat()
        except Exception:
            db.rollback()
            raise

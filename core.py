from pathlib import Path
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import sqlite3
import os
import requests
import pandas as pd
import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord, EarthLocation, AltAz, get_sun, get_body
from astropy.time import Time
from astropy.utils import iers
iers.conf.auto_download = False
ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('DARKWAVE_SUITE_DATA', ROOT / 'data'))
DATA.mkdir(parents=True, exist_ok=True)

def catalog():
    frames = []
    for name in ('NGC.csv', 'addendum.csv'):
        path = DATA / name
        if not path.exists():
            r = requests.get('https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files/' + name, timeout=45)
            r.raise_for_status()
            # Validate before caching, so an error page cannot poison later runs.
            if not r.text.startswith('Name;Type;RA;Dec;'):
                raise ValueError('Unexpected catalog format')
            path.write_text(r.text, encoding='utf-8')
        frames.append(pd.read_csv(path, sep=';', dtype=str).fillna(''))
    df = pd.concat(frames, ignore_index=True).drop_duplicates('Name')
    # Explicit planner convention: disputed M102 is represented by NGC5866.
    df = df[df.Name != 'M102'].copy()
    df.loc[df.Name == 'NGC5866', 'M'] = '102'
    df.loc[df.Name == 'NGC5866', 'Common names'] = 'Spindle Galaxy (M102 identification disputed)'
    df = df[(df.RA != '') & (df.Dec != '')].copy()
    coords = SkyCoord(df.RA.tolist(), df.Dec.tolist(), unit=(u.hourangle, u.deg))
    df['ra_deg'], df['dec_deg'] = coords.ra.deg, coords.dec.deg
    df['label'] = df.apply(lambda r: ('M' + str(int(r.M)) + ' / ' if r.M.isdigit() else '') + r.Name + (' — ' + r['Common names'] if r['Common names'] else ''), axis=1)
    return df

def db():
    c = sqlite3.connect(DATA / 'imaging.sqlite3')
    c.execute('CREATE TABLE IF NOT EXISTS imaging (object TEXT PRIMARY KEY, imaged INTEGER, reimage INTEGER, first_date TEXT, image_url TEXT, notes TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS nightly_plan (night TEXT, object TEXT, PRIMARY KEY (night, object))')
    return c

def planned_targets(day):
    with db() as c:
        return {row[0] for row in c.execute('SELECT object FROM nightly_plan WHERE night=?', (day.isoformat(),))}

def set_planned(day, name, enabled):
    with db() as c:
        if enabled:
            c.execute('INSERT OR IGNORE INTO nightly_plan VALUES (?, ?)', (day.isoformat(), name))
        else:
            c.execute('DELETE FROM nightly_plan WHERE night=? AND object=?', (day.isoformat(), name))

def records():
    with db() as c:
        return pd.read_sql_query('SELECT * FROM imaging', c)

def save(name, imaged, reimage, first_date, image_url, notes):
    with db() as c:
        c.execute('INSERT OR REPLACE INTO imaging VALUES (?, ?, ?, ?, ?, ?)', (name, int(imaged), int(reimage), first_date, image_url, notes))

def night_grid(day, tz):
    # Use elapsed UTC minutes, avoiding lost/repeated local hours at DST changes.
    start = datetime.combine(day, time(12), ZoneInfo(tz)).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time(12), ZoneInfo(tz)).astimezone(timezone.utc)
    return [start + timedelta(minutes=5*i) for i in range(int((end-start).total_seconds()/300))]

def windows(mask, dates, tz):
    chunks = []
    start = None
    for i, good in enumerate(list(mask) + [False]):
        if good and start is None:
            start = i
        if not good and start is not None:
            stop = dates[i-1] + timedelta(minutes=5)
            chunks.append((dates[start], stop))
            start = None
    return chunks

def plan(df, day, lat, lon, tz, minimum=30, moon_sep=30, south_height=0):
    dates = night_grid(day, tz)
    ts = Time(dates)
    site = EarthLocation.from_geodetic(lon*u.deg, lat*u.deg)
    frame = AltAz(obstime=ts, location=site, pressure=0*u.hPa)
    sun = get_sun(ts).transform_to(frame)
    moon = get_body('moon', ts, location=site)
    ma = moon.transform_to(frame)
    dark = sun.alt.deg < -18
    coords = SkyCoord(df.ra_deg.to_numpy()*u.deg, df.dec_deg.to_numpy()*u.deg)
    # Chunk the full catalog to limit peak memory.
    result = []
    for base in range(0, len(df), 256):
        cc = coords[base:base+256]
        aa = cc[:, None].transform_to(frame[None, :])
        sep = aa.separation(ma[None, :]).deg
        for j, (_, row) in enumerate(df.iloc[base:base+256].iterrows()):
            altitude, azimuth = aa.alt.deg[j], aa.az.deg[j]
            visible = dark & (altitude >= minimum)
            visible &= ~((azimuth >= 90) & (azimuth <= 270) & (altitude < south_height))
            usable = visible & ((ma.alt.deg <= 0) | (sep[j] >= moon_sep))
            spans = windows(usable, dates, tz)
            fmt = lambda dt: dt.astimezone(ZoneInfo(tz)).strftime('%m/%d %H:%M')
            h = float(usable.sum()/12)
            peak = float(altitude[dark].max()) if dark.any() else None
            best = max(spans, key=lambda p:(p[1]-p[0]).total_seconds(), default=None)
            result.append({'Name':row.Name, 'Target':row.label, 'Type':row.Type, 'Hours':round(h,2), 'Peak °':round(peak,1) if peak is not None else None, 'Best window':fmt(best[0])+' → '+fmt(best[1]) if best else 'None', 'Moon-free h':round(float((visible & (ma.alt.deg <= 0)).sum()/12),2)})
    return pd.DataFrame(result), dates, dark

def track(row, dates, lat, lon, tz):
    frame = AltAz(obstime=Time(dates), location=EarthLocation.from_geodetic(lon*u.deg,lat*u.deg), pressure=0*u.hPa)
    aa = SkyCoord(row.ra_deg*u.deg,row.dec_deg*u.deg).transform_to(frame)
    return pd.DataFrame({'Altitude':aa.alt.deg, 'Moon altitude':get_body('moon', Time(dates), location=frame.location).transform_to(frame).alt.deg}, index=pd.DatetimeIndex(dates).tz_convert(tz))

def image_urls(row):
    from urllib.parse import urlencode
    size = pd.to_numeric(row.get('MajAx',''), errors='coerce')
    fov = max(0.15,min(12, float(size)/60*1.5)) if pd.notna(size) else 0.5
    return [(label, 'https://alasky.cds.unistra.fr/hips-image-services/hips2fits?' + urlencode(dict(hips=hips, ra=row.ra_deg, dec=row.dec_deg, fov=fov*scale, width=600,height=600,projection='TAN',format='jpg'))) for label,hips,scale in [('DSS2 color • detail','CDS/P/DSS2/color',1),('DSS2 color • wide field','CDS/P/DSS2/color',2.5),('2MASS • infrared','CDS/P/2MASS/color',1)]]

FORECAST_VARIABLES = ['Cloud','Transparency','Seeing','Temperature','DewPoint','Wind']

def forecast_structure(value):
    # Only field names/types, never credentials or response values.
    if isinstance(value, list):
        return 'list; first entry: ' + forecast_structure(value[0] if value else None)
    if isinstance(value, dict):
        return ', '.join(f'{k} ({type(v).__name__})' for k, v in value.items() if k != 'APIKey')
    return type(value).__name__

def parse_forecast(data):
    # Some gateways serialize a JSON body twice; decode before inspecting it.
    if isinstance(data, str):
        import json
        try:
            data = json.loads(data)
        except ValueError:
            raise ValueError('Astrospheric returned no forecast data. The location may be outside forecast coverage.') from None
    if not isinstance(data, dict):
        raise ValueError('Astrospheric returned an unexpected response instead of a forecast.')
    if data.get('ErrorInfo'):
        raise ValueError(str(data['ErrorInfo']))
    hourly = data.get('HourlyForecast')
    if isinstance(hourly, dict):
        # Variable arrays nested under the response's forecast envelope.
        data_values = hourly
    elif isinstance(hourly, list):
        # Hourly rows with weather variables alongside the timestamp.
        data_values = {variable: [] for variable in FORECAST_VARIABLES}
        for entry in hourly:
            if not isinstance(entry, dict):
                raise ValueError('Unexpected HourlyForecast entry format.')
            timestamp = entry.get('UTCForecastHour') or entry.get('ForecastTime') or entry.get('Time')
            for variable in FORECAST_VARIABLES:
                value = entry.get(variable)
                if value is not None:
                    if isinstance(value, dict):
                        value = value.get('Value', value)
                    if not isinstance(value, dict):
                        value = {'ActualValue': value}
                    data_values[variable].append({'UTCForecastHour': timestamp, 'Value': value})
    else:
        data_values = data
    rows = {}
    try:
        for variable in FORECAST_VARIABLES:
            for entry in data_values.get(variable) or []:
                value = entry['Value']['ActualValue']
                if value is not None:
                    rows.setdefault(entry['UTCForecastHour'], {})[variable] = value
        if not rows:
            fields = ', '.join(sorted(data.keys())) or '(none)'
            raise ValueError('Astrospheric returned no hourly forecast values. '
                             'Check location coverage and API access. '
                             'Response field names: ' + fields + '. Forecast structure: ' + forecast_structure(hourly))
        frame = pd.DataFrame.from_dict(rows, orient='index')
        frame.index = pd.to_datetime(frame.index, utc=True, errors='raise')
        if frame.index.isna().any():
            raise ValueError('Missing forecast timestamp. Forecast structure: ' + forecast_structure(hourly))
        frame.index.name = 'Forecast time'
        return frame.sort_index(), data
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('Astrospheric returned an unexpected hourly forecast format. Forecast structure: ' + forecast_structure(hourly)) from exc

def forecast(key, lat, lon):
    if not key.strip():
        raise ValueError('Enter your Astrospheric API key.')
    r = requests.post('https://v2-api-public.astrospheric.com/api/GetForecastData',
                      json={'APIKey':key.strip(),'Latitude':lat,'Longitude':lon,
                            'Variables':FORECAST_VARIABLES,'ForecastLength':72}, timeout=45)
    try:
        data = r.json()
    except ValueError:
        raise ValueError(f'Astrospheric returned a non-JSON response (HTTP {r.status_code}). Try again later.') from None
    # Read the provider error before raise_for_status discards its useful message.
    if isinstance(data, dict) and data.get('ErrorInfo'):
        raise ValueError(str(data['ErrorInfo']))
    r.raise_for_status()
    return parse_forecast(data)


def remember_api_key(key, directory=DATA):
    path = Path(directory) / 'astrospheric_api_key.txt'
    key = key.strip()
    if key:
        temporary = path.with_suffix('.tmp')
        temporary.write_text(key, encoding='utf-8')
        temporary.chmod(0o600)
        temporary.replace(path)
    else:
        path.unlink(missing_ok=True)

def remembered_api_key(directory=DATA):
    path = Path(directory) / 'astrospheric_api_key.txt'
    return path.read_text(encoding='utf-8').strip() if path.exists() else ''

def forecast_us_units(weather):
    result = weather.copy()
    for column in ('Temperature', 'DewPoint'):
        if column in result:
            result[column] = ((pd.to_numeric(result[column], errors='coerce') - 273.15) * 9 / 5 + 32).round(1)
    if 'Wind' in result:
        result['Wind'] = (pd.to_numeric(result['Wind'], errors='coerce') * 2.2369362921).round(1)
    return result.rename(columns={'Temperature':'Temperature (°F)', 'DewPoint':'Dew point (°F)', 'Wind':'Wind (mph)'})

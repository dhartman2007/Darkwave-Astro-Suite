"""Location-specific ISS disk transits. All numerical search times are UTC."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import requests
from skyfield.api import EarthSatellite, Loader, wgs84
from sgp4.api import Satrec

ORBIT_URL = 'https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE'


def load_orbit(cache_dir, refresh=False):
    path = Path(cache_dir) / 'iss.tle'
    path.parent.mkdir(parents=True, exist_ok=True)
    if refresh or not path.exists() or datetime.now().timestamp() - path.stat().st_mtime > 3600:
        response = requests.get(ORBIT_URL, timeout=30)
        response.raise_for_status()
        text = response.text
        parse_orbit(text)  # Never replace a valid cache with an error response.
        path.write_text(text, encoding='utf-8')
    return parse_orbit(path.read_text(encoding='utf-8'))


def parse_orbit(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    pairs = [(a, b) for a, b in zip(lines, lines[1:])
             if a.startswith('1 25544') and b.startswith('2 25544')]
    if len(pairs) != 1:
        raise ValueError('The orbit provider did not return an ISS element set.')
    for line in pairs[0]:
        checksum = sum(int(c) if c.isdigit() else 1 if c == '-' else 0 for c in line[:68]) % 10
        if len(line) != 69 or not line[-1].isdigit() or checksum != int(line[-1]):
            raise ValueError('Invalid ISS element set checksum.')
    model = Satrec.twoline2rv(*pairs[0])
    if model.satnum != 25544 or not 0 < model.no_kozai or not 0 <= model.ecco < 1:
        raise ValueError('Invalid ISS orbital elements.')
    return pairs[0]


def minimum_time(function, left, right, tolerance=0.002):
    """Golden-section search, including sub-second events between coarse samples."""
    ratio = (5 ** 0.5 - 1) / 2
    c, d = right - ratio * (right-left), left + ratio * (right-left)
    fc, fd = function(c), function(d)
    while right-left > tolerance:
        if fc < fd:
            right, d, fd = d, c, fc
            c = right - ratio * (right-left)
            fc = function(c)
        else:
            left, c, fc = c, d, fd
            d = left + ratio * (right-left)
            fd = function(d)
    return (left+right)/2


def contact_time(function, inside, outside):
    if function(outside) <= 0:
        raise ValueError('Could not bracket transit contact.')
    while abs(outside-inside) > 0.002:
        middle = (inside+outside)/2
        if function(middle) <= 0:
            inside = middle
        else:
            outside = middle
    return (inside+outside)/2


def predict(cache_dir, lines, start, days, lat, lon, elevation=0, near_deg=1.0):
    """Search one to seven days; reject elements too distant from their epoch."""
    if start.tzinfo is None:
        raise ValueError('Search start must include a time zone.')
    if not 1 <= days <= 7 or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError('Invalid search period or location.')
    if not 0 <= near_deg <= 5:
        raise ValueError('Near-miss margin must be between 0 and 5 degrees.')
    loader = Loader(str(cache_dir))
    ts = loader.timescale()
    satellite = EarthSatellite(*lines, 'ISS', ts)
    start = start.astimezone(timezone.utc)
    end = start + timedelta(days=days)
    epoch = satellite.epoch.utc_datetime()
    if max(abs((start-epoch).total_seconds()), abs((end-epoch).total_seconds())) > 7*86400:
        raise ValueError('Search dates are more than seven days from the ISS orbit epoch. Refresh the orbit or choose nearer dates.')
    ephemeris = loader('de421.bsp')
    site = wgs84.latlon(lat, lon, elevation_m=elevation)
    observer = ephemeris['earth'] + site
    relative = satellite - site
    events = []
    for body, radius_km in [('sun', 695700.0), ('moon', 1737.4)]:
        def geometry(seconds):
            seconds = np.asarray(seconds)
            times = ts.from_datetimes([start+timedelta(seconds=float(s)) for s in seconds.reshape(-1)])
            iss = relative.at(times)
            if any(message is not None for message in iss.message):
                raise ValueError('ISS propagation failed for the selected dates.')
            target = observer.at(times).observe(ephemeris[body]).apparent()
            separation = iss.separation_from(target).degrees
            radius = np.degrees(np.arcsin(radius_km / target.distance().km))
            altitude, azimuth, distance = iss.altaz()
            target_altitude = target.altaz()[0].degrees
            values = (separation, radius, altitude.degrees, azimuth.degrees, distance.km, target_altitude)
            return tuple(float(v[0]) if seconds.ndim == 0 else v for v in values)

        # Day chunks bound memory. Overlap one sample at each boundary.
        for day in range(days):
            grid = np.arange(day*86400-10, (day+1)*86400+11, 10.0)
            sep, radius, alt, az, distance, target_alt = geometry(grid)
            candidates = np.flatnonzero((sep[1:-1] <= sep[:-2]) & (sep[1:-1] < sep[2:])) + 1
            for index in candidates:
                if alt[index] < -5 or target_alt[index] < -5:
                    continue
                center = minimum_time(lambda s: geometry(s)[0], grid[index-1], grid[index+1])
                if not day*86400 <= center < (day+1)*86400:
                    continue
                separation, disk, altitude, azimuth, range_km, body_alt = geometry(center)
                if altitude <= 0 or body_alt <= 0 or separation > disk + near_deg:
                    continue
                crossing = separation < disk
                ingress = egress = None
                if crossing:
                    def limb(s):
                        values = geometry(s)
                        return values[0] - values[1]
                    ingress = contact_time(limb, center, center-30)
                    egress = contact_time(limb, center, center+30)
                iso = lambda s: (start+timedelta(seconds=s)).isoformat(timespec='milliseconds')
                events.append(dict(body=body.title(), classification='Disk transit' if crossing else 'Near miss',
                    closest_utc=iso(center), ingress_utc=iso(ingress) if crossing else None,
                    egress_utc=iso(egress) if crossing else None,
                    duration_s=round(egress-ingress, 3) if crossing else None,
                    separation_deg=round(separation, 5), disk_radius_deg=round(disk, 5),
                    altitude_deg=round(altitude, 2), azimuth_deg=round(azimuth, 2),
                    range_km=round(range_km, 1)))
    return sorted(events, key=lambda row: row['closest_utc']), epoch.isoformat()

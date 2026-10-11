"""ISS pass visibility and geometric transit footprints on the WGS84 ellipsoid."""
from datetime import timedelta, timezone
import numpy as np
from skyfield.api import EarthSatellite, Loader, wgs84
from skyfield.framelib import itrs
from iss_transits import minimum_time

EARTH_AXES = np.array([6378.137, 6378.137, 6356.752314245])


def system(cache, lines, start, days):
    if start.tzinfo is None or not 1 <= days <= 7:
        raise ValueError('Use a timezone-aware start and one to seven days.')
    start = start.astimezone(timezone.utc)
    loader = Loader(str(cache))
    ts = loader.timescale()
    satellite = EarthSatellite(*lines, 'ISS', ts)
    epoch = satellite.epoch.utc_datetime()
    if max(abs((start-epoch).total_seconds()), abs((start+timedelta(days=days)-epoch).total_seconds())) > 7*86400:
        raise ValueError(f'ISS orbit epoch is {epoch.isoformat()}. The whole search must be within seven days of that time.')
    return start, ts, satellite, loader('de421.bsp'), epoch.isoformat()


def direction(azimuth):
    return ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
            'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'][int((azimuth % 360 + 11.25)//22.5) % 16]


def visible_mask(altitude, sun_altitude, sunlit, minimum=10):
    return (np.asarray(altitude) >= minimum) & (np.asarray(sun_altitude) < -6) & np.asarray(sunlit, dtype=bool)


def visible_passes(cache, lines, start, days, lat, lon, elevation=0, minimum=10):
    if not 0 <= minimum <= 80:
        raise ValueError('Pass minimum altitude must be between 0 and 80 degrees.')
    start, ts, satellite, ephemeris, epoch = system(cache, lines, start, days)
    site = wgs84.latlon(lat, lon, elevation_m=elevation)
    observer = ephemeris['earth'] + site
    relative = satellite-site
    end = start+timedelta(days=days)
    t0, t1 = ts.from_datetime(start), ts.from_datetime(end)
    event_times, codes = satellite.find_events(site, t0, t1, altitude_degrees=minimum)
    active = start if relative.at(t0).altaz()[0].degrees >= minimum else None
    periods = []
    for time, code in zip(event_times.utc_datetime(), codes):
        if code == 0:
            active = time
        elif code == 2 and active is not None:
            periods.append((active, time))
            active = None
    if active is not None:
        periods.append((active, end))
    result = []
    for rise, setting in periods:
        seconds = (setting-rise).total_seconds()
        if seconds <= 0:
            continue
        offsets = np.linspace(0, seconds, max(3, int(seconds/5)+2))
        times = ts.from_datetimes([rise+timedelta(seconds=float(s)) for s in offsets])
        position = relative.at(times)
        if any(message is not None for message in position.message):
            raise ValueError('ISS propagation failed.')
        alt, az, _ = position.altaz()
        sunlight = satellite.at(times).is_sunlit(ephemeris)
        sun_alt = observer.at(times).observe(ephemeris['sun']).apparent().altaz()[0].degrees
        visible = visible_mask(alt.degrees, sun_alt, sunlight, minimum)
        peak_index = int(np.argmax(alt.degrees))
        lo, hi = offsets[max(0, peak_index-1)], offsets[min(len(offsets)-1, peak_index+1)]
        def altitude(s):
            return relative.at(ts.from_datetime(rise+timedelta(seconds=float(s)))).altaz()[0].degrees
        peak = minimum_time(lambda s: -altitude(s), lo, hi)
        peak_date = rise+timedelta(seconds=float(peak))
        peak_time = ts.from_datetime(peak_date)
        peak_alt, peak_az, _ = relative.at(peak_time).altaz()
        spans = []
        indices = np.flatnonzero(visible)
        if len(indices):
            for group in np.split(indices, np.flatnonzero(np.diff(indices)>1)+1):
                spans.append(((rise+timedelta(seconds=float(offsets[group[0]]))).isoformat(timespec='seconds'),
                              (rise+timedelta(seconds=float(offsets[group[-1]]))).isoformat(timespec='seconds')))
        result.append(dict(rise_utc=rise.isoformat(timespec='seconds'), peak_utc=peak_date.isoformat(timespec='seconds'),
            set_utc=setting.isoformat(timespec='seconds'), rise_direction=direction(float(az.degrees[0])),
            peak_direction=direction(float(peak_az.degrees)), set_direction=direction(float(az.degrees[-1])),
            peak_altitude_deg=round(float(peak_alt.degrees), 1),
            sunlit_at_peak=bool(satellite.at(peak_time).is_sunlit(ephemeris)),
            potentially_visible=bool(visible.any()), visible_intervals_utc=spans))
    return result, epoch


def ray_ellipsoid(origin, ray):
    """Nearest forward intersection, NaN for rays missing Earth or pointing away."""
    origin, ray = np.asarray(origin, dtype=float), np.asarray(ray, dtype=float)
    scaled_origin, scaled_ray = origin/EARTH_AXES, ray/EARTH_AXES
    a = np.sum(scaled_ray**2, axis=-1)
    b = 2*np.sum(scaled_origin*scaled_ray, axis=-1)
    c = np.sum(scaled_origin**2, axis=-1)-1
    discriminant = b*b-4*a*c
    with np.errstate(invalid='ignore', divide='ignore'):
        length = (-b-np.sqrt(np.maximum(discriminant, 0)))/(2*a)
    valid = (discriminant >= 0) & (length >= 0) & (a > 0)
    return np.where(valid[..., None], origin+length[..., None]*ray, np.nan)


def latlon(points):
    points = np.asarray(points)
    x, y, z = points[..., 0], points[..., 1], points[..., 2]
    p = np.hypot(x, y)
    e2 = 1-(EARTH_AXES[2]/EARTH_AXES[0])**2
    latitude = np.arctan2(z, p*(1-e2))
    for _ in range(7):
        n = EARTH_AXES[0]/np.sqrt(1-e2*np.sin(latitude)**2)
        latitude = np.arctan2(z+e2*n*np.sin(latitude), p)
    return np.degrees(latitude), np.degrees(np.arctan2(y, x))


def distance_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2-lat1)/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin((lon2-lon1)/2)**2
    return 6371.0088*2*np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def disk_polygon(origin, body_position, body_radius, vertices=32):
    """Footprint of limb rays at one instant; horizon-clipped disks return no polygon."""
    vector = origin-body_position
    unit = vector/np.linalg.norm(vector)
    basis = np.cross(unit, [0., 0., 1.])
    if np.linalg.norm(basis) < .01:
        basis = np.cross(unit, [0., 1., 0.])
    basis /= np.linalg.norm(basis)
    perpendicular = np.cross(unit, basis)
    radius = np.arcsin(body_radius/np.linalg.norm(vector))
    angles = np.linspace(0, 2*np.pi, vertices, endpoint=False)
    rays = np.cos(radius)*unit + np.sin(radius)*(np.cos(angles)[:, None]*basis + np.sin(angles)[:, None]*perpendicular)
    points = ray_ellipsoid(origin, rays)
    if not np.isfinite(points).all():
        return []
    latitude, longitude = latlon(points)
    return [[float(lon), float(lat)] for lat, lon in zip(latitude, longitude)]


def nearby_paths(cache, lines, start, days, lat, lon, radius_km=200):
    if not 10 <= radius_km <= 500:
        raise ValueError('Travel radius must be between 10 and 500 km.')
    start, ts, satellite, ephemeris, epoch = system(cache, lines, start, days)
    results = []
    for body, body_radius in [('sun', 695700.), ('moon', 1737.4)]:
        def footprint(seconds):
            values = np.atleast_1d(seconds)
            times = ts.from_datetimes([start+timedelta(seconds=float(s)) for s in values])
            position = satellite.at(times)
            if any(message is not None for message in position.message):
                raise ValueError('ISS propagation failed.')
            origin = position.frame_xyz(itrs).km.T
            target = ephemeris['earth'].at(times).observe(ephemeris[body]).apparent().frame_xyz(itrs).km.T
            points = ray_ellipsoid(origin, origin-target)
            latitude, longitude = latlon(points)
            distances = distance_km(lat, lon, latitude, longitude)
            distances = np.where(np.isfinite(distances), distances, np.inf)
            return latitude, longitude, distances, origin, target
        for day in range(days):
            grid = np.arange(day*86400-10, (day+1)*86400+11, 10.0)
            _, _, distances, _, _ = footprint(grid)
            candidates = np.flatnonzero((distances[1:-1] <= distances[:-2]) &
                                       (distances[1:-1] < distances[2:])) + 1
            for index in candidates:
                center = minimum_time(lambda s: float(footprint(s)[2][0]), grid[index-1], grid[index+1], tolerance=.01)
                if not day*86400 <= center < (day+1)*86400:
                    continue
                latitude, longitude, distance, origin, target = footprint(center)
                if distance[0] > radius_km:
                    continue
                samples = np.arange(center-180, center+181, 2.)
                path_lat, path_lon, travel, origins, targets = footprint(samples)
                keep = np.isfinite(travel) & (travel <= radius_km*1.5)
                path = [[float(x), float(y)] for x, y in zip(path_lon[keep], path_lat[keep])]
                polygons = []
                previous = None
                for i in range(len(samples)):
                    polygon = disk_polygon(origins[i], targets[i], body_radius) if keep[i] else []
                    if polygon and previous:
                        polygons.append(swept_polygon(previous, polygon, lon))
                    previous = polygon
                results.append(dict(body=body.title(),
                    closest_utc=(start+timedelta(seconds=float(center))).isoformat(timespec='milliseconds'),
                    latitude=float(latitude[0]), longitude=float(longitude[0]),
                    centerline_distance_km=round(float(distance[0]), 2),
                    path=path, footprints=polygons,
                    closest_footprint=disk_polygon(origin[0], target[0], body_radius)))
    return sorted(results, key=lambda row: row['closest_utc']), epoch


def swept_polygon(first, second, reference_lon):
    """Convex envelope between adjacent two-second footprints, dateline-safe."""
    points = sorted(set((reference_lon+(x-reference_lon+180)%360-180, y)
                        for x, y in first+second))
    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    def half(sequence):
        result = []
        for point in sequence:
            while len(result) >= 2 and cross(result[-2], result[-1], point) <= 0:
                result.pop()
            result.append(point)
        return result
    return [list(point) for point in half(points)[:-1]+half(reversed(points))[:-1]]

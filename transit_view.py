from datetime import datetime, time
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from iss_transits import load_orbit, predict
from orbit_features import nearby_paths


def path_map(rows, lat, lon, tz):
    import pydeck as pdk
    from pass_view import local_time
    selected = st.selectbox('Nearby transit event', range(len(rows)), format_func=lambda i:
        f'{rows[i]["body"]} · {local_time(rows[i]["closest_utc"], tz)} · {rows[i]["centerline_distance_km"]:.1f} km to centerline')
    row = rows[selected]
    st.write(f'**Closest centerline point:** {row["latitude"]:.5f}°, {row["longitude"]:.5f}°')
    st.write(f'**Straight-line travel distance:** {row["centerline_distance_km"]:.1f} km ({row["centerline_distance_km"]/1.609344:.1f} miles). Road travel may be longer.')
    st.write('**Transit center at that point:** ' + local_time(row['closest_utc'], tz))
    st.link_button('Directions to this point', f'https://www.google.com/maps/dir/?api=1&origin={lat},{lon}&destination={row["latitude"]},{row["longitude"]}')
    def unwrap(points):
        return [[lon+(x-lon+180)%360-180, y] for x, y in points]
    pins = [dict(position=[lon, lat], label='Observing location', color=[240, 60, 60]),
            dict(position=unwrap([[row['longitude'], row['latitude']]])[0], label='Nearest centerline point', color=[20, 180, 80])]
    layers = [
        pdk.Layer('PolygonLayer', [dict(polygon=unwrap(p)) for p in row['footprints']],
                  get_polygon='polygon', get_fill_color=[50, 130, 230, 55], get_line_color=[50, 130, 230, 140],
                  stroked=True, get_line_width=30),
        pdk.Layer('PathLayer', [dict(path=unwrap(row['path']))], get_path='path',
                  get_color=[30, 110, 230], get_width=4, width_units='pixels'),
        pdk.Layer('ScatterplotLayer', pins, get_position='position', get_fill_color='color',
                  get_radius=7, radius_units='pixels', pickable=True)]
    st.pydeck_chart(pdk.Deck(layers=layers, map_provider='carto', map_style='light',
        initial_view_state=pdk.ViewState(latitude=(lat+row['latitude'])/2,
            longitude=(lon+pins[1]['position'][0])/2, zoom=6),
        tooltip={'text': '{label}'}))
    st.caption('Blue line: transit centerline. Blue band: approximate transit visibility corridor joining two-second disk footprints. Green point: nearest point on the centerline; red: your observing location. Map tiles require internet. Distances are to the centerline, not the band edge. Confirm site access and refresh orbital data before traveling; terrain, refraction and orbital uncertainty are not included.')
    export = pd.DataFrame([{k: v for k, v in event.items() if k not in ('path', 'footprints', 'closest_footprint')} for event in rows])
    st.download_button('Download nearby transit locations CSV', export.to_csv(index=False), 'nearby_transits.csv', 'text/csv')


def transits(day, lat, lon, tz, place, data):
    st.header('ISS Sun & Moon transits')
    st.write(f'Search from {place} ({lat:.5f}°, {lon:.5f}°). Times use {tz}.')
    st.caption('A disk transit means the ISS center crosses the Sun or Moon from this exact location. Near misses require a different observing location; they are not transits here.')
    st.warning('Solar observing requires a proper front-mounted solar filter. Never point an unfiltered telescope at the Sun.')
    with st.form('iss_search'):
        mode = st.radio('Transit search area', ['At my location', 'Nearby paths'], horizontal=True)
        date = st.date_input('Search start date', day)
        days = st.slider('Days to search', 1, 7, 3)
        elevation = st.number_input('Observer elevation (meters)', -500.0, 9000.0, 0.0, help='Used by At my location. Nearby paths use the WGS84 surface.')
        margin = st.slider('Include near misses within degrees of the disk edge', 0.0, 5.0, 1.0, 0.1, help='Used by At my location; nearby paths use the travel radius instead.')
        travel_radius = st.slider('Nearby centerline search radius (km)', 10, 500, 200, 10)
        refresh = st.checkbox('Refresh ISS orbital data', value=True)
        submitted = st.form_submit_button('Find ISS transits')
    identity = (date.isoformat(), days, lat, lon, tz, elevation, margin, mode, travel_radius)
    if submitted:
        st.session_state.pop('iss_result', None)
        try:
            with st.spinner('Loading orbital data and searching Sun and Moon alignments…'):
                cache = data / 'transits'
                lines = load_orbit(cache, refresh)
                start = datetime.combine(date, time(), ZoneInfo(tz))
                if mode == 'Nearby paths':
                    rows, epoch = nearby_paths(cache, lines, start, days, lat, lon, travel_radius)
                else:
                    rows, epoch = predict(cache, lines, start, days, lat, lon, elevation, margin)
                st.session_state['iss_result'] = (identity, rows, epoch)
        except Exception as error:
            st.error(f'Transit search unavailable: {error}')
    result = st.session_state.get('iss_result')
    if not result or result[0] != identity:
        return
    _, rows, epoch = result
    st.caption(f'ISS orbit epoch: {epoch}. Source: CelesTrak, NORAD 25544. JPL DE421 Sun/Moon ephemeris. First search downloads ephemeris data; subsequent searches reuse it.')
    st.info('These are geometric predictions, not guaranteed timings. ISS maneuvers and orbit errors can shift the narrow transit path. Refresh shortly before observing. Searches cover the selected local midnight plus the chosen number of 24-hour periods; altitudes are unrefracted and must be above the horizon.')
    if not rows:
        st.info('No transit centerlines found within the travel radius.' if mode == 'Nearby paths'
                else 'No ISS disk transits or near misses found for this location and search period.')
        return
    if mode == 'Nearby paths':
        st.write(f'**{len(rows)} nearby transit path(s)**')
        path_map(rows, lat, lon, tz)
        return
    frame = pd.DataFrame(rows)
    for column in ('closest_utc', 'ingress_utc', 'egress_utc'):
        frame[column.replace('_utc', '_local')] = frame[column].map(
            lambda value: datetime.fromisoformat(value).astimezone(ZoneInfo(tz)).isoformat(timespec='milliseconds') if pd.notna(value) else '')
    actual = frame[frame.classification == 'Disk transit']
    st.write(f'**{len(actual)} disk transit(s)** · {len(frame)-len(actual)} near miss(es)')
    for _, row in frame.iterrows():
        with st.container(border=True):
            st.subheader(f'{row.body} — {row.classification}')
            st.write(f'Closest alignment: **{row.closest_local}**')
            if row.classification == 'Disk transit':
                st.write(f'Ingress: {row.ingress_local} · Egress: {row.egress_local} · Duration: {row.duration_s:.3f} seconds')
            st.write(f'Altitude: {row.altitude_deg}° · Azimuth: {row.azimuth_deg}° · Range: {row.range_km} km')
            st.caption(f'Center separation: {row.separation_deg}° · Disk radius: {row.disk_radius_deg}°')
    st.download_button('Download transit predictions CSV', frame.to_csv(index=False),
                       f'iss_transits_{date.isoformat()}.csv', 'text/csv')

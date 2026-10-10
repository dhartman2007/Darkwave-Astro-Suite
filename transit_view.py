from datetime import datetime, time
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from iss_transits import load_orbit, predict


def transits(day, lat, lon, tz, place, data):
    st.header('ISS Sun & Moon transits')
    st.write(f'Search from {place} ({lat:.5f}°, {lon:.5f}°). Times use {tz}.')
    st.caption('A disk transit means the ISS center crosses the Sun or Moon from this exact location. Near misses require a different observing location; they are not transits here.')
    st.warning('Solar observing requires a proper front-mounted solar filter. Never point an unfiltered telescope at the Sun.')
    with st.form('iss_search'):
        date = st.date_input('Search start date', day)
        days = st.slider('Days to search', 1, 7, 3)
        elevation = st.number_input('Observer elevation (meters)', -500.0, 9000.0, 0.0)
        margin = st.slider('Include near misses within degrees of the disk edge', 0.0, 5.0, 1.0, 0.1)
        refresh = st.checkbox('Refresh ISS orbital data', value=True)
        submitted = st.form_submit_button('Find ISS transits')
    identity = (date.isoformat(), days, lat, lon, tz, elevation, margin)
    if submitted:
        st.session_state.pop('iss_result', None)
        try:
            with st.spinner('Loading orbital data and searching Sun and Moon alignments…'):
                cache = data / 'transits'
                lines = load_orbit(cache, refresh)
                start = datetime.combine(date, time(), ZoneInfo(tz))
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
        st.success('No ISS disk transits or near misses found for this location and search period.')
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

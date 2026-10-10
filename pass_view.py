from datetime import datetime, time
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from iss_transits import load_orbit
from orbit_features import visible_passes


def local_time(value, zone):
    return datetime.fromisoformat(value).astimezone(ZoneInfo(zone)).strftime('%b %d, %I:%M:%S %p %Z')


def pass_cards(rows, zone, visible_only=True):
    shown = [row for row in rows if row['potentially_visible'] or not visible_only]
    if not shown:
        st.info('No potentially visible ISS passes in this period.' if visible_only else 'No ISS passes above the selected altitude.')
    for row in shown:
        with st.container(border=True):
            st.write(f'**{local_time(row["peak_utc"], zone)} — peak {row["peak_altitude_deg"]}° {row["peak_direction"]}**')
            st.write(f'Above altitude threshold: {local_time(row["rise_utc"], zone)} ({row["rise_direction"]}) → {local_time(row["set_utc"], zone)} ({row["set_direction"]})')
            st.write('Sunlit at peak: ' + ('Yes' if row['sunlit_at_peak'] else 'No'))
            if row['visible_intervals_utc']:
                for a, b in row['visible_intervals_utc']:
                    st.caption(f'Potentially visible: {local_time(a, zone)} → {local_time(b, zone)}')
            else:
                st.caption('Daylight/twilight or Earth shadow prevents predicted naked-eye visibility.')


def passes(day, lat, lon, zone, place, data):
    st.header('ISS visible passes')
    st.write(f'{place} · {zone}')
    with st.form('iss_pass_form'):
        date = st.date_input('Pass search start date', day)
        days = st.slider('Pass search days', 1, 7, 3)
        minimum = st.slider('Minimum ISS altitude (degrees)', 0, 80, 10)
        elevation = st.number_input('Pass observer elevation (meters)', -500.0, 9000.0, 0.0)
        refresh = st.checkbox('Refresh ISS pass orbital data', True)
        submitted = st.form_submit_button('Find ISS passes')
    identity = (date.isoformat(), days, lat, lon, zone, minimum, elevation)
    if submitted:
        st.session_state.pop('iss_pass_result', None)
        try:
            with st.spinner('Calculating ISS altitude, sunlight and twilight…'):
                cache = data / 'transits'
                lines = load_orbit(cache, refresh)
                start = datetime.combine(date, time(), ZoneInfo(zone))
                rows, epoch = visible_passes(cache, lines, start, days, lat, lon, elevation, minimum)
                st.session_state['iss_pass_result'] = (identity, rows, epoch)
        except Exception as error:
            st.error(f'ISS passes unavailable: {error}')
    result = st.session_state.get('iss_pass_result')
    if not result or result[0] != identity:
        return
    _, rows, epoch = result
    st.caption(f'Orbit epoch: {epoch}. Potential visibility requires ISS altitude ≥ {minimum}°, a sunlit station, and Sun altitude below −6°. Visible intervals use at most five-second samples; clouds, brightness and obstructions are not modeled. Rise/set refer to the selected altitude threshold and can be clipped by the search period.')
    only = st.checkbox('Only potentially visible passes', True)
    pass_cards(rows, zone, only)
    if rows:
        frame = pd.DataFrame(rows)
        for column in ['rise_utc', 'peak_utc', 'set_utc']:
            frame[column.replace('_utc', '_local')] = frame[column].map(lambda value: local_time(value, zone))
        st.download_button('Download ISS passes CSV', frame.to_csv(index=False), 'iss_passes.csv', 'text/csv')

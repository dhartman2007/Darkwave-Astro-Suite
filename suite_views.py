"""Streamlit views for the integrated observing workflow."""
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from core import catalog, planned_targets, records, save
from suite import (Collector, LOGGER, import_logger_config, link_session,
                   read_suite, save_suite, session_links, target_candidates)

sys.path.insert(0, str(LOGGER))
from web_viewer import sessions, detail


@st.cache_resource
def collector():
    return Collector()


def localize(rows, zone):
    rows = [dict(row) for row in rows]
    for row in rows:
        for key, value in list(row.items()):
            if key.endswith('_utc') and value:
                try:
                    row[key[:-4] + '_local'] = datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(ZoneInfo(zone)).isoformat(timespec='seconds')
                except (TypeError, ValueError):
                    pass
    return rows


def overview(day, zone):
    config = read_suite()
    result = sessions(config['logs'])
    st.subheader('Your observing workspace')
    cols = st.columns(3)
    cols[0].metric('Planned tonight', len(planned_targets(day)))
    cols[1].metric('Recent sessions', len(result['sessions']))
    cols[2].metric('Suite collector', 'Running' if collector().running else 'Stopped')
    st.caption('Session history shows up to the latest 500 sessions. Collector status refers to the process started here.')
    st.markdown('Choose **Planner** to build your night, **Sessions** to review captured files and possible crossings, or **Logger & settings** to start collection.')
    planned = sorted(planned_targets(day))
    if planned:
        st.write('Tonight’s saved targets: ' + ', '.join(planned))
    if result['sessions']:
        st.dataframe(pd.DataFrame(localize(result['sessions'][:10], zone)).drop(columns=['conditions'], errors='ignore'), hide_index=True, use_container_width=True)
    else:
        st.info('No sessions found. Point the suite at your existing logs or start the collector.')
    st.caption('Forecasts are model predictions. Recorded weather is currently Open-Meteo model conditions; all-sky and local sensor measurements are future integrations.')


def logger_settings():
    config = read_suite()
    worker = collector()
    st.subheader('Logger & shared settings')
    st.caption('The observing location, time zone and Astrospheric key in the location panel are shared with the logger. Save location before starting. Restart the collector after changing settings.')
    with st.form('logger_configuration'):
        folder = st.text_input('Image folder to watch', config['folder'], help='A mapped Seestar share, mounted network folder or local image folder on this computer.')
        logs = st.text_input('Log folder', config['logs'], help='Use the logs folder from your existing Logger installation to retain its history.')
        poll = st.number_input('Scan interval (seconds)', 1, 3600, int(config['poll']))
        idle = st.number_input('Session inactivity threshold (seconds)', 1, 86400, int(config['idle']))
        st.caption('Optional checks send location/time to the corresponding providers. Candidates are predictions, not confirmed detections.')
        aircraft = st.checkbox('ADSB.lol aircraft candidates', config['aircraft'])
        satellites = st.checkbox('CelesTrak / SGP4 satellite candidates', config['satellites'])
        small_bodies = st.checkbox('JPL comet and asteroid candidates', config['small_bodies'])
        contact = st.text_input('JPL contact email', config['contact'])
        if st.form_submit_button('Save logger settings', disabled=worker.running):
            if not logs.strip():
                st.error('Enter a log folder.')
            elif small_bodies and not contact.strip():
                st.error('JPL checks require a contact email.')
            else:
                config = dict(folder=str(Path(folder).expanduser().resolve()) if folder.strip() else '', logs=str(Path(logs).expanduser().resolve()), poll=poll, idle=idle,
                              aircraft=aircraft, satellites=satellites,
                              small_bodies=small_bodies, contact=contact.strip())
                save_suite(config)
                st.success('Logger settings saved.')
    with st.expander('Use an existing SeeStar Logger installation'):
        st.caption('Stop the original logger first. Import keeps its log folder in place and preserves advanced candidate settings. Enter the image folder above; use the shared key field for Astrospheric.')
        source = st.text_input('Existing Logger installation folder')
        if st.button('Import existing logger configuration', disabled=worker.running):
            try:
                import_logger_config(source)
                st.rerun()
            except (OSError, ValueError) as error:
                st.error(str(error))
    controls()
    st.caption('Start creates a baseline of existing files. Only subsequent file changes create sessions. Stop requests graceful shutdown. The collector continues if you close the browser; use Stop before closing the suite console.')


@st.fragment(run_every='5s')
def controls():
    worker = collector()
    st.write('Collector: ' + ('Running' if worker.running else 'Stopped'))
    cols = st.columns(2)
    if cols[0].button('Start collector', disabled=worker.running):
        try:
            worker.start(read_suite())
            st.rerun(scope='fragment')
        except (OSError, ValueError) as error:
            st.error(str(error))
    if cols[1].button('Stop collector', disabled=not worker.running):
        worker.stop()
        st.info('Stop requested; waiting for the active scan and workers.')
    if worker.process is not None and not worker.running and worker.process.returncode:
        st.error(f'Collector exited with code {worker.process.returncode}. See output below.')
    with st.expander('Collector output', expanded=True):
        st.code(worker.output() or 'No collector started in this suite process yet.', language='text')


def session_history(zone):
    st.subheader('Observing sessions')
    st.caption('File activity estimates session timing. Possible crossings and small-body candidates are predictions. Missing or failed checks are unavailable, not zero detections.')
    if st.button('Refresh sessions'):
        st.rerun()
    config = read_suite()
    response = sessions(config['logs'])
    rows = localize(response['sessions'], zone)
    if not rows:
        st.info(response['status'])
        return
    links = session_links(config['logs'])
    query = st.text_input('Filter session target or status')
    selected_rows = [row for row in rows if query.casefold() in (row['target_folder'] + ' ' + row['status']).casefold()]
    if not selected_rows:
        st.info('No matching sessions.')
        return
    table = [{**{key: value for key, value in row.items() if key != 'conditions'},
              'catalog_object': links.get(row['id'], '')} for row in selected_rows]
    frame = pd.DataFrame(table)
    st.dataframe(frame, hide_index=True, use_container_width=True)
    st.download_button('Export displayed sessions CSV', frame.to_csv(index=False).encode('utf-8'), 'darkwave-sessions.csv', 'text/csv')
    identity = st.selectbox('Inspect session', [r['id'] for r in selected_rows],
                            format_func=lambda value: next(f"#{r['id']} · {r['target_folder']} · {r.get('start_observed_local', '')}" for r in selected_rows if r['id'] == value))
    row = next(r for r in selected_rows if r['id'] == identity)
    st.write('Session conditions (recorded model data)')
    st.json(row['conditions'])
    result = detail(config['logs'], identity)
    st.write('Predicted candidates; N/A means unavailable or unchecked')
    for col, name in zip(st.columns(4), ['aircraft', 'satellites', 'comets', 'asteroids']):
        value = result['counts'][name]
        col.metric(name.title(), 'N/A' if value is None else value)
    for name, section in result.items():
        if name == 'counts':
            continue
        with st.expander(name.replace('_', ' ').title()):
            st.caption(f"{section['status']} · latest {section['limit']} rows maximum")
            if section['rows']:
                st.dataframe(pd.DataFrame(localize(section['rows'], zone)), hide_index=True, use_container_width=True)
    with st.expander('Link to a catalog target / review imaging status'):
        objects = catalog()
        suggestions = target_candidates(row['target_folder'], objects)
        current = links.get(identity)
        names = sorted(set(objects.Name))
        default = current if current in names else (suggestions[0] if suggestions else names[0])
        name = st.selectbox('Catalog object', names, index=names.index(default), key=f'catalog-{identity}')
        if st.button('Save session link'):
            link_session(config['logs'], identity, name)
            st.success(f'Session linked to {name}. Imaging status is unchanged.')
        imaging = records()
        matches = imaging[imaging.object == name]
        existing = matches.iloc[0].to_dict() if not matches.empty else {}
        with st.form(f'imaging-review-{identity}-{name}'):
            imaged = st.checkbox('Imaged', bool(existing.get('imaged', False)))
            reimage = st.checkbox('Needs reimage', bool(existing.get('reimage', False)))
            first = st.text_input('First imaging date (YYYY-MM-DD)', existing.get('first_date') or '')
            image = st.text_input('Personal image link', existing.get('image_url') or '')
            notes = st.text_area('Notes', existing.get('notes') or '')
            if st.form_submit_button('Save reviewed imaging status'):
                try:
                    if first:
                        datetime.strptime(first, '%Y-%m-%d')
                    save(name, imaged, reimage, first, image, notes)
                    link_session(config['logs'], identity, name)
                    st.success('Imaging record and session link saved.')
                except ValueError:
                    st.error('Use YYYY-MM-DD for the first imaging date.')

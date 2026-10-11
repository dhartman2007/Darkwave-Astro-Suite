"""Local equipment inventory; never overwrite another suite setting file."""
import json
import math
from pathlib import Path
from uuid import uuid4

DEFAULT = dict(id='seestar-default', name='Seestar S50', kind='Seestar',
               telescope='Seestar S50', camera='Built-in camera', aperture_mm=50.0,
               focal_length_mm=250.0, filters=['Built-in dual-band'],
               fov_long=2.8, fov_short=1.575, notes='')


def read_equipment(data):
    path = Path(data) / 'equipment.json'
    if not path.exists():
        return {'active': DEFAULT['id'], 'profiles': [dict(DEFAULT)]}
    config = json.loads(path.read_text(encoding='utf-8'))
    if not config.get('profiles'):
        raise ValueError('Equipment file has no profiles.')
    return config


def active_equipment(data):
    config = read_equipment(data)
    return next((p for p in config['profiles'] if p['id'] == config['active']), config['profiles'][0])


def save_equipment(data, config):
    profiles = config['profiles']
    ids = [p['id'] for p in profiles]
    if not profiles or len(ids) != len(set(ids)) or config['active'] not in ids:
        raise ValueError('Choose a valid active equipment profile.')
    for profile in profiles:
        if not profile['name'].strip() or not profile['telescope'].strip():
            raise ValueError('Enter a profile name and telescope.')
        if not all(math.isfinite(float(profile[k])) and 0.01 <= float(profile[k]) <= 180
                   for k in ('fov_long', 'fov_short')):
            raise ValueError('Frame dimensions must be between 0.01 and 180 degrees.')
        if profile['fov_short'] > profile['fov_long']:
            raise ValueError('The frame long side must be at least the short side.')
        if not all(math.isfinite(float(profile[k])) and float(profile[k]) > 0
                   for k in ('aperture_mm', 'focal_length_mm')):
            raise ValueError('Aperture and focal length must be positive.')
    directory = Path(data)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / 'equipment.json.tmp'
    temporary.write_text(json.dumps(config, indent=2), encoding='utf-8')
    temporary.replace(directory / 'equipment.json')


def field_of_view(sensor_mm, focal_mm):
    if sensor_mm <= 0 or focal_mm <= 0:
        raise ValueError('Sensor size and focal length must be positive.')
    return math.degrees(2 * math.atan(sensor_mm / (2 * focal_mm)))


def equipment_filter(object_type, profile):
    emission = object_type in {'PN', 'HII', 'EmN', 'SNR', 'Cl+N'}
    filters = profile.get('filters', [])
    narrow = [f for f in filters if any(word in f.lower() for word in
              ('dual', 'narrow', 'h-alpha', 'ha/', 'oiii', 'o-iii', 'uhc'))]
    if emission and narrow:
        return 'Available emission-line option: ' + ', '.join(narrow) + '. Check its bandpasses and camera compatibility.'
    if emission:
        return 'No emission-line filter listed. Broadband imaging is possible; prioritize darker, Moon-free windows.'
    return 'Use an unfiltered or broadband setup for this target; listed narrow/dual-band filters suppress much of its light.'


def equipment_view(data):
    import streamlit as st
    config = read_equipment(data)
    st.header('Equipment profiles')
    st.caption('The active profile supplies the Planner and PDF frame dimensions and available-filter guidance. Exposure estimates are not calibrated for arbitrary instruments.')
    profiles = config['profiles']
    selected = st.selectbox('Edit profile', [p['id'] for p in profiles] + ['new'],
                            format_func=lambda key: 'Create a new profile' if key == 'new'
                            else next(p['name'] for p in profiles if p['id'] == key))
    profile = next((p for p in profiles if p['id'] == selected), dict(DEFAULT, id='new', name='New equipment'))
    with st.form('equipment_' + selected):
        name = st.text_input('Profile name', profile['name'])
        kind = st.selectbox('Equipment type', ['Seestar', 'Telescope + camera'],
                            index=0 if profile['kind'] == 'Seestar' else 1)
        telescope = st.text_input('Telescope', profile['telescope'])
        camera = st.text_input('Camera', profile['camera'])
        aperture = st.number_input('Aperture (mm)', 1.0, 2000.0, float(profile['aperture_mm']))
        focal = st.number_input('Focal length (mm)', 1.0, 20000.0, float(profile['focal_length_mm']))
        filters = st.text_input('Available filters (comma separated)', ', '.join(profile['filters']))
        long_side = st.number_input('Frame long side (degrees)', .01, 180.0, float(profile['fov_long']), format='%.4f')
        short_side = st.number_input('Frame short side (degrees)', .01, 180.0, float(profile['fov_short']), format='%.4f')
        notes = st.text_area('Equipment notes', profile['notes'])
        active = st.checkbox('Use this profile for planning', selected == config['active'])
        if st.form_submit_button('Save equipment profile'):
            key = uuid4().hex if selected == 'new' else selected
            item = dict(id=key, name=name.strip(), kind=kind, telescope=telescope.strip(),
                        camera=camera.strip(), aperture_mm=aperture, focal_length_mm=focal,
                        filters=[f.strip() for f in filters.split(',') if f.strip()],
                        fov_long=long_side, fov_short=short_side, notes=notes)
            updated = dict(active=key if active else config['active'],
                           profiles=[p for p in profiles if p['id'] != key] + [item])
            try:
                save_equipment(data, updated)
                st.success('Equipment saved. Select the active profile in the location panel to change planning equipment.')
            except (ValueError, OSError) as error:
                st.error(str(error))
    with st.expander('Calculate a camera field of view'):
        sensor_long = st.number_input('Sensor long side (mm)', .1, 100.0, 22.3)
        sensor_short = st.number_input('Sensor short side (mm)', .1, 100.0, 14.9)
        focal_calc = st.number_input('Effective focal length, including reducers (mm)', 1.0, 20000.0, 600.0)
        st.write(f'Calculated frame: {field_of_view(sensor_long, focal_calc):.4f}° × {field_of_view(sensor_short, focal_calc):.4f}°. Enter these in the profile above.')

"""One location/date-aware overview of saved targets, weather and ISS events."""
from datetime import datetime, time
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from core import catalog, plan, planned_targets, night_grid, forecast, forecast_us_units, DATA
from night_summary import night_summary
from equipment import active_equipment
from imaging_guidance import suitability
from iss_transits import load_orbit, predict
from orbit_features import visible_passes
from pass_view import pass_cards, local_time


@st.cache_data(max_entries=8, show_spinner=False)
def target_windows(names, day, lat, lon, zone, minimum, moon_sep, south, long_side, short_side):
    rows = catalog()
    selected = rows[rows.Name.isin(names)]
    result, _, _ = plan(selected, day, lat, lon, zone, minimum, moon_sep, south)
    framing = {row.Name: suitability(row, long_side, short_side)[0] for _, row in selected.iterrows()}
    result['Equipment framing'] = result.Name.map(framing)
    return result


@st.cache_data(max_entries=8, show_spinner=False)
def moon_conditions(day, lat, lon, zone):
    return night_summary(night_grid(day, zone), lat, lon, zone)


def observing_dashboard(day, lat, lon, zone, place, minimum, moon_sep, south, long_side, short_side, api_key):
    st.subheader('Tonight’s observing dashboard')
    st.caption(f'{place} · {day.isoformat()} · {zone}. Targets and Moon conditions cover local noon to next noon.')
    profile = active_equipment(DATA)
    st.write(f'**Equipment:** {profile["name"]} · {profile["telescope"]} · {profile["camera"]} · frame {long_side:g}° × {short_side:g}°')
    selected = tuple(sorted(planned_targets(day)))
    st.markdown('**Saved targets and observing windows**')
    if selected:
        try:
            with st.spinner('Calculating tonight’s saved targets…'):
                result = target_windows(selected, day, lat, lon, zone, minimum, moon_sep, south, long_side, short_side)
            st.dataframe(result.drop(columns='Name'), hide_index=True, use_container_width=True)
            missing = set(selected)-set(result.Name)
            if missing:
                st.caption('No catalog coordinates for: ' + ', '.join(sorted(missing)))
        except Exception as error:
            st.error(f'Target windows unavailable: {error}')
    else:
        st.info('Choose targets under Planner to fill tonight’s dashboard.')
    with st.expander('Moon, Sun and twilight tonight', expanded=True):
        try:
            for label, value in moon_conditions(day, lat, lon, zone):
                st.write(f'**{label}:** {value}')
            st.caption('Approximate geometric planning conditions, not a weather or skyline forecast.')
        except Exception as error:
            st.error(f'Moon conditions unavailable: {error}')
    st.markdown('**Weather for tonight**')
    if st.button('Refresh dashboard weather', disabled=not bool(api_key)):
        try:
            weather, metadata = forecast(api_key, lat, lon)
            st.session_state['weather'] = (lat, lon, weather, metadata)
        except Exception as error:
            st.session_state.pop('weather', None)
            st.error(f'Forecast unavailable: {error}')
    saved = st.session_state.get('weather')
    if saved and saved[:2] == (lat, lon):
        weather = forecast_us_units(saved[2]).copy()
        weather.index = pd.to_datetime(weather.index, utc=True).tz_convert(zone)
        grid = night_grid(day, zone)
        weather = weather[(weather.index >= pd.Timestamp(grid[0]).tz_convert(zone)) &
                          (weather.index <= pd.Timestamp(grid[-1]).tz_convert(zone))]
        if weather.empty:
            st.info('Loaded forecast has no coverage for this observing night.')
        else:
            st.dataframe(weather, use_container_width=True)
            st.caption('Loaded forecast model: temperature/dew point °F, wind mph; cloud/seeing/transparency retain provider scales. Refresh uses Astrospheric API credits.')
    else:
        st.info('Refresh to load Astrospheric weather.' if api_key else 'Enter your Astrospheric key in the location panel to load weather.')
    st.markdown('**ISS passes tonight and upcoming transits**')
    identity = (day.isoformat(), lat, lon, zone)
    if st.button('Refresh dashboard ISS events'):
        st.session_state.pop('dashboard_iss', None)
        try:
            with st.spinner('Loading ISS passes and three days of transits…'):
                cache = DATA / 'transits'
                lines = load_orbit(cache, refresh=True)
                noon = datetime.combine(day, time(12), ZoneInfo(zone))
                passes, epoch = visible_passes(cache, lines, noon, 1, lat, lon)
                events, _ = predict(cache, lines, noon, 3, lat, lon, near_deg=0)
                st.session_state['dashboard_iss'] = (identity, passes, events, epoch)
        except Exception as error:
            st.error(f'Dashboard ISS predictions unavailable: {error}')
    saved = st.session_state.get('dashboard_iss')
    if saved and saved[0] == identity:
        _, passes, events, epoch = saved
        st.caption(f'ISS orbit epoch: {epoch}. Tonight’s passes cover 24 hours from local noon; transits cover the next 72 hours. Visibility requires altitude ≥ 10°, station sunlit, and Sun below −6°. Weather and obstructions are not modeled.')
        pass_cards(passes, zone)
        st.markdown('**Sun/Moon disk transits at this location in the next three days**')
        if events:
            for event in events:
                st.write(f'{event["body"]} · {local_time(event["closest_utc"], zone)} · {event["duration_s"]:.3f} seconds')
        else:
            st.info('No disk transits predicted here. Use ISS Transits → Nearby paths to search surrounding locations.')
    else:
        st.caption('Refresh to calculate ISS events for this location and date. Full searches and transit maps are available in the ISS workspaces.')

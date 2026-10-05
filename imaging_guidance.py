"""Transparent planning heuristics, not instrument performance guarantees."""
import numpy as np
import pandas as pd
from astropy import units as u
from astropy.time import Time
from astropy.coordinates import SkyCoord, EarthLocation, AltAz, get_sun, get_body, GeocentricTrueEcliptic
from core import windows

EMISSION={'PN','HII','EmN','SNR','Cl+N'}
CLUSTERS={'OCl','GCl'}

def suitability(row, fov_long=2.8, fov_short=1.575):
    major=pd.to_numeric(row.get('MajAx',''),errors='coerce')
    minor=pd.to_numeric(row.get('MinAx',''),errors='coerce')
    if pd.isna(major):
        return 'Uncertain', 'Catalog size is missing; check the reference image and framing.'
    # Missing minor axis: conservative circular envelope.
    minor=major if pd.isna(minor) else minor
    major,minor=max(major,minor),min(major,minor)
    if major>fov_long*60 or minor>fov_short*60:
        return 'Mosaic / partial frame', 'Catalog size exceeds the configured single frame; plan a mosaic or photograph part of the object.'
    if major<1:
        return 'Challenging detail', 'Fits the frame, but is smaller than 1 arcminute; fine structure will be difficult with a 50 mm telescope.'
    magnitude=pd.to_numeric(row.get('V-Mag',''),errors='coerce')
    if pd.notna(magnitude) and magnitude>12:
        return 'Challenging / faint', 'Fits the frame, but is faint in the catalog; longer integration and darker skies are useful.'
    reason='Fits the configured frame, allowing rotation; detailed framing still depends on position angle and sky rotation.'
    if row.Type in EMISSION:reason+=' Emission-line light can benefit from a dual-band filter.'
    elif row.Type in CLUSTERS:reason+=' Broadband star clusters are practical targets.'
    else:reason+=' Faint extended structure needs dark skies and longer integration.'
    return 'Good starting target',reason

def guidance(row,dates,lat,lon,tz,minimum=30,moon_sep=30,south=0,fov_long=2.8,fov_short=1.575):
    ts=Time(dates)
    site=EarthLocation.from_geodetic(lon*u.deg,lat*u.deg)
    frame=AltAz(obstime=ts,location=site,pressure=0*u.hPa)
    target=SkyCoord(row.ra_deg*u.deg,row.dec_deg*u.deg).transform_to(frame)
    moon=get_body('moon',ts,location=site)
    ma=moon.transform_to(frame)
    dark=get_sun(ts).transform_to(frame).alt.deg < -18
    visible=dark & (target.alt.deg>=minimum)
    visible &= ~((target.az.deg>=90)&(target.az.deg<=270)&(target.alt.deg<south))
    separation=target.separation(ma).deg
    usable=visible & ((ma.alt.deg<=0)|(separation>=moon_sep))
    spans=windows(usable,dates,tz)
    longest=max(((b-a).total_seconds()/3600 for a,b in spans),default=0)
    index=int(np.flatnonzero(usable)[np.argmax(target.alt.deg[usable])]) if usable.any() else len(dates)//2
    time=ts[index]
    sun_geo=get_sun(time)
    moon_geo=get_body('moon',time)
    illumination=float((1-np.cos(sun_geo.separation(moon_geo).radian))*50)
    ecliptic=GeocentricTrueEcliptic(equinox=time)
    phase=float((moon_geo.transform_to(ecliptic).lon-sun_geo.transform_to(ecliptic).lon).wrap_at(360*u.deg).deg)%360
    waning=phase>180
    up=usable & (ma.alt.deg>0)
    overlap=float(up.sum()/12)
    moon_free=float((usable & (ma.alt.deg<=0)).sum()/12)
    minimum_sep=float(separation[up].min()) if up.any() else None
    if not usable.any():
        impact='No usable imaging window meets your selected altitude and Moon limits tonight.'
    elif not up.any():
        impact='The Moon is below the horizon throughout the usable windows; little direct moonlight interference is expected.'
    else:
        impact=f'The Moon is up for {overlap:.1f} usable hours; minimum target separation is {minimum_sep:.0f} degrees.'
        if illumination>=60 or minimum_sep<40:
            impact+=' Moonlight can noticeably reduce contrast in faint detail.'
        else:impact+=' Some sky-background brightening is possible; haze can worsen it.'
    trend='waning (fading)' if waning else 'waxing (brightening)'
    impact+=f' Illumination is approximately {illumination:.0f}% near the target’s best altitude; the Moon is {trend}. '
    impact+=('Lunar illumination decreases over the coming nights until new Moon; cloud and haze forecasts still need checking.' if waning else 'Lunar illumination increases toward full Moon; favor Moon-free windows when possible.')
    if row.Type in EMISSION:
        filter_note='Dual-band / LP filter can help emission-line contrast under moonlight. It does not remove all background light.'
    else:
        filter_note='Use broadband / LP filter off for natural star or galaxy light. Dual-band filters discard much of this target’s light; prefer Moon-free hours.'
    base=(0.5,1.5) if row.Type in CLUSTERS else (1.,3.) if row.Type=='PN' else (2.,4.)
    rating,reason=suitability(row,fov_long,fov_short)
    if rating=='Challenging / faint':base=(3.,6.)
    time_text=f'{base[0]:g}-{base[1]:g} hours of accepted stacked exposure; quick preview about 20-30 minutes.'
    if overlap>0 and row.Type not in EMISSION and illumination>=60:
        time_text+=' Prefer another Moon-free session for faint detail; more exposure alone cannot fully recover lost contrast.'
    if longest<base[0]:
        time_text+=f' Tonight’s longest usable window is only {longest:.1f} hours: collect what you can and combine additional nights.'
    else:time_text+=f' Tonight’s longest usable window is {longest:.1f} hours.'
    if rating=='Mosaic / partial frame':time_text+=' Time estimate is per panel; a mosaic needs more total imaging time.'
    return {'rating':rating,'reason':reason,'moon':impact,'filter':filter_note,'integration':time_text,'moon_free':moon_free,'assumptions':'Rule-based estimates for a 50 mm smart telescope, not measured performance. Actual results depend on surface brightness, sky brightness, transparency, tracking, processing and rejected frames. Wall-clock time will exceed accepted integration.','fov':f'Configured frame {fov_long:g} x {fov_short:g} degrees (approximate; adjustable in the sidebar).'}

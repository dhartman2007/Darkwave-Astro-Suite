"""Approximate rise/set and twilight events over the selected noon-to-noon night."""
import numpy as np
import pandas as pd
from astropy import units as u
from astropy.time import Time
from astropy.coordinates import EarthLocation, AltAz, get_sun, get_body

def night_summary(dates,lat,lon,tz):
    times=Time(dates)
    site=EarthLocation.from_geodetic(lon*u.deg,lat*u.deg)
    frame=AltAz(obstime=times,location=site,pressure=0*u.hPa)
    sun=get_sun(times)
    moon=get_body('moon',times,location=site)
    sun_alt=sun.transform_to(frame).alt.deg
    moon_alt=moon.transform_to(frame).alt.deg
    local=pd.DatetimeIndex(dates).tz_convert(tz)
    def crossing(values,level,rising):
        found=[]
        for i in range(len(values)-1):
            a,b=values[i]-level,values[i+1]-level
            if (a < 0 <= b) if rising else (a >= 0 > b):
                t=local[i]+(local[i+1]-local[i])*(-a/(b-a))
                found.append(t.strftime('%m/%d %I:%M %p %Z'))
        return ', '.join(found) or 'No event during this observing night'
    midnight_index=len(dates)//2
    # Approximation based on geocentric Sun-Moon elongation.
    geocentric_moon=get_body('moon',times[midnight_index])
    elongation=get_sun(times[midnight_index]).separation(geocentric_moon).radian
    illumination=(1-np.cos(elongation))*50
    return [
        ('Sunset / sunrise',crossing(sun_alt,-0.833,False)+' / '+crossing(sun_alt,-0.833,True)),
        ('Civil dusk / dawn',crossing(sun_alt,-6,False)+' / '+crossing(sun_alt,-6,True)),
        ('Nautical dusk / dawn',crossing(sun_alt,-12,False)+' / '+crossing(sun_alt,-12,True)),
        ('Astronomical dusk / dawn',crossing(sun_alt,-18,False)+' / '+crossing(sun_alt,-18,True)),
        ('Moonrise',crossing(moon_alt,-0.3,True)),
        ('Moonset',crossing(moon_alt,-0.3,False)),
        ('Moon illumination',f'Approximately {illumination:.1f}% near local midnight'),
    ]

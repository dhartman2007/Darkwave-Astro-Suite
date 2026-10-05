from datetime import date, timedelta
import pandas as pd
from core import night_grid, windows, plan, catalog

def test_dst():
    assert len(night_grid(date(2026,10,31),'America/Chicago'))==300
    assert len(night_grid(date(2026,3,7),'America/Chicago'))==276

def test_disjoint_windows():
    grid=night_grid(date(2026,10,4),'America/Chicago')
    spans=windows([True,False,True],grid,'America/Chicago')
    assert len(spans)==2
    assert spans[0][1]-spans[0][0]==timedelta(minutes=5)

def test_geometry():
    sample=pd.DataFrame([dict(Name='pole',label='Pole',Type='*',ra_deg=0.,dec_deg=90.)])
    result,_,_=plan(sample,date(2026,10,4),30.4,-87.68,'America/Chicago',minimum=35)
    assert result.Hours.iloc[0]==0
    assert abs(result['Peak °'].iloc[0]-30.4)<1
    result,_,_=plan(sample,date(2026,10,4),50.,-87.68,'America/Chicago',minimum=35,moon_sep=0)
    assert result.Hours.iloc[0]>0

def test_catalog():
    df=catalog()
    ids=set(int(v) for v in df.M if v.isdigit())
    assert ids==set(range(1,111))

import pytest
from core import parse_forecast, forecast

def test_forecast_documented_response():
    frame, _ = parse_forecast({'Cloud':[
        {'UTCForecastHour':'2026-10-04T16:00:00Z','Value':{'ActualValue':0}},
        {'UTCForecastHour':'2026-10-04T15:00:00Z','Value':{'ActualValue':12}}],
        'Seeing':None})
    assert list(frame.Cloud) == [12, 0]
    assert frame.index.tz is not None
    assert frame.index.tz_convert('America/Chicago')[0].hour == 10

@pytest.mark.parametrize('data', [{}, {'Cloud':None}, {'Cloud':[]}, 'No Data', {'ErrorInfo':'Invalid API key'}])
def test_forecast_rejects_empty_and_errors(data):
    with pytest.raises(ValueError):
        parse_forecast(data)

def test_forecast_http_error_preserved(monkeypatch):
    class Response:
        def json(self): return {'ErrorInfo':'Monthly credit cap exceeded'}
        def raise_for_status(self): raise AssertionError('Provider message should be used')
    monkeypatch.setattr('core.requests.post', lambda *a, **k: Response())
    with pytest.raises(ValueError, match='Monthly credit cap exceeded'):
        forecast('test-only',30.4,-87.68)

@pytest.mark.parametrize('hourly', [
    {'Cloud':[{'UTCForecastHour':'2026-10-04T15:00:00Z','Value':{'ActualValue':12}}]},
    [{'UTCForecastHour':'2026-10-04T15:00:00Z','Cloud':{'Value':{'ActualValue':12}}}],
    [{'UTCForecastHour':'2026-10-04T15:00:00Z','Cloud':{'ActualValue':12}}],
    [{'UTCForecastHour':'2026-10-04T15:00:00Z','Cloud':12}],
])
def test_nested_hourly_forecast(hourly):
    frame, _ = parse_forecast({'HourlyForecast':hourly})
    assert frame.Cloud.iloc[0] == 12

from core import forecast_us_units, remember_api_key, remembered_api_key

def test_us_forecast_units():
    raw = pd.DataFrame({'Temperature':[273.15,296.15], 'DewPoint':[273.15,295.15], 'Wind':[0,10]})
    converted = forecast_us_units(raw)
    assert list(converted['Temperature (°F)']) == [32,73.4]
    assert list(converted['Dew point (°F)']) == [32,71.6]
    assert list(converted['Wind (mph)']) == [0,22.4]
    assert raw.Temperature.iloc[0] == 273.15

def test_key_survives_restart_and_clear(tmp_path):
    assert remembered_api_key(tmp_path) == ''
    remember_api_key(' example-test-key ',tmp_path)
    assert remembered_api_key(tmp_path) == 'example-test-key'
    remember_api_key('',tmp_path)
    assert remembered_api_key(tmp_path) == ''

from core import planned_targets, set_planned

def test_nightly_plan_persistence_and_isolation(tmp_path,monkeypatch):
    monkeypatch.setattr('core.DATA',tmp_path)
    today=date(2026,10,4)
    tomorrow=today+timedelta(days=1)
    set_planned(today,'NGC0224',True)
    set_planned(today,'NGC0224',True)
    set_planned(tomorrow,'NGC0224',True)
    assert planned_targets(today)=={'NGC0224'}
    set_planned(today,'NGC0224',False)
    assert planned_targets(today)==set()
    assert planned_targets(tomorrow)=={'NGC0224'}

from night_summary import night_summary

def test_night_overview_local_events():
    summary=dict(night_summary(night_grid(date(2026,10,4),'America/Chicago'),30.4066,-87.6836,'America/Chicago'))
    assert '10/04' in summary['Sunset / sunrise']
    assert '10/05' in summary['Sunset / sunrise']
    assert 'CDT' in summary['Astronomical dusk / dawn']
    assert '%' in summary['Moon illumination']

from imaging_guidance import suitability, guidance

def test_suitability_framing_and_small_targets():
    obj=pd.Series({'MajAx':'180','MinAx':'60','Type':'G','V-Mag':'5'})
    assert suitability(obj)[0]=='Mosaic / partial frame'
    obj['MajAx']='0.5';obj['MinAx']='0.3'
    assert suitability(obj)[0]=='Challenging detail'
    obj['MajAx']='';assert suitability(obj)[0]=='Uncertain'

def test_guidance_flags_short_window_and_emission_filter():
    obj=pd.Series({'Name':'test','MajAx':'3','MinAx':'2','Type':'PN','V-Mag':'10','ra_deg':0.,'dec_deg':-90.})
    advice=guidance(obj,night_grid(date(2026,10,4),'America/Chicago'),30.4,-87.68,'America/Chicago')
    assert 'No usable imaging window' in advice['moon']
    assert 'additional nights' in advice['integration']
    assert 'Dual-band' in advice['filter']

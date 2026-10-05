"""Printable observing plans, with survey cutouts and local observing windows."""
from io import BytesIO
from pathlib import Path
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from functools import lru_cache
from xml.sax.saxutils import escape
import pandas as pd
import requests
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
from core import image_urls, track, forecast_us_units
from night_summary import night_summary
from imaging_guidance import guidance

TYPE_INFO = {
 'G': ('Galaxy', 'A distant system of stars, gas and dust. Its faint outer structure benefits from dark skies and longer total integration.'),
 'GPair': ('Galaxy pair', 'Two cataloged galaxies in the same field. Frame both components and allow space for faint outer structure.'),
 'GTrpl': ('Galaxy triplet', 'A group of three cataloged galaxies sharing the field.'),
 'GGroup': ('Galaxy group', 'A group of galaxies; check the complete group size when choosing your framing.'),
 'OCl': ('Open cluster', 'A loose group of stars formed together. Broadband imaging preserves their natural star colors.'),
 'GCl': ('Globular cluster', 'A dense, roughly spherical star cluster. Preserve the bright core while collecting faint outer stars.'),
 'PN': ('Planetary nebula', 'An expanding shell of gas shed by an aging star. The name does not mean it contains planets.'),
 'HII': ('Emission nebula', 'Ionized gas glowing around hot stars. Hydrogen emission is a prominent part of its light.'),
 'EmN': ('Emission nebula', 'Glowing interstellar gas. Its extended faint structure benefits from longer integration.'),
 'RfN': ('Reflection nebula', 'Dust reflecting nearby starlight. Broadband imaging captures the reflected continuum light.'),
 'SNR': ('Supernova remnant', 'Expanding gas and shock structures left by a stellar explosion.'),
 'Cl+N': ('Cluster and nebula', 'A star cluster associated with nebulosity; include both stars and surrounding gas in the frame.'),
 '*': ('Star', 'A cataloged stellar object; check its identification before planning deep-sky imaging.'),
 '**': ('Double star', 'A pair of stars close together on the sky.'),
 'Neb': ('Nebula', 'An extended cloud of interstellar gas or dust.'),
}
SPECIAL = {
 'NGC0205': ('M110 is an elliptical satellite galaxy of Andromeda (M31). Its smooth stellar light contrasts with the spiral structure of its larger neighbor.', 'https://science.nasa.gov/mission/hubble/science/explore-the-night-sky/hubble-messier-catalog/messier-110/'),
 'NGC0598': ('M33, the Triangulum Galaxy, is a nearby spiral galaxy in the Local Group. Its spiral arms contain many star-forming regions.', 'https://science.nasa.gov/mission/hubble/science/explore-the-night-sky/hubble-messier-catalog/messier-33/'),
}

def clean(value):
    return escape(str(value).replace('—','-').replace('–','-').replace('→','to').replace('’',"'"))

@lru_cache(maxsize=128)
def cutout(url):
    response = requests.get(url, timeout=25)
    response.raise_for_status()
    return response.content

def build_plan_pdf(catalog, results, dates, dark, day, place, lat, lon, tz, minimum, moon_sep, south, weather=None, weather_note="", fov_long=2.8, fov_short=1.575):
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=(612,792), rightMargin=42,leftMargin=42,topMargin=36,bottomMargin=38)
    font_dir=Path(__file__).parent/'fonts'
    pdfmetrics.registerFont(TTFont('PlanSans',str(font_dir/'DejaVuSans.ttf')))
    pdfmetrics.registerFont(TTFont('PlanSansBold',str(font_dir/'DejaVuSans-Bold.ttf')))
    styles=getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName='PlanSans'
    styles['Title'].fontName=styles['Heading2'].fontName='PlanSansBold'
    styles['Title'].fontSize=20
    styles['BodyText'].fontSize=10
    styles['BodyText'].leading=14
    styles.add(styles['BodyText'].clone('Caption',fontSize=8,leading=10,textColor=colors.HexColor('#526075')))
    story=[]
    def para(text, style='BodyText'): return Paragraph(clean(text),styles[style])
    def table(rows):
        item=Table([[para(k),para(v)] for k,v in rows],colWidths=[175,353])
        item.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(0,-1),colors.HexColor('#eaf0f7')),('LINEBELOW',(0,0),(-1,-1),.3,colors.HexColor('#d5dee9')),('LEFTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
        return item
    local=pd.DatetimeIndex(dates).tz_convert(tz)
    darkness=local[dark]
    darkness_text=f'{darkness[0]:%m/%d %I:%M %p} to {darkness[-1]+pd.Timedelta(minutes=5):%m/%d %I:%M %p}' if len(darkness) else 'No astronomical darkness'
    story.extend([para("Darkwave - Night Overview",'Title'),para(f'{day.isoformat()} | {place} | {tz}', 'Caption'),Spacer(1,10),para('Sun, Moon and darkness','Heading2'),table(night_summary(dates,lat,lon,tz)),Spacer(1,8),para('Times cover noon on the selected date through noon the following day. Rise/set times are approximate, interpolated from 5-minute samples with standard horizon corrections; terrain is not included.', 'Caption'),para('Astrospheric hourly forecast','Heading2')])
    if weather is not None and not weather.empty:
        forecast=forecast_us_units(weather)
        forecast.index=pd.to_datetime(forecast.index,utc=True).tz_convert(tz)
        start=local[0]+pd.Timedelta(hours=6)
        end=local[-1]-pd.Timedelta(hours=6)
        forecast=forecast[(forecast.index>=start)&(forecast.index<=end)]
        if not forecast.empty:
            columns=[c for c in ['Cloud','Transparency','Seeing','Temperature (°F)','Dew point (°F)','Wind (mph)'] if c in forecast]
            headers=['Local time']+[{'Cloud':'Cloud %','Transparency':'Transp.','Seeing':'Seeing','Temperature (°F)':'Temp °F','Dew point (°F)':'Dew °F','Wind (mph)':'Wind mph'}[c] for c in columns]
            cells=[[para(h,'Caption') for h in headers]]
            for stamp,row in forecast.iloc[:14].iterrows():
                cells.append([para(stamp.strftime('%m/%d %I%p'),'Caption')]+[para(f'{row[c]:.1f}' if pd.notna(row[c]) else '-', 'Caption') for c in columns])
            wt=Table(cells,colWidths=[84]+[444/len(columns)]*len(columns),repeatRows=1)
            wt.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf0f7')),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),.3,colors.HexColor('#d5dee9')),('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
            story.append(wt)
            story.append(para('Transparency and seeing retain Astrospheric numeric scales. Forecast covers approximately 6 PM to 6 AM; uncovered hours have no forecast. Weather can change after this PDF is generated.', 'Caption'))
        else:
            story.append(para('No Astrospheric forecast hours overlap this selected night. Change the date or refresh the forecast.'))
    else:
        story.append(para(weather_note or 'Astrospheric forecast unavailable. Enter your API key and generate the PDF again.'))
    story.append(para(f'Coordinates: {lat:.5f}, {lon:.5f}. Selected targets: {len(results)}. Target pages follow.', 'Caption'))
    story.append(PageBreak())
    for count,(_,result) in enumerate(results.iterrows()):
        row=catalog[catalog.Name==result.Name].iloc[0]
        if count: story.append(PageBreak())
        story.extend([para('Darkwave - Tonight\'s Plan','Title'),para(f'{day.isoformat()} | {place} | {tz}', 'Caption'),Spacer(1,12),para(row.label,'Heading2')])
        kind,description=TYPE_INFO.get(row.Type,(row.Type,'A deep-sky catalog entry. The classification and measurements below come from OpenNGC.'))
        description,source=SPECIAL.get(row.Name,(description,'https://github.com/mattiaverga/OpenNGC'))
        story.extend([para(description),Spacer(1,10)])
        url=image_urls(row)[0][1]
        try:
            pic=Image(BytesIO(cutout(url)),width=235,height=235)
            pic.hAlign='CENTER';story.append(pic)
        except Exception:
            raise ValueError(f'Could not load the reference image for {row.Name}. Check your internet connection and generate the PDF again.') from None
        story.extend([para('DSS2 color survey reference, served by CDS HiPS2FITS. Orientation/framing may differ from your telescope.', 'Caption'),Spacer(1,10)])
        curve=track(row,dates,lat,lon,tz)
        dark_curve=curve[dark]
        peak_time=dark_curve.Altitude.idxmax() if len(dark_curve) else None
        peak=f'{result["Peak °"]} degrees at {peak_time:%m/%d %I:%M %p}' if peak_time is not None else 'No darkness'
        fields=[('Best imaging window', result['Best window']+' (local, 24-hour time)'),('Usable / Moon-free hours',f'{result.Hours:.2f} / {result["Moon-free h"]:.2f} hours'),('Highest altitude in darkness',peak),('Astronomical darkness',darkness_text),('Object / constellation',f'{kind} / {row.Const}'),('RA / Dec (J2000)',f'{row.RA} / {row.Dec}'),('Angular size / V magnitude',f'{row.MajAx or "unknown"} x {row.MinAx or "unknown"} arcmin / {row["V-Mag"] or "unknown"}')]
        story.extend([table(fields),Spacer(1,9),para(f'Location: {lat:.5f}, {lon:.5f}. Limits: altitude >= {minimum} degrees; Moon separation >= {moon_sep} degrees when Moon is up; southern obstruction {south} degrees. Times sampled every 5 minutes. Best window is the longest interval meeting these limits.', 'Caption'),para('Weather is not included in this geometric imaging window. Check clouds, wind and dew before setting up.', 'Caption'),para('Description/catalog: '+source, 'Caption')])
        advice=guidance(row,dates,lat,lon,tz,minimum,moon_sep,south,fov_long,fov_short)
        story.extend([PageBreak(),para('SeeStar Imaging Guidance','Title'),para(row.label,'Heading2'),para(f'{day.isoformat()} | {place} | {tz}','Caption'),Spacer(1,14)])
        for heading,text in [('Suitability - '+advice['rating'],advice['reason']),('Framing',advice['fov']),('Moon impact tonight',advice['moon']),('Filter guidance',advice['filter']),('Suggested total integration',advice['integration'])]:
            story.extend([para(heading,'Heading2'),para(text),Spacer(1,8)])
        story.extend([para(f'Moon-free usable time: {advice["moon_free"]:.1f} hours. Best imaging window: {result["Best window"]} (local time).'),Spacer(1,10),para(advice['assumptions'],'Caption'),para('Instrument reference: https://www.seestar.com/products/seestar-s50-pro-smart-telescope','Caption')])
    def footer(canvas,doc):
        canvas.setFont('PlanSans',8);canvas.setFillColor(colors.HexColor('#526075'))
        canvas.drawString(42,22,'Darkwave Target Planner | Local observing times')
        canvas.drawRightString(570,22,f'Page {doc.page}')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()

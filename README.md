# Darkwave Astro Suite

One local browser application combining the Target Planner and SeeStar Logger.
Use **Overview**, **Planner**, **ISS Transits**, **Sessions**, and **Logger** across the top. The
desktop/mobile switch and black/red night display apply to every workspace.

## Get the suite

This is the standalone suite repository. The combined implementation was imported
from `dhartman2007/Astrophotography-Planner` at commit
`6254235848faee41c5a991b97b44259a3d399493`. The original Planner and
SeeStar Logger repositories remain separate. See `UPSTREAM.md` for provenance.

Until the import pull request is merged, clone its branch in PowerShell 7:

```powershell
git clone --branch codex/import-suite https://github.com/dhartman2007/Darkwave-Astro-Suite.git
Set-Location Darkwave-Astro-Suite
.\Start_Windows.bat
```

After merge, a normal clone uses `main`. This repository is private, so Git must
be authenticated with an account that can access it. The bundled `data/NGC.csv`,
`data/addendum.csv`, and `fonts/` support catalog loading and PDF export.
Personal databases, settings, API keys, and runtime output are not bundled.

## Start the suite

On Windows, run **Start_Windows.bat**. On Linux, including a Raspberry Pi, use
the virtual-environment commands below. The suite opens at
http://localhost:8501. Images and log files must be accessible to the computer
running Python; a phone browser does not provide access to its own filesystem.

1. In the location panel, save the observing location and time zone. The saved
   location is the collector's fallback; FITS site coordinates take precedence.
   The Astrospheric key field is shared with the collector.
2. Open **Logger** and enter the mounted Seestar image folder and log folder.
   Save settings, then click **Start collector**. Optional aircraft, satellite
   and JPL checks are disabled until explicitly enabled. JPL requires contact
   email. Provider requests use the existing logger's caching/credit behavior;
   Planner and Logger forecast caches remain separate.
3. Build tonight's target list under **Planner**. Review files, recorded model
   conditions and candidate coverage under **Sessions**. Link a session to its
   catalog target, then explicitly review Imaged / Needs reimage.
4. Click **Stop collector** and wait for Stopped before closing the suite
   console. Closing the browser alone leaves collection running. Collection
   must be started explicitly after restarting the suite.

The suite makes no telescope control connection. The first scan establishes a
baseline; existing images do not create historical sessions. Sessions estimate
file activity rather than actual integration time. Forecast/model conditions
are labeled; all-sky camera and local sensor feeds are not implemented here.

## Moving from the separate Planner and Logger

Use a new checkout of this repository in a separate directory. Do not replace
the original Planner checkout or change its Git remote. Before copying persistent
data, stop the Planner and original Logger and make timestamped backups of the
Planner `data/` folder and Logger `logs/` folder. Do not copy or synchronize
SQLite files while either application is writing to them.

Copy the existing Planner's `imaging.sqlite3`, `settings.json`, and, if present,
`astrospheric_api_key.txt` from its backed-up `data/` folder into the new suite's
`data/` folder. These files stay local and ignored by Git. Preserve the bundled
catalog CSVs. Import the original Logger folder as described below; the suite
can use its existing logs in place, so retain their backup before collection.

For rollback, stop suite collection, then restart the original applications
using the original installation folders and backed-up data if needed. Never run
the original Logger and suite collector against the same logs simultaneously.
This repository import changes application source only; it does not move your
installed data or modify the original repositories' main branches.

Stop the original Logger before enabling collection in the suite. Under
**Logger**, import its installation folder to use its existing `logs/` folder
in place and preserve advanced aircraft/satellite/JPL settings. Set the image
folder explicitly and enter your Astrospheric key in the shared location panel.
Alternatively, select the existing logs folder manually for read-only history.
Existing logger desktop launchers are retained under `logger/`.

Suite preferences are in `data/suite.json`; shared location settings and the
private key retain their existing paths. Worker configuration and output live
under `data/runtime/`. New log databases default to `data/logs/`. Runtime files,
personal databases and credentials are ignored by Git. The standalone repository imports only the clean source snapshot, not the
Planner's earlier Git history or its previously tracked personal database/key
files. Those files remain in the original repository's history.

The integration retains the original database schemas and links session IDs
to catalog objects in `imaging.sqlite3`. Logger sessions and candidate coverage
remain in their existing SQLite files, so no destructive database conversion
is needed. Back up the Planner data folder and selected Logger logs folder.
`DARKWAVE_SUITE_DATA` can select a different Planner/suite data directory.

This is a local suite integration. Multi-machine synchronization between the
NUC and traveling Pi, shared forecast caching, and a unified database migration
are separate work. Do not synchronize live SQLite files or run two collectors
against the same logs folder. Plan and image review do not automatically clear
Needs reimage, including M31 and NGC869.

## Validation

```
python -m pytest -q test_core.py test_suite.py test_iss_transits.py
python -m unittest discover -s logger/tests
```

The suite tests exercise shared settings, legacy configuration import,
session/catalog links, collector shutdown and duplicate-writer rejection.
The logger's native Windows GUI smoke test requires a built executable.

## Target Planner

Python application with a local browser interface. Install Python 3.11 or 3.12 from python.org on Windows, extract this entire folder to a writable location, and double-click Start_Windows.bat. Your browser opens at http://localhost:8501. Keep the console running; closing it stops the app.

On Linux/macOS:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py --server.address 127.0.0.1
```

## Features
- ISS Sun/Moon disk-transit predictions from the selected observing latitude, longitude, elevation and time zone. Open **ISS Transits**, select a start date and one to seven days, then click **Find ISS transits**. Results include local ingress/closest/egress times, duration, altitude, azimuth, range and CSV export. Near misses are explicitly separate from crossings at your location. This workspace reports results on demand; it does not send background notifications.
- ISS predictions use CelesTrak NORAD 25544 TLEs, Skyfield SGP4 propagation and the JPL DE421 ephemeris. Orbit data is cached for one hour under data/transits; the refresh checkbox requests a new orbit. The first search downloads DE421. Provider/download failures appear as errors, not empty successful searches. Search endpoints must be within seven days of the orbit epoch; older/far-future searches require a suitable element set and are rejected. Recheck close to the event: orbital errors and maneuvers can move the very narrow path. Times refine to milliseconds numerically but this is not a physical accuracy guarantee. Geometric center crossings exclude the ISS silhouette size, refraction, terrain, clouds and illumination constraints. Sun and Moon must be above the geometric horizon. Use a proper front-mounted solar filter for solar observing.
- OpenNGC NGC/IC catalog and Messier cross-references, including addendum objects M40 and M45. M102 uses NGC5866 as an explicit planner convention; its historical identification is disputed. Both CSVs are bundled; missing files are downloaded and cached in data/. No fabricated fallback catalog.
- Editable latitude, longitude, location name and IANA time zone. Foley is the default. Save location persists your choice. Longitude west is negative. Change the time zone when traveling; it is not inferred from coordinates.
- Selected evening date covers local noon through next local noon. Astronomical darkness, minimum altitude, optional southern obstruction, Moon separation, Moon-free hours, best continuous window and altitude chart. Local time includes DST.
- Search, catalog/type/status filters, at least-two-hour filter and CSV export.
- Persistent Imaged / Needs reimage checkboxes, first imaging date, personal image link and notes. Messier and NGC aliases share the same OpenNGC object record. No objects are premarked as completed. M31 and NGC869 can be marked Needs reimage.
- Three online survey reference views per object: DSS2 detail, DSS2 wide field and 2MASS infrared. These are not three independently curated photographs. Some survey coverage is missing or images may fail to load; links let you open them separately. Full professional/amateur photo curation is not bundled.
- Astrospheric v2 forecast integration, activated with your private API key. Calls consume provider credits. The key is saved locally in data/astrospheric_api_key.txt and loaded on restart. Clear the sidebar field to forget it. Forecast is shown separately from geometric visibility; no invented combined quality score.

## Data and limitations
Coordinates are transformed from ICRS with Astropy's built-in solar-system ephemeris, offline Earth orientation tables, and geometric (unrefracted) altitudes. Windows have approximately five-minute sampling precision; weather and exact skyline mapping do not change the geometric ranking. The simple southern obstruction covers azimuth 90–270 degrees. No telescope field-of-view/framing model is included in this first version.

OpenNGC can include duplicate designations, non-existent catalog entries and non-imaging object types. Entries without coordinates are excluded. NGC and IC are supplied together; use the catalog filter to choose. Initial download and images require internet access. The full catalog calculation takes longer than Messier; results are cached while the app is running.

Records are stored in data/imaging.sqlite3; settings in data/settings.json. Back up the entire data directory to preserve records. CSV backup exports records but automatic CSV restoration is not yet supplied.

Sources: https://github.com/mattiaverga/OpenNGC (catalog data CC BY-SA 4.0; upstream authors/contributors). Cached CSVs remain under that license. https://alasky.cds.unistra.fr/hips-image-services/hips2fits (CDS survey cutout service). https://www.astrospheric.com/DynamicContent/api_info_v2 (forecast API). Individual survey imagery retains its provider attribution and terms. Application source is provided for personal modification.

Forecast repair: empty responses now show an error; provider errors are preserved and timestamps validated. To update an existing installation, stop the app and replace only app.py and core.py from this package. Keep your existing data folder to preserve imaging records. Restart Start_Windows.bat, re-enter the key and refresh the forecast.

Weather temperatures and dew points display and export in Fahrenheit; wind displays and exports in mph. API keys are private to your local installation and are never included in distributed packages.

Check Explore in the target table to update the details, chart, gallery, and imaging form. The dropdown also remains available. Tonight’s plan checkboxes in the table are editable and save immediately.

Select an object and use Add to tonight’s plan to save it automatically for the selected observing date. Uncheck to remove it. Expand Tonight’s plan to view saved targets and export their observing windows. Plans persist locally in imaging.sqlite3.

Export tonight’s plan downloads only checked targets for the selected date, including chosen targets hidden by search filters. Export all displayed targets downloads the full current table.

PDF plans: click Generate tonight’s plan PDF, then Download tonight’s plan PDF. Each checked target gets an embedded survey image, a brief description, catalog details and local observing windows. Descriptions are based on object type, with specific descriptions for M110 and M33. Images require internet during generation; the saved PDF works offline. The opening overview includes available Astrospheric weather, Sun/Moon rise and set, twilight and approximate Moon illumination. To update: copy app.py, plan_pdf.py, requirements.txt and the fonts folder into the existing installation, preserving data; run Start_Windows.bat to install the new PDF dependency.

Night overview update: copy app.py, plan_pdf.py and night_summary.py into your installation. Generate PDF refreshes Astrospheric weather using the saved API key and consumes the provider’s normal API credits. Forecast rows cover 6 PM through roughly 6 AM in local time; unavailable coverage is labeled. Keep the fonts folder and your data folder.

Imaging guidance: targets now show a transparent heuristic SeeStar suitability rating, configurable approximate frame dimensions, Moon interference and phase, filter guidance, and estimated accepted stacked exposure. The PDF adds a guidance page after each target image/details page. These are planning estimates, not calibrated exposure predictions; field rotation, rejection rate, light pollution and actual surface brightness affect results. To update copy app.py, plan_pdf.py and imaging_guidance.py into the installation. Preserve data and fonts.


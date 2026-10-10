from copy import deepcopy
import numpy as np
import pytest
from equipment import DEFAULT, active_equipment, read_equipment, save_equipment, field_of_view, equipment_filter
from orbit_features import EARTH_AXES, ray_ellipsoid, latlon, distance_km, visible_mask, direction, disk_polygon, swept_polygon


def test_equipment_round_trip_and_active_selection(tmp_path):
    assert active_equipment(tmp_path)['name'] == 'Seestar S50'
    other = dict(DEFAULT, id='camera', name='Refractor', kind='Telescope + camera',
                 telescope='80 mm refractor', camera='Camera', aperture_mm=80,
                 fov_long=1.5, fov_short=1)
    save_equipment(tmp_path, {'active': 'camera', 'profiles': [deepcopy(DEFAULT), other]})
    assert active_equipment(tmp_path)['camera'] == 'Camera'
    assert len(read_equipment(tmp_path)['profiles']) == 2


def test_invalid_profile_does_not_replace_saved_inventory(tmp_path):
    config = read_equipment(tmp_path)
    save_equipment(tmp_path, config)
    original = (tmp_path/'equipment.json').read_text()
    config['profiles'][0]['fov_short'] = 5
    with pytest.raises(ValueError, match='long side'):
        save_equipment(tmp_path, config)
    assert (tmp_path/'equipment.json').read_text() == original


def test_camera_geometry_and_available_filters():
    assert field_of_view(20, 500) == pytest.approx(2.2915, abs=.0001)
    assert 'dual-band' in equipment_filter('HII', DEFAULT)
    assert 'unfiltered' in equipment_filter('G', DEFAULT)
    assert 'No emission-line' in equipment_filter('PN', dict(DEFAULT, filters=[]))


def test_forward_earth_intersections_and_misses():
    radius = EARTH_AXES[0]
    points = ray_ellipsoid([[radius+400, 0, 0]]*3, [[-1, 0, 0], [1, 0, 0], [0, 1, 0]])
    assert points[0] == pytest.approx([radius, 0, 0])
    assert np.isnan(points[1:]).all()
    latitude, longitude = latlon(points[0])
    assert latitude == pytest.approx(0)
    assert longitude == pytest.approx(0)


def test_ellipsoid_poles_and_antimeridian_distance():
    latitude, longitude = latlon([[0, 0, EARTH_AXES[2]], [-EARTH_AXES[0], 0, 0]])
    assert latitude == pytest.approx([90, 0])
    assert longitude[1] == pytest.approx(180)
    assert distance_km(0, 179.9, 0, -179.9) == pytest.approx(22.239, abs=.001)


def test_disk_footprint_limb_not_center_only():
    origin = np.array([EARTH_AXES[0]+400, 0., 0.])
    polygon = disk_polygon(origin, np.array([149600000., 0., 0.]), 695700)
    assert len(polygon) == 32
    latitude = np.array([point[1] for point in polygon])
    assert latitude.max() > 0 and latitude.min() < 0
    # Solar angular radius ~0.266° at a 400 km range produces a ~1.86 km radius.
    assert distance_km(0, 0, polygon[0][1], polygon[0][0]) == pytest.approx(1.86, abs=.02)


def test_visible_pass_requires_all_three_conditions():
    result = visible_mask([15, 15, 15, 5], [-10, 0, -10, -10], [True, True, False, True])
    assert result.tolist() == [True, False, False, False]
    assert direction(359) == 'N'
    assert direction(90) == 'E'
    assert direction(225) == 'SW'


def test_swept_corridor_crosses_dateline_without_spanning_globe():
    first = [[179.8, 0], [179.9, .1], [179.8, .2], [179.7, .1]]
    second = [[-179.9, 0], [-179.8, .1], [-179.9, .2], [-180, .1]]
    result = swept_polygon(first, second, 180)
    assert max(x for x, y in result)-min(x for x, y in result) < 1
    assert min(x for x, y in result) < 180 < max(x for x, y in result)

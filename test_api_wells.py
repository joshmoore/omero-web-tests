#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (C) 2017 University of Dundee & Open Microscopy Environment.
# All rights reserved.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Tests querying Wells with web json api."""

from omeroweb.testlib import IWebTest, _get_response_json
from django.core.urlresolvers import reverse
from django.conf import settings
import pytest
from test_api_projects import get_update_service, \
    get_connection, marshal_objects
from omero.model import ImageI, \
    LengthI, \
    PlateAcquisitionI, \
    PlateI, \
    WellI, \
    WellSampleI
from omero.model.enums import UnitsLength
from omero.rtypes import rstring, rint, unwrap, rtime
import json


def get_query_service(user):
    """Get the query_service for the given user's client."""
    return user[0].getSession().getQueryService()


def cmp_column_row(x, y):
    """Sort wells by row, then column."""
    sort_by_column = cmp(unwrap(x.column), unwrap(y.column))
    if sort_by_column == 0:
        return cmp(unwrap(x.row), unwrap(y.row))
    return sort_by_column


def remove_urls(marshalled):
    """Traverse a dict (Well) removing 'url:' values."""
    for key, val in marshalled.items():
        if key.startswith('url:'):
            del(marshalled[key])
        # We only traverse paths where we know urls are
        elif key == 'Image':
            remove_urls(val)
        elif key == 'WellSamples':
            for i in val:
                remove_urls(i)


def assert_objects(conn, json_objects, omero_ids_objects, dtype="Project",
                   group='-1', extra=None, opts=None):
    """
    Load objects from OMERO, via conn.getObjects().

    marshal with omero_marshal and compare with json_objects.
    omero_ids_objects can be IDs or list of omero.model objects.

    @param: extra       List of dicts containing expected extra json data
                        e.g. {'omero:childCount': 1}
    """
    pids = []
    for p in omero_ids_objects:
        try:
            pids.append(long(p))
        except TypeError:
            pids.append(p.id.val)
    conn.SERVICE_OPTS.setOmeroGroup(group)
    objs = conn.getObjects(dtype, pids, respect_order=True, opts=opts)
    objs = [p._obj for p in objs]
    expected = marshal_objects(objs)
    assert len(json_objects) == len(expected)
    for i, o1, o2 in zip(range(len(expected)), json_objects, expected):
        if extra is not None and i < len(extra):
            o2.update(extra[i])
        # We dump to json and re-load (same as test data). This means that
        # unicode has been handled in same way, e.g. Pixel size symbols.
        o2 = json.loads(json.dumps(o2))
        # remove any urls from json (tested elsewhere)
        remove_urls(o1)

        assert o1 == o2


class TestWells(IWebTest):
    """Tests querying Wells."""

    @pytest.fixture()
    def user1(self):
        """Return a new user in a read-annotate group."""
        group = self.new_group(perms='rwra--')
        return self.new_client_and_user(group=group)

    def create_plate_wells(self, user1, rows, cols, with_plate_acq=True):
        """Return Plate with Wells."""
        updateService = get_update_service(user1)
        plate = PlateI()
        plate.name = rstring('plate')
        plate = updateService.saveAndReturnObject(plate)

        # Single PlateAcquisition for plate
        if with_plate_acq:
            plate_acq = PlateAcquisitionI()
            plate_acq.name = rstring('plateacquisition')
            plate_acq.description = rstring('plateacquisition_description')
            plate_acq.maximumFieldCount = rint(3)
            plate_acq.startTime = rtime(1L)
            plate_acq.endTime = rtime(2L)
            plate_acq.plate = PlateI(plate.id.val, False)
            plate_acq = updateService.saveAndReturnObject(plate_acq)

        # Create Wells for plate
        for row in range(rows):
            for col in range(cols):
                # create Well
                well = WellI()
                well.column = rint(col)
                well.row = rint(row)
                well.plate = PlateI(plate.id.val, False)
                # Only wells in first Column have well-samples etc.
                if col == 0:
                    # Have 3 images/well-samples in these wells
                    for i in range(3):
                        image = self.create_test_image(
                            size_x=5, size_y=5, session=user1[0].getSession())
                        ws = WellSampleI()
                        ws.image = ImageI(image.id, False)
                        ws.well = well
                        ws.posX = LengthI(i * 10, UnitsLength.REFERENCEFRAME)
                        ws.posY = LengthI(i, UnitsLength.REFERENCEFRAME)
                        if with_plate_acq:
                            ws.setPlateAcquisition(
                                PlateAcquisitionI(plate_acq.id.val, False))
                        well.addWellSample(ws)
                updateService.saveObject(well)
        return plate

    @pytest.fixture()
    def small_plate(self, user1):
        """
        Create a small plate with 1 row and 2 columns.

        Two wells are created, but only the first has any Images (3).
        """
        return self.create_plate_wells(user1, 1, 2, with_plate_acq=False)

    @pytest.fixture()
    def bigger_plate(self, user1):
        """
        Create a bigger plate with 2 rows and 3 columns.

        Six wells are created, but only wells in the first
        column have any Images (3 in each Well).
        """
        return self.create_plate_wells(user1, 2, 3)

    def test_plate_wells(self, user1, small_plate, bigger_plate):
        """Test listing of Wells in a Plate."""
        conn = get_connection(user1)
        user_name = conn.getUser().getName()
        django_client = self.new_django_client(user_name, user_name)
        version = settings.API_VERSIONS[-1]

        wells_url = reverse('api_wells', kwargs={'api_version': version})

        # List ALL Wells in both plates
        rsp = _get_response_json(django_client, wells_url, {})
        assert len(rsp['data']) == 8

        # Filter Wells by Plate
        for plate, with_acq, well_count in zip([small_plate, bigger_plate],
                                               [False, True],
                                               [2, 6]):
            # Use Blitz Plates for listing Wells etc.
            plate_wrapper = conn.getObject('Plate', plate.id.val)
            wells = [w._obj for w in plate_wrapper.listChildren()]
            wells.sort(cmp_column_row)
            payload = {'plate': plate.id.val}
            rsp = _get_response_json(django_client, wells_url, payload)
            # Manual check that Images are loaded but Pixels are not
            assert len(rsp['data']) == well_count
            well_sample = rsp['data'][0]['WellSamples'][0]
            assert 'Image' in well_sample
            assert ('PlateAcquisition' in well_sample) == with_acq
            assert 'Pixels' not in well_sample['Image']

            assert_objects(conn, rsp['data'], wells, dtype='Well',
                           opts={'load_images': True})

    def test_well(self, user1, small_plate):
        """Test loading a single Well, with or without WellSamples."""
        conn = get_connection(user1)
        user_name = conn.getUser().getName()
        django_client = self.new_django_client(user_name, user_name)
        version = settings.API_VERSIONS[-1]

        small_plate = conn.getObject('Plate', small_plate.id.val)
        wells = [w._obj for w in small_plate.listChildren()]
        wells.sort(cmp_column_row)

        # plate has 2 wells. First has WellSamples, other doesn't
        for well, has_image in zip(wells, [True, False]):
            well_url = reverse('api_well', kwargs={'api_version': version,
                                                   'object_id': well.id.val})
            rsp = _get_response_json(django_client, well_url, {})
            # Manually check for image and Pixels loaded
            assert ('WellSamples' in rsp) == has_image
            if has_image:
                assert len(rsp['WellSamples']) == 3
                assert 'Pixels' in rsp['WellSamples'][0]['Image']
            assert_objects(conn, [rsp], [well], dtype='Well',
                           opts={'load_pixels': True})

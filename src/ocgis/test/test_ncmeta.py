import unittest
import netCDF4 as nc
from ocgis.interface.ncmeta import NcMetadata


class TestNcMeta(unittest.TestCase):
    uri = '/usr/local/climate_data/CanCM4/tasmax_day_CanCM4_decadal2000_r2i1p1_20010101-20101231.nc'

    def setUp(self):
        self.rootgrp = nc.Dataset(self.uri)

    def tearDown(self):
        self.rootgrp.close()

    def test_ncmeta(self):
        ncm = NcMetadata(self.rootgrp)
        self.assertEqual(ncm.keys(),['dataset','variables','dimensions'])


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()
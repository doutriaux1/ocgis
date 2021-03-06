import numpy as np
from ocgis.util.helpers import make_poly, iter_array
from shapely.geometry.multipolygon import MultiPolygon
from shapely.geometry.polygon import Polygon
from shapely.geometry.point import Point
from shapely.geometry.linestring import LineString


def _get_iter_(geom):
    try:
        it = iter(geom)
    except TypeError:
        it = [geom]
    return(it)

def wrap_coll(coll):
    for var in coll.variables.itervalues():
        wrap_var(var)

def wrap_var(var):
    right_clip = make_poly((-90,90),(180,360))
    left_clip = make_poly((-90,90),(-180,180))
    
    def _shift_(geom):
        try:
            coords = np.array(geom.exterior.coords)
            coords[:,0] = coords[:,0] - 360
            ret = Polygon(coords)
        except AttributeError:
            polygons = np.empty(len(geom),dtype=object)
            for ii,polygon in enumerate(geom):
                coords = np.array(polygon.exterior.coords)
                coords[:,0] = coords[:,0] - 360
                polygons[ii] = Polygon(coords)
            ret = MultiPolygon(polygons)
        return(ret)
    
    geoms = var.spatial._value
    if not isinstance(geoms[0,0],Point):
        for idx,geom in iter_array(geoms,return_value=True):
            bounds = np.array(geom.bounds)
            if np.all([bounds[0] > 180,bounds[2] > 180]):
                geoms[idx] = _shift_(geom)
            elif bounds[1] <= 180 and bounds[2] > 180:
                left = [poly for poly in _get_iter_(geom.intersection(left_clip))]
                right = [poly for poly in _get_iter_(_shift_(geom.intersection(right_clip)))]
                try:
                    geoms[idx] = MultiPolygon(left+right)
                except TypeError:
                    left = filter(lambda x: type(x) != LineString,left)
                    right = filter(lambda x: type(x) != LineString,right)
                    geoms[idx] = MultiPolygon(left+right)
            else:
                continue
    else:
        for idx,geom in iter_array(geoms,return_value=True):
            if geom.x > 180:
                geoms[idx] = Point(geom.x-360,geom.y)

def unwrap_geoms(geoms,left_max_x_bound):
    clip1 = make_poly((-90,90),(-180,left_max_x_bound))
    clip2 = make_poly((-90,90),(left_max_x_bound,180))
    
    def _shift_(polygon):
        coords = np.array(polygon.exterior.coords)
        coords[:,0] = coords[:,0] + 360
        return(Polygon(coords))
    
    def _transform_(geom,lon_cutoff):
        ## return the geometry iterator
        it = _get_iter_(geom)
        ## loop through the polygons determining if any coordinates need to be
        ## shifted and flag accordingly.
        adjust = False
        for polygon in it:
            coords = np.array(polygon.exterior.coords)
            if np.any(coords[:,0] < lon_cutoff):
                adjust = True
                break

        ## wrap the polygon if requested
        if adjust:
            ## intersection with the two regions
            left = geom.intersection(clip1)
            right = geom.intersection(clip2)
            
            ## pull out the right side polygons
            right_polygons = [poly for poly in _get_iter_(right)]
            
            ## adjust polygons falling the left window
            if isinstance(left,Polygon):
                left_polygons = [_shift_(left)]
            else:
                left_polygons = []
                for polygon in left:
                    left_polygons.append(_shift_(polygon))
            
            ## merge polygons into single unit
            try:
                ret = MultiPolygon(left_polygons + right_polygons)
            except TypeError:
                left = filter(lambda x: type(x) != LineString,left_polygons)
                right = filter(lambda x: type(x) != LineString,right_polygons)
                ret = MultiPolygon(left+right)
        
        ## if polygon does not need adjustment, just return it.
        else:
            ret = geom
        return(ret)
    
    ## update the polygons in place
    for geom in geoms:
        geom['geom'] = _transform_(geom['geom'],left_max_x_bound)
from warnings import warn
from ocgis.interface.ncmeta import NcMetadata
import inspect
import netCDF4 as nc
import datetime
from ocgis.util.helpers import iter_array, approx_resolution, vprint, contains
import numpy as np
from ocgis.interface.projection import WGS84
from shapely.geometry.polygon import Polygon
from shapely import prepared


class GlobalInterface(object):
    
    def __init__(self,rootgrp,target_var,overload={}):
        self.target_var = target_var
        self._dim_map = self._get_dimension_map_(rootgrp)
        self._meta = NcMetadata(rootgrp)
        
        interfaces = [TemporalInterface,LevelInterface,RowInterface,ColumnInterface]
        for interface in interfaces:
            try:
                argspec = inspect.getargspec(interface.__init__)
                overloads = argspec.args[-len(argspec.defaults):]
                kwds = dict(zip(overloads,[overload.get(o) for o in overloads]))
            except TypeError:
                kwds = {}
            setattr(self,interface._name,interface(self,**kwds))
        
        ## check for proj4 string to initialize a projection
        s_proj4 = overload.get('s_proj4')
        if s_proj4 is None:
            projection = WGS84()
        else:
            raise(NotImplementedError)
        
        ## get the geometric abstraction
        s_abstraction = overload.get('s_abstraction')
        if s_abstraction is None:
            if self._row.bounds is None:
                s_abstraction = 'point'
            else:
                s_abstraction = 'polygon'
        if s_abstraction == 'polygon':
            self.spatial = SpatialInterfacePolygon(self._row,self._col,projection)
        else:
            self.spatial = SpatialInterfacePoint(self._row,self._col,projection)
        
        import ipdb;ipdb.set_trace()
        
    def _get_dimension_map_(self,rootgrp):
        var = rootgrp.variables[self.target_var]
        dims = var.dimensions
        mp = dict.fromkeys(['T','Z','X','Y'])
        
        ## try to pull dimensions
        for dim in dims:
            try:
                dimvar = rootgrp.variables[dim]
                try:
                    axis = getattr(dimvar,'axis')
                except AttributeError:
                    warn('guessing dimension location with "axis" attribute missing')
                    axis = self._guess_by_location_(dims,dim)
                mp[axis] = {'variable':dimvar}
            except KeyError:
                raise(NotImplementedError)
            
        ## look for bounds variables
        bounds_names = set(['bounds','bnds'])
        for key,value in mp.iteritems():
            if value is None:
                continue
            bounds_var = None
            var = value['variable']
            intersection = list(bounds_names.intersection(set(var.ncattrs())))
            bounds_var = rootgrp.variables[getattr(var,intersection[0])]
            value.update({'bounds':bounds_var})
        return(mp)
            
    def _guess_by_location_(self,dims,target):
        mp = {3:{0:'T',1:'Y',2:'X'},
              4:{0:'T',2:'Y',3:'X',1:'Z'}}
        return(mp[len(dims)][dims.index(target)])
        
        
class AbstractInterface(object):
    _axis = None
    _name = None
    
    def __init__(self,gi):
        self.gi = gi
        self._ref = gi._dim_map[self._axis]
        if self._ref is not None:
            self._ref_var = self._ref.get('variable')
            self._ref_bnds = self._ref.get('bounds')
        else:
            self._ref_var = None
            self._ref_bnds = None
        
    def format(self):
        self.value = self._format_value_()
        self.bounds = self._format_bounds_()
        
    def _get_attribute_(self,overloaded,default,target='variable'):
        if overloaded is not None:
            ret = overloaded
        else:
            ret = getattr(self._ref[target],default)
        return(ret)
        
    def _format_value_(self):
        if self._ref_bnds is not None:
            ret = self._ref_var[:]
        else:
            ret = None
        return(ret)
    
    def _format_bounds_(self):
        if self._ref_bnds is not None:
            ret = self._ref_bnds[:]
        else:
            ret = None
        return(ret)
        
        
class TemporalInterface(AbstractInterface):
    _axis = 'T'
    _name = 'temporal'
    
    def __init__(self,gi,t_calendar=None,t_units=None):
        super(TemporalInterface,self).__init__(gi)
        
        self.calendar = self._get_attribute_(t_calendar,'calendar')
        self.units = self._get_attribute_(t_units,'units')
        
        self.format()
                
    def _format_value_(self):
        ret = nc.num2date(self._ref_var[:],self.units,self.calendar)
        self._to_datetime_(ret)
        return(ret)
    
    def _format_bounds_(self):
        ret = nc.num2date(self._ref_bnds[:],self.units,self.calendar)
        self._to_datetime_(ret)
        return(ret)
        
    def _to_datetime_(self,arr):
        for idx,t in iter_array(arr,return_value=True):
            arr[idx] = datetime.datetime(t.year,t.month,t.day,
                                         t.hour,t.minute,t.second)
            
            
class LevelInterface(AbstractInterface):
    _axis = 'Z'
    _name = 'level'
    
    def __init__(self,gi):
        super(LevelInterface,self).__init__(gi)
        self.format()
        
        
class RowInterface(AbstractInterface):
    _axis = 'Y'
    _name = '_row'
    
    def __init__(self,gi):
        super(RowInterface,self).__init__(gi)
        self.format()


class ColumnInterface(AbstractInterface):
    _axis = 'X'
    _name = '_col'
    
    def __init__(self,gi):
        super(ColumnInterface,self).__init__(gi)
        self.format()
        

class AbstractSpatialInterface(object):
    
    def __init__(self,row,col,projection):
        self.row = row
        self.col = col
        self.projection = projection
        
        self.is_360 = self._get_wrapping_()
        self.resolution = self._get_resolution_()
        
    def select(self,polygon=None):
        if polygon is None:
            return(self._get_all_geoms_())
        else:
            return(self._subset_(polygon))
        
    def _get_resolution_(self):
        return(approx_resolution(self.row.value))
        
    def _select_(self,polygon):
        raise(NotImplementedError)
        
    def _get_all_geoms_(self):
        raise(NotImplementedError)
        
    def _get_wrapping_(self):
        raise(NotImplementedError)


class SpatialInterfacePolygon(AbstractSpatialInterface):
    
    def __init__(self,*args,**kwds):
        super(self.__class__,self).__init__(*args,**kwds)
        
        self.min_col,self.min_row = self.get_min_bounds()
        self.max_col,self.max_row = self.get_max_bounds()
        
        self.real_col,self.real_row = np.meshgrid(
                                np.arange(0,len(self.col.bounds)),
                                np.arange(0,len(self.row.bounds)))

        self.shape = self.real_col.shape
        self.gid = np.ma.array(np.arange(1,self.real_col.shape[0]*
                                           self.real_col.shape[1]+1)\
                               .reshape(self.shape),
                               mask=False)
        
        import ipdb;ipdb.set_trace()
        
    def get_bounds(self,colidx):
        col,row = np.meshgrid(self.col.bounds[:,colidx],
                              self.row.bounds[:,colidx])
        return(col,row)
    
    def get_min_bounds(self):
        return(self.get_bounds(0))
    
    def get_max_bounds(self):
        return(self.get_bounds(1))
    
    def extent(self):
        minx = self.min_col.min()
        maxx = self.max_col.max()
        miny = self.min_row.min()
        maxy = self.max_row.max()
        poly = Polygon(((minx,miny),(maxx,miny),(maxx,maxy),(minx,maxy)))
        return(poly)
    
    def calc_weights(self,npd,geom):
        weight = np.ma.array(np.zeros((npd.shape[2],npd.shape[3]),dtype=float),
                             mask=npd.mask[0,0,:,:])
        for ii,jj in iter_array(weight):
            weight[ii,jj] = geom[ii,jj].area
        weight = weight/weight.max()
        return(weight)
    
    def _get_wrapping_(self):
        ## check for values over 180 in the bounds variables. if higher values
        ## exists, user geometries will need to be wrapped and data may be 
        ## wrapped later in the conversion process.
        if np.any(self.col.bounds > 180):
            is_360 = True
            ## iterate bounds coordinates to identify upper bound for left
            ## clip polygon for geometry wrapping.
            self.left_upper_bound = 0.0
            ref = self.col.bounds
            for idx in range(ref.shape[0]):
                if ref[idx,0] < 0 and ref[idx,1] > 0:
                    self.left_upper_bound = ref[idx,0]
                    break
        else:
            is_360 = False
            
        return(is_360)
    
    def _get_all_geoms_(self):
        geom = np.empty(self.gid.shape,dtype=object)
        min_col,max_col,min_row,max_row = self.min_col,self.max_col,self.min_row,self.max_row
        
        for ii,jj in iter_array(geom,use_mask=False):
            geom[ii,jj] = Polygon(((min_col[ii,jj],min_row[ii,jj]),
                                   (max_col[ii,jj],min_row[ii,jj]),
                                   (max_col[ii,jj],max_row[ii,jj]),
                                   (min_col[ii,jj],max_row[ii,jj])))

        row = self.real_row.reshape(-1)
        col = self.real_col.reshape(-1)
        
        return(geom,row,col)
    
    def _select_(self,polygon):
        vprint('entering select...')
#        prep_polygon = prepared.prep(polygon)
        emin_col,emin_row,emax_col,emax_row = polygon.envelope.bounds
        smin_col = contains(self.min_col,
                            emin_col,emax_col,
                            self.resolution)
        smax_col = contains(self.max_col,
                            emin_col,emax_col,
                            self.resolution)
        smin_row = contains(self.min_row,
                            emin_row,emax_row,
                            self.resolution)
        smax_row = contains(self.max_row,
                            emin_row,emax_row,
                            self.resolution)
        include = np.any((smin_col,smax_col),axis=0)*\
                  np.any((smin_row,smax_row),axis=0)
        vprint('initial subset complete.')
        
        vprint('building spatial index...')
        from ocgis.util.spatial import index as si
        grid = si.build_index_grid(30.0,polygon)
        index = si.build_index(polygon,grid)
        index_intersects = si.index_intersects
        
        ## construct the reference matrices
        geom = np.empty(self.gid.shape,dtype=object)
        row = np.array([],dtype=int)
        col = np.array([],dtype=int)
        
        def _append_(arr,value):
            arr.resize(arr.shape[0]+1,refcheck=False)
            arr[arr.shape[0]-1] = value
        
        real_row = self.real_row
        real_col = self.real_col
        min_row = self.min_row
        min_col = self.min_col
        max_row = self.max_row
        max_col = self.max_col
        
        vprint('starting main loop...')
        for ii,jj in iter_array(include,use_mask=False):
            if include[ii,jj]:
                test_geom = Polygon(((min_col[ii,jj],min_row[ii,jj]),
                                     (max_col[ii,jj],min_row[ii,jj]),
                                     (max_col[ii,jj],max_row[ii,jj]),
                                     (min_col[ii,jj],max_row[ii,jj])))
                geom[ii,jj] = test_geom
                if index_intersects(test_geom,index):
                    _append_(row,real_row[ii,jj])
                    _append_(col,real_col[ii,jj])
        vprint('main select loop finished.')
        
        return(geom,row,col)  
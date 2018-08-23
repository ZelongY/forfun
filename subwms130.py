# -*- coding: iso-8859-15 -*-
# =============================================================================
# Copyright (c) 2004, 2006 Sean C. Gillies
# Copyright (c) 2005 Nuxeo SARL <http://nuxeo.com>
#
# Authors : Sean Gillies <sgillies@frii.com>
#           Julien Anguenot <ja@nuxeo.com>
#
# Contact email: sgillies@frii.com
# =============================================================================

"""
API For Web Map Service version 1.3.0.
"""
import warnings
import six
from owslib.etree import etree
from owslib.util import (openURL, ServiceException, testXMLValue,
                         extract_xml_list, xmltag_split, OrderedDict, 
                         bind_url)
# from owslib.util import subcommon.nspath
from owslib.fgdc import Metadata
from owslib.iso import MD_Metadata
from owslib.crs import Crs
from owslib.namespaces import Namespaces
from owslib.map.common import WMSCapabilitiesReader
import owslib.map.subcommon as subcommon
from owslib.map.subcommon import SubWMSCapabilitiesReader
from wms130 import ContentMetadata, WebMapService_1_3_0, ServiceIdentification, ServiceProvider, OperationMetadata, ContactMetadata

try:                    # Python 3
    from urllib.parse import urlencode
except ImportError:     # Python 2
    from urllib import urlencode

from owslib.util import log
n = Namespaces()
WMS_NAMESPACE = n.get_namespace("wms")
OGC_NAMESPACE = n.get_namespace('ogc')

  
    #default namespace for subcommon.nspath is OWS common
OWS_NAMESPACE = 'http://www.opengis.net/ows/1.1'


class SubWebMapService_1_3_0(WebMapService_1_3_0):

    def __getitem__(self, name):
        ''' check contents dictionary to allow dict
        like access to service layers
        '''
        if name in self.__getattribute__('contents'):
            return self.__getattribute__('contents')[name]
        else:
            raise KeyError("No content named %s" % name)

    def __init__(self, url, version=None, xml=None, username=None,
                 password=None, parse_remote_metadata=False, timeout=30,
                 headers=None):
        """initialize"""
        self.url = url
        self.username = username
        self.password = password
        self.version = version
        self.timeout = timeout
        self.headers = headers
        self._capabilities = None

        # Authentication handled by Reader
        # Check whether required parameters (service, version, request) exist. If not, the missing parameters will be added.
        reader = SubWMSCapabilitiesReader(self.version, url=self.url,
                                       un=self.username, pw=self.password,
                                       headers=headers)
        if xml:  # read from stored xml
            self._capabilities = reader.readString(xml)
        else:  # read from server
            self._capabilities = reader.read(self.url, timeout=self.timeout)

        self.request = reader.request

        # avoid building capabilities metadata if the
        # response is a ServiceExceptionReport
        if subcommon.WMSExceptionDetection(self._capabilities):
            raise ServiceException("ServiceException")

        # build metadata objects
        self._buildMetadata(parse_remote_metadata)
        
    
    def __build_getlegendgraphic_request(self, layer=None, styles=None,
               format=None, size=None, time=None, transparent=False,
               bgcolor=None, exceptions=None, **kwargs):

        request = {'service': 'WMS', 'version': self.version, 'request': 'GetLegendGraphic'}

        # check layers and styles
        request['layer'] = str(layer)
        if styles:
            assert len(styles) == len(layers)
            request['styles'] = ','.join(styles)
        else:
            request['styles'] = ''

        # size
        request['width'] = str(size[0])
        request['height'] = str(size[1])

        request['format'] = str(format)
        request['transparent'] = str(transparent).upper()
        request['bgcolor'] = '0x' + bgcolor[1:7]
        request['exceptions'] = str(exceptions)

        if time is not None:
            request['time'] = str(time)

        if kwargs:
            for kw in kwargs:
                request[kw]=kwargs[kw]
        return request

    def getlegendgraphic(self, layer=None, styles=None,
               format=None, size=None, time=None, transparent=False,
               bgcolor='#FFFFFF',
               exceptions='application/vnd.ogc.se_xml',
               method='Get',
               timeout=None,
               **kwargs
               ):
        # Extract legend url from layer styles
        request = None
        request = self.contents[layer].getlegendgraphicrequest()

        # Construct legend url
        if request is None:
            try:
                base_url = next((m.get('url') for m in self.getOperationByName('GetLegendGraphic').methods if m.get('type').lower() == method.lower()))
            except StopIteration:
                base_url = self.url
            request = {'version': self.version, 'request': 'GetLegendGraphic'}

            request = self.__build_getlegendgraphic_request(
                layer=layer,
                styles=styles,
                format=format,
                size=size,
                time=time,
                transparent=transparent,
                bgcolor=bgcolor,
                exceptions=exceptions,
                **kwargs)

            data = urlencode(request)
            ##########
            #Replace + with %20
            ##########
            data = data.replace("+", "%20")

            request = bind_url(base_url) + data

        u = openURL(request, method, username=self.username, password=self.password, timeout=timeout or self.timeout)

        # check for service exceptions, and return
        if u.info()['Content-Type'].split(';')[0] in ['application/vnd.ogc.se_xml']:
            se_xml = u.read()
            se_tree = etree.fromstring(se_xml)
            err_message = six.text_type(se_tree.find('ServiceException').text).strip() + request
            raise ServiceException(err_message)
        return u, request

    def _buildMetadata(self, parse_remote_metadata=False):
        '''set up capabilities metadata objects:'''

        self.updateSequence = self._capabilities.attrib.get('updateSequence')
        
        '''
        Judge whether xmlns is adopted
        '''
        global WMS_NAMESPACE
        if not subcommon.ns_existence(self._capabilities):
            WMS_NAMESPACE = None

        # SubServiceIdentification metadata
        serviceelem = self._capabilities.find(subcommon.nspath('Service',
                                              ns=WMS_NAMESPACE))
        self.identification = SubServiceIdentification(serviceelem, self.version)

        # serviceProvider metadata
        self.provider = SubServiceProvider(serviceelem)

        # serviceOperations metadata
        self.operations = []
        for elem in self._capabilities.find(subcommon.nspath('Capability/Request',
                                            ns=WMS_NAMESPACE))[:]:
            self.operations.append(SubOperationMetadata(elem))

        # serviceContents metadata: our assumption is that services use a top-level
        # layer as a metadata organizer, nothing more.
        self.contents = OrderedDict()
        caps = self._capabilities.find(subcommon.nspath('Capability', WMS_NAMESPACE))

        # recursively gather content metadata for all layer elements.
        # To the WebMapService.contents store only metadata of named layers.
        def gather_layers(parent_elem, parent_metadata, layerid):
            layers = []
            for index, elem in enumerate(parent_elem.findall(subcommon.nspath('Layer', WMS_NAMESPACE))):
                cm = SubContentMetadata(elem, parent=parent_metadata, index=index+1, parse_remote_metadata=parse_remote_metadata)
                # Only get the layers with a name element
                if cm.id:
                    if cm.id in self.contents:
                        warnings.warn('Content metadata for layer "%s" already exists. Using child layer' % cm.id)
                    cm.layerid = layerid + str(index)
                    layers.append(cm)
                    self.contents[cm.id] = cm
                cm.children = gather_layers(elem, cm, layerid + str(index) + "L")
            return layers
        
        gather_layers(caps, None, "L")

        # exceptions
        self.exceptions = [f.text for f
                           in self._capabilities.findall(subcommon.nspath('Capability/Exception/Format',
                                                         WMS_NAMESPACE))]

    def items(self):
        '''supports dict-like items() access'''
        items = []
        for item in self.contents:
            items.append((item, self.contents[item]))
        return items

    def getServiceXML(self):
        xml = None
        if self._capabilities is not None:
            xml = etree.tostring(self._capabilities)
        return xml

    def getOperationByName(self, name):
        """Return a named content item."""
        for item in self.operations:
            if item.name == name:
                return item
        raise KeyError("No operation named %s" % name)

    def __build_getmap_request(self, layers=None, styles=None, srs=None, bbox=None,
               format=None, size=None, time=None, dimensions={},
               elevation=None, transparent=False,
               bgcolor=None, exceptions=None, **kwargs):

        request = {'service': 'WMS', 'version': self.version, 'request': 'GetMap'}

        # check layers and styles
        assert len(layers) > 0
        request['layers'] = ','.join(layers)
        if styles:
            assert len(styles) == len(layers)
            request['styles'] = ','.join(styles)
        else:
            request['styles'] = ''

        # size
        request['width'] = str(size[0])
        request['height'] = str(size[1])

        # remap srs to crs for the actual request
        if srs.upper() == 'EPSG:0':
            # if it's esri's unknown spatial ref code, bail
            raise Exception('Undefined spatial reference (%s).' % srs)

        sref = Crs(srs)
        if sref.axisorder == 'yx':
            # remap the given bbox
            bbox = (bbox[1], bbox[0], bbox[3], bbox[2])

        # remapping the srs to crs for the request
        request['crs'] = str(srs)
        request['bbox'] = ','.join([repr(x) for x in bbox])
        request['format'] = str(format)
        request['transparent'] = str(transparent).upper()
        request['bgcolor'] = '0x' + bgcolor[1:7]
        request['exceptions'] = str(exceptions)

        if time is not None:
            request['time'] = str(time)

        if elevation is not None:
            request['elevation'] = str(elevation)

        # any other specified dimension, prefixed with "dim_"
        for k, v in six.iteritems(dimensions):
            request['dim_' + k] = str(v)

        if kwargs:
            for kw in kwargs:
                request[kw]=kwargs[kw]
        return request

    def getmap(self, layers=None,
               styles=None,
               srs=None,
               bbox=None,
               format=None,
               size=None,
               time=None,
               elevation=None,
               dimensions={},
               transparent=False,
               bgcolor='#FFFFFF',
               exceptions='XML',
               method='Get',
               timeout=None,
               **kwargs
               ):
        """Request and return an image from the WMS as a file-like object.

        Parameters
        ----------
        layers : list
            List of content layer names.
        styles : list
            Optional list of named styles, must be the same length as the
            layers list.
        srs : string
            A spatial reference system identifier.
            Note: this is an invalid query parameter key for 1.3.0 but is being
                  retained for standardization with 1.1.1.
            Note: throws exception if the spatial ref is ESRI's "no reference"
                  code (EPSG:0)
        bbox : tuple
            (left, bottom, right, top) in srs units (note, this order does not
                change depending on axis order of the crs).

            CRS:84: (long, lat)
            EPSG:4326: (lat, long)
        format : string
            Output image format such as 'image/jpeg'.
        size : tuple
            (width, height) in pixels.

        time : string or list or range
            Optional. Time value of the specified layer as ISO-8601 (per value)
        elevation : string or list or range
            Optional. Elevation value of the specified layer.
        dimensions: dict (dimension : string or list or range)
            Optional. Any other Dimension option, as specified in the GetCapabilities

        transparent : bool
            Optional. Transparent background if True.
        bgcolor : string
            Optional. Image background color.
        method : string
            Optional. HTTP DCP method name: Get or Post.
        **kwargs : extra arguments
            anything else e.g. vendor specific parameters

        Example
        -------
            wms = WebMapService('http://webservices.nationalatlas.gov/wms/1million',\
                                    version='1.3.0')
            img = wms.getmap(layers=['airports1m'],\
                                 styles=['default'],\
                                 srs='EPSG:4326',\
                                 bbox=(-176.646, 17.7016, -64.8017, 71.2854),\
                                 size=(300, 300),\
                                 format='image/jpeg',\
                                 transparent=True)
            out = open('example.jpg.jpg', 'wb')
            out.write(img.read())
            out.close()

        """

        try:
            base_url = next((m.get('url') for m in
                            self.getOperationByName('GetMap').methods if
                            m.get('type').lower() == method.lower()))
        except StopIteration:
            base_url = self.url

        request = self.__build_getmap_request(
            layers=layers,
            styles=styles,
            srs=srs,
            bbox=bbox,
            dimensions=dimensions,
            elevation=elevation,
            format=format,
            size=size,
            time=time,
            transparent=transparent,
            bgcolor=bgcolor,
            exceptions=exceptions,
            **kwargs)

        data = urlencode(request)
        data = data.replace("+", "%20")

        self.request = bind_url(base_url) + data

        u = openURL(base_url,
                    data,
                    method,
                    username=self.username,
                    password=self.password,
                    timeout=timeout or self.timeout)

        # need to handle casing in the header keys
        headers = {}
        for k, v in six.iteritems(u.info()):
            headers[k.lower()] = v

        # handle the potential charset def
        if headers['content-type'].split(';')[0] in ['application/vnd.ogc.se_xml', 'text/xml']:
            se_xml = u.read()
            se_tree = etree.fromstring(se_xml)
            err_message = six.text_type(se_tree.find(subcommon.nspath('ServiceException', OGC_NAMESPACE)).text).strip() + self.request
            raise ServiceException(err_message)
        return u, self.request
    
    def Subgetmap_url(self, layers=None,
               styles=None,
               srs=None,
               bbox=None,
               format=None,
               size=None,
               time=None,
               elevation=None,
               dimensions={},
               transparent=False,
               bgcolor='#FFFFFF',
               exceptions='XML',
               method='Get',
               timeout=None,
               **kwargs
               ):

        try:
            base_url = next((m.get('url') for m in
                            self.getOperationByName('GetMap').methods if
                            m.get('type').lower() == method.lower()))
        except StopIteration:
            base_url = self.url

        request = self.__build_getmap_request(
            layers=layers,
            styles=styles,
            srs=srs,
            bbox=bbox,
            dimensions=dimensions,
            elevation=elevation,
            format=format,
            size=size,
            time=time,
            transparent=transparent,
            bgcolor=bgcolor,
            exceptions=exceptions,
            **kwargs)

        data = urlencode(request)
        data = data.replace("+", "%20")

        request = bind_url(base_url) + data

        u = openURL(base_url,
                    data,
                    method,
                    username=self.username,
                    password=self.password,
                    timeout=timeout or self.timeout)

        # need to handle casing in the header keys
        headers = {}
        for k, v in six.iteritems(u.info()):
            headers[k.lower()] = v

        # handle the potential charset def
        if headers['content-type'].split(';')[0] in ['application/vnd.ogc.se_xml', 'text/xml']:
            se_xml = u.read()
            se_tree = etree.fromstring(se_xml)
            err_message = six.text_type(se_tree.find(subcommon.nspath('ServiceException', OGC_NAMESPACE)).text).strip()
            raise ServiceException(err_message)
        return request

    def getfeatureinfo(self, layers=None,
                       styles=None,
                       srs=None,
                       bbox=None,
                       format=None,
                       size=None,
                       time=None,
                       elevation=None,
                       dimensions={},
                       transparent=False,
                       bgcolor='#FFFFFF',
                       exceptions='XML',
                       query_layers=None,
                       xy=None,
                       info_format=None,
                       feature_count=20,
                       method='Get',
                       timeout=None,
                       **kwargs
                       ):
        try:
            base_url = next((m.get('url') for m in self.getOperationByName('GetFeatureInfo').methods if m.get('type').lower() == method.lower()))
        except StopIteration:
            base_url = self.url

        # GetMap-Request
        request = self.__build_getmap_request(
            layers=layers,
            styles=styles,
            srs=srs,
            bbox=bbox,
            dimensions=dimensions,
            elevation=elevation,
            format=format,
            size=size,
            time=time,
            transparent=transparent,
            bgcolor=bgcolor,
            exceptions=exceptions,
            kwargs=kwargs)

        # extend to GetFeatureInfo-Request
        request['request'] = 'GetFeatureInfo'

        if not query_layers:
            __str_query_layers = ','.join(layers)
        else:
            __str_query_layers = ','.join(query_layers)

        request['query_layers'] = __str_query_layers
        request['i'] = str(xy[0])
        request['j'] = str(xy[1])
        request['info_format'] = info_format
        request['feature_count'] = str(feature_count)

        data = urlencode(request)
 
        self.request = bind_url(base_url) + data

        u = openURL(base_url, data, method, username=self.username, password=self.password, timeout=timeout or self.timeout)

        # check for service exceptions, and return
        if u.info()['Content-Type'] == 'XML':
            se_xml = u.read()
            se_tree = etree.fromstring(se_xml)
            err_message = six.text_type(se_tree.find('ServiceException').text).strip()
            raise ServiceException(err_message)
        return u

class SubServiceIdentification(ServiceIdentification):
    def __init__(self, infoset, version):
        self._root = infoset
        self.type = testXMLValue(self._root.find(subcommon.nspath('Name', WMS_NAMESPACE)))
        self.version = version
        self.title = testXMLValue(self._root.find(subcommon.nspath('Title', WMS_NAMESPACE)))
        self.abstract = testXMLValue(self._root.find(subcommon.nspath('Abstract', WMS_NAMESPACE)))
        self.keywords = extract_xml_list(self._root.findall(subcommon.nspath('KeywordList/Keyword', WMS_NAMESPACE)))
        self.accessconstraints = testXMLValue(self._root.find(subcommon.nspath('AccessConstraints', WMS_NAMESPACE)))
        self.fees = testXMLValue(self._root.find(subcommon.nspath('Fees', WMS_NAMESPACE)))


class SubServiceProvider(ServiceProvider):
    def __init__(self, infoset):
        self._root = infoset
        name = self._root.find(subcommon.nspath('ContactInformation/ContactPersonPrimary/ContactOrganization', WMS_NAMESPACE))
        if name is not None:
            self.name = name.text
        else:
            self.name = None
        self.url = self._root.find(subcommon.nspath('OnlineResource', WMS_NAMESPACE)).attrib.get('{http://www.w3.org/1999/xlink}href', '')
        
        # contact metadata
        contact = self._root.find(subcommon.nspath('ContactInformation', WMS_NAMESPACE))
        # sometimes there is a contact block that is empty, so make
        # sure there are children to parse
        if contact is not None and contact[:] != []:
            self.contact = SubContactMetadata(contact)
        else:
            self.contact = None
  

class SubContentMetadata(ContentMetadata):
    def __init__(self, elem, parent=None, children=None, index=0, parse_remote_metadata=False, timeout=30):
        if xmltag_split(elem.tag) != 'Layer':
            raise ValueError('%s should be a Layer' % (elem,))

        self.parent = parent
        if parent:
            self.index = "%s.%d" % (parent.index, index)
        else:
            self.index = str(index)

        self._children = children

        self.id = self.name = testXMLValue(elem.find(subcommon.nspath('Name', WMS_NAMESPACE)))

        # layer attributes
        self.queryable = int(bool(elem.attrib.get('queryable', 0)))
        self.cascaded = int(elem.attrib.get('cascaded', 0))
        self.opaque = int(elem.attrib.get('opaque', 0))
        self.noSubsets = int(elem.attrib.get('noSubsets', 0))
        self.fixedWidth = int(elem.attrib.get('fixedWidth', 0))
        self.fixedHeight = int(elem.attrib.get('fixedHeight', 0))

        # title is mandatory property
        self.title = None
        title = testXMLValue(elem.find(subcommon.nspath('Title', WMS_NAMESPACE)))
        if title is not None:
            self.title = title.strip()

        # layer abstract
        self.abstract = testXMLValue(elem.find(subcommon.nspath('Abstract', WMS_NAMESPACE)))
        
        # layer keywords
        self.keywords = [f.text for f in elem.findall(subcommon.nspath('KeywordList/Keyword', WMS_NAMESPACE))]
        
        # ScaleHint
        sh = elem.find(subcommon.nspath('ScaleHint', WMS_NAMESPACE))
        if sh is not None:
            self.scaleHint = {}
            if 'min' in sh.attrib:
                self.scaleHint['min'] = sh.attrib['min']
            if 'max' in sh.attrib:
                self.scaleHint['max'] = sh.attrib['max']
        # If not exist, try to inherit it from its parent
        elif self.parent:
            self.scaleHint = self.parent.scaleHint
        else:
            self.scaleHint = None
                
        # Attribution
        attribution = elem.find(subcommon.nspath('Attribution', WMS_NAMESPACE))
        if attribution is not None:
            self.attribution = dict()
            self.attribution['title'] = self.attribution['url'] = self.attribution['logo_size'] = self.attribution['logo_format'] = self.attribution['logo_url'] = None
            title = attribution.find(subcommon.nspath('Title', WMS_NAMESPACE))
            url = attribution.find(subcommon.nspath('OnlineResource', WMS_NAMESPACE))
            logo = attribution.find(subcommon.nspath('LogoURL', WMS_NAMESPACE))
            if title is not None:
                self.attribution['title'] = title.text
            if url is not None:
                self.attribution['url'] = url.attrib['{http://www.w3.org/1999/xlink}href']
            if logo is not None:                
                self.attribution['logo_format'] = logo.find(subcommon.nspath('Format', WMS_NAMESPACE))
                self.attribution['logo_size'] = (int(logo.attrib['width']), int(logo.attrib['height']))
                self.attribution['logo_url'] = logo.find(subcommon.nspath('OnlineResource', WMS_NAMESPACE)).attrib['{http://www.w3.org/1999/xlink}href']
        # If not exist, try to inherit it from its parent
        elif self.parent:
            self.attribution = self.parent.attribution
        else:
            self.attribution = None
        
        # TODO: what is the preferred response to esri's handling of custom projections
        #       in the spatial ref definitions? see http://resources.arcgis.com/en/help/main/10.1/index.html#//00sq000000m1000000
        #       and an example (20150812) http://maps.ngdc.noaa.gov/arcgis/services/firedetects/MapServer/WMSServer?request=GetCapabilities&service=WMS

        # boundingBoxWGS84
        self.boundingBoxWGS84 = None
        b = elem.find(subcommon.nspath('EX_GeographicBoundingBox', WMS_NAMESPACE))
        if b is not None:
            minx = b.find(subcommon.nspath('westBoundLongitude', WMS_NAMESPACE))
            miny = b.find(subcommon.nspath('southBoundLatitude', WMS_NAMESPACE))
            maxx = b.find(subcommon.nspath('eastBoundLongitude', WMS_NAMESPACE))
            maxy = b.find(subcommon.nspath('northBoundLatitude', WMS_NAMESPACE))
            box = tuple(map(float, [minx.text if minx is not None else None,
                            miny.text if miny is not None else None,
                            maxx.text if maxx is not None else None,
                            maxy.text if maxy is not None else None]))
            self.boundingBoxWGS84 = tuple(box)
        # If not exist, try to inherit it from its parent    
        elif self.parent:
            self.boundingBoxWGS84 = self.parent.boundingBoxWGS84
        else:
            self.boundingBoxWGS84 = None

        # make a bbox list (of tuples)
        bbs = elem.findall(subcommon.nspath('BoundingBox', WMS_NAMESPACE))
        if not bbs:
            crs_list = []
            for bb in bbs:
                srs_str = bb.attrib.get('CRS', None)
                srs = Crs(srs_str)
                box = tuple(map(float, [bb.attrib['minx'], bb.attrib['miny'], bb.attrib['maxx'], bb.attrib['maxy']]))
                minx, miny, maxx, maxy = box[0], box[1], box[2], box[3]
                # handle the ordering so that it always returns (minx, miny, maxx, maxy)
                if srs and srs.axisorder == 'yx':
                    # reverse things
                    minx, miny, maxx, maxy = box[1], box[0], box[3], box[2]
                crs_list.append((minx, miny, maxx, maxy, srs_str))
            
        if len(crs_list) > 0:
            self.crs_list = crs_list
        elif self.parent:
            self.crs_list = self.parent.crs_list
        else:
            self.crs_list = None
                
        # and maintain the original boundingBox attribute (first in list) 
        # or the wgs84 bbox (to handle cases of incomplete parentage)
        self.boundingBox = crs_list[0] if crs_list else self.boundingBoxWGS84

        # TODO: get this from the bbox attributes instead (deal with parents)
        # SRS options
        self.crsOptions = []
        # Copy any parent SRS options (they are inheritable properties)
        if self.parent:
            self.crsOptions = list(self.parent.crsOptions)
        # Look for SRS option attached to this layer
        if elem.find(subcommon.nspath('CRS', WMS_NAMESPACE)) is not None:
            # some servers found in the wild use a single SRS
            # tag containing a whitespace separated list of SRIDs
            # instead of several SRS tags. hence the inner loop
            for srslist in map(lambda x: x.text, elem.findall(subcommon.nspath('CRS', WMS_NAMESPACE))):
                if srslist:
                    for srs in srslist.split():
                        self.crsOptions.append(srs)
        # Get rid of duplicate entries
        self.crsOptions = list(set(self.crsOptions))
        # Set self.crsOptions to None if the layer (and parents) had no SRS options
        if len(self.crsOptions) == 0:
            # raise ValueError('%s no SRS available!?' % (elem,))
            # Comment by D Lowe.
            # Do not raise ValueError as it is possible that a layer is purely a parent layer and does not have SRS specified. Instead set crsOptions to None
            # Comment by Jachym:
            # Do not set it to None, but to [], which will make the code
            # work further. Fixed by anthonybaxter
            self.crsOptions = None

        # Styles
        self.styles = {}

        # Copy any parent styles (they are inheritable properties)
        if self.parent:
            self.styles = self.parent.styles.copy()

        # Get the styles for this layer (items with the same name are replaced)
        for s in elem.findall(subcommon.nspath('Style', WMS_NAMESPACE)):
            name = s.find(subcommon.nspath('Name', WMS_NAMESPACE))
            title = s.find(subcommon.nspath('Title', WMS_NAMESPACE))
#             if name is None or title is None:
            if name is None:
                continue
            if title is None:
                style = {'title':None}
            else:
                style = {'title': title.text}
            # legend url
            legend = s.find(subcommon.nspath('LegendURL/OnlineResource', WMS_NAMESPACE))
            if legend is not None:
                style['legend'] = legend.attrib['{http://www.w3.org/1999/xlink}href']

            lgd = s.find(subcommon.nspath('LegendURL', WMS_NAMESPACE))
            if lgd is not None:
                if 'width' in lgd.attrib.keys():
                    style['legend_width'] = lgd.attrib.get('width')
                if 'height' in lgd.attrib.keys():
                    style['legend_height'] = lgd.attrib.get('height')

                lgd_format = lgd.find(subcommon.nspath('Format', WMS_NAMESPACE))
                if lgd_format is not None:
                    style['legend_format'] = lgd_format.text.strip()
                    
            self.styles[name.text] = style        

        # extents replaced by dimensions of name
        # comment by Soren Scott
        # <Dimension name="elevation" units="meters" default="500" multipleValues="1"
        #    nearestValue="0" current="true" unitSymbol="m">500, 490, 480</Dimension>
        # it can be repeated with the same name so ? this assumes a single one to match 1.1.1
        self.timepositions = None
        self.defaulttimeposition = None
        time_dimension = None
        for dim in elem.findall(subcommon.nspath('Dimension', WMS_NAMESPACE)):
            if dim.attrib.get('name') is not None:
                time_dimension = dim
                
        if time_dimension is not None:
            self.timepositions = time_dimension.text.split(',') if time_dimension.text else None
            self.defaulttimeposition = time_dimension.attrib.get('default', None)

        # Elevations - available vertical levels
        self.elevations = None
        elev_dimension = None
        for dim in elem.findall(subcommon.nspath('Dimension', WMS_NAMESPACE)):
            if dim.attrib.get('elevation') is not None:
                elev_dimension = dim
        if elev_dimension is not None:
            self.elevations = [e.strip() for e in elev_dimension.text.split(',')] if elev_dimension.text else None

        # and now capture the dimensions as more generic things (and custom things)
        self.dimensions = {}
        for dim in elem.findall(subcommon.nspath('Dimension', WMS_NAMESPACE)):
            dim_name = dim.attrib.get('name')
            dim_data = {}
            for k, v in six.iteritems(dim.attrib):
                if k != 'name':
                    dim_data[k] = v
            # single values and ranges are not differentiated here
            dim_data['values'] = dim.text.strip().split(',') if dim.text.strip() else None
            self.dimensions[dim_name] = dim_data

        # MetadataURLs
        self.metadataUrls = []
        for m in elem.findall(subcommon.nspath('MetadataURL', WMS_NAMESPACE)):
            metadataUrl = {
                'type': testXMLValue(m.attrib['type'], attrib=True),
                'format': testXMLValue(m.find(subcommon.nspath('Format', WMS_NAMESPACE))),
                'url': testXMLValue(m.find(subcommon.nspath('OnlineResource', WMS_NAMESPACE)).attrib['{http://www.w3.org/1999/xlink}href'], attrib=True)
            }

            if metadataUrl['url'] is not None and parse_remote_metadata:  # download URL
                try:
                    content = openURL(metadataUrl['url'], timeout=timeout)
                    doc = etree.parse(content)
                    if metadataUrl['type'] is not None:
                        if metadataUrl['type'] == 'FGDC':
                            metadataUrl['metadata'] = Metadata(doc)
                        if metadataUrl['type'] == 'TC211':
                            metadataUrl['metadata'] = MD_Metadata(doc)
                except Exception:
                    metadataUrl['metadata'] = None

            self.metadataUrls.append(metadataUrl)
            
        def str_strip(str_text):
            if str_text:
                return str_text.strip()
            else:
                return str_text
            
        # DataURLs
        self.dataUrls = []
        for m in elem.findall(subcommon.nspath('DataURL', WMS_NAMESPACE)):
            dataUrl = {
                'format': str_strip(m.find(subcommon.nspath('Format', WMS_NAMESPACE)).text),
                'url': m.find(subcommon.nspath('OnlineResource', WMS_NAMESPACE)).attrib['{http://www.w3.org/1999/xlink}href']
            }
            self.dataUrls.append(dataUrl)

        # FeatureListURLs
        self.featureListUrls = []
        for m in elem.findall(subcommon.nspath('FeatureListURL', WMS_NAMESPACE)):
            featureUrl = {
                'format': m.find(subcommon.nspath('Format', WMS_NAMESPACE)).text.strip(),
                'url': m.find(subcommon.nspath('OnlineResource', WMS_NAMESPACE)).attrib['{http://www.w3.org/1999/xlink}href']
            }
            self.featureListUrls.append(featureUrl)

        self.layers = []
        for child in elem.findall(subcommon.nspath('Layer', WMS_NAMESPACE)):
            self.layers.append(SubContentMetadata(child, self))
            
    def getlegendgraphicrequest(self):
        request = None

        for styleName in self.styles:
            style = self.styles[styleName]
            if style['legend']:
                request = style['legend']
                break

        return request

    @property
    def children(self):
        return self._children

    @children.setter
    def children(self, value):
        if self._children is None:
            self._children = value
        else:
            self._children.extend(value)

    def __str__(self):
        return 'Layer Name: %s Title: %s' % (self.name, self.title)

class SubOperationMetadata(OperationMetadata):
    def __init__(self, elem):
        """."""
        self.name = xmltag_split(elem.tag)
        # formatOptions
        self.formatOptions = [f.text for f in elem.findall(subcommon.nspath('Format', WMS_NAMESPACE))]
        self.methods = []
        for verb in elem.findall(subcommon.nspath('DCPType/HTTP/*', WMS_NAMESPACE)):
            url = verb.find(subcommon.nspath('OnlineResource',ns=WMS_NAMESPACE))
            xlink_ns = url.nsmap['xlink']
            url = url.attrib[subcommon.nspath('href',ns=xlink_ns)]
            self.methods.append({'type': xmltag_split(verb.tag), 'url': url})


class SubContactMetadata(ContactMetadata):
    def __init__(self, elem):
        self.name = self.organization = None            
        name = elem.find(subcommon.nspath('ContactPersonPrimary/ContactPerson', WMS_NAMESPACE))
        if name is not None:
            self.name = name.text
            
        organization = elem.find(subcommon.nspath('ContactPersonPrimary/ContactOrganization', WMS_NAMESPACE))
        if organization is not None:
            self.organization = organization.text            
        
        self.position = self.email = self.voiceTelephone = self.facsimileTelephone = None            
        email = elem.find(subcommon.nspath('ContactElectronicMailAddress', WMS_NAMESPACE))
        if email is not None:
            self.email = email.text
            
        voiceTelephone = elem.find(subcommon.nspath('ContactVoiceTelephone', WMS_NAMESPACE))
        if voiceTelephone is not None:
            self.voiceTelephone = voiceTelephone.text
            
        facsimileTelephone = elem.find(subcommon.nspath('ContactFacsimileTelephone', WMS_NAMESPACE))
        if facsimileTelephone is not None:
            self.facsimileTelephone = facsimileTelephone.text
            
        position = elem.find(subcommon.nspath('ContactPosition', WMS_NAMESPACE))
        if position is not None:
            self.position = position.text
            
        self.addressType = self.address = self.city = self.region = self.postcode = self.country = None
        address = elem.find(subcommon.nspath('ContactAddress', WMS_NAMESPACE))
        if address is not None:
            addressType = address.find(subcommon.nspath('AddressType', WMS_NAMESPACE))
            if addressType is not None:
                self.addressType = addressType.text
                
            street = address.find(subcommon.nspath('Address', WMS_NAMESPACE))
            if street is not None:
                self.address = street.text

            city = address.find(subcommon.nspath('City', WMS_NAMESPACE))
            if city is not None:
                self.city = city.text

            region = address.find(subcommon.nspath('StateOrProvince', WMS_NAMESPACE))
            if region is not None:
                self.region = region.text

            postcode = address.find(subcommon.nspath('PostCode', WMS_NAMESPACE))
            if postcode is not None:
                self.postcode = postcode.text

            country = address.find(subcommon.nspath('Country', WMS_NAMESPACE))
            if country is not None:
                self.country = country.text


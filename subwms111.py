from wms111 import ContentMetadata, WebMapService_1_1_1, ServiceIdentification, ServiceProvider, OperationMetadata, ContactMetadata
from owslib.util import (openURL, testXMLValue, extract_xml_list, 
                         xmltag_split, OrderedDict, ServiceException,
                         bind_url)
try:                    # Python 3
    from urllib.parse import urlencode
except ImportError:     # Python 2
    from urllib import urlencode
from owslib.etree import etree
import six
from owslib.crs import Crs
import warnings
from owslib.map.subcommon import SubWMSCapabilitiesReader
from owslib.namespaces import Namespaces
import owslib.map.subcommon as subcommon


n = Namespaces()
WMS_NAMESPACE = n.get_namespace("wms")
OGC_NAMESPACE = n.get_namespace('ogc')
  #default namespace for subcommon.nspath is OWS common
OWS_NAMESPACE = 'http://www.opengis.net/ows/1.1'

class SubWebMapService_1_1_1(WebMapService_1_1_1):
    def __init__(self, url, version=None, xml=None,
                 username=None,
                 password=None,
                 parse_remote_metadata=False,
                 headers=None,
                 timeout=30):
        """Initialize."""
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
    
    def _buildMetadata(self, parse_remote_metadata=False):
        """Set up capabilities metadata objects."""

        self.updateSequence = self._capabilities.attrib.get('updateSequence')
        
        global WMS_NAMESPACE
        if not subcommon.ns_existence(self._capabilities):
            WMS_NAMESPACE = None
            
        # serviceIdentification metadata
        serviceelem = self._capabilities.find(subcommon.nspath('Service',
                                              ns=WMS_NAMESPACE))
        self.identification = ServiceIdentification(serviceelem, self.version)

        # serviceProvider metadata
        self.provider = ServiceProvider(serviceelem)

        # serviceOperations metadata
        self.operations = []
        for elem in self._capabilities.find(subcommon.nspath('Capability/Request',
                                              ns=WMS_NAMESPACE))[:]:
            self.operations.append(OperationMetadata(elem))

        # serviceContents metadata: our assumption is that services use a
        # top-level layer as a metadata organizer, nothing more.
        self.contents = OrderedDict()
        caps = self._capabilities.find(subcommon.nspath('Capability',
                                              ns=WMS_NAMESPACE))

        # recursively gather content metadata for all layer elements.
        # To the WebMapService.contents store only metadata of named layers.
        def gather_layers(parent_elem, parent_metadata, layerid):
            layers = []
            for index, elem in enumerate(parent_elem.findall(subcommon.nspath('Layer',ns=WMS_NAMESPACE))):
                cm = SubContentMetadata(elem, parent=parent_metadata,
                                     index=index + 1,
                                     parse_remote_metadata=parse_remote_metadata)
                if cm.id:
                    if cm.id in self.contents:
                        warnings.warn('Content metadata for layer "%s" already exists. Using child layer' % cm.id)
                    cm.layerid = layerid + str(index)
                    layers.append(cm)
                    self.contents[cm.id] = cm
                cm.children = gather_layers(elem, cm, layerid+str(index)+"L")
            return layers
        
        gather_layers(caps, None, "L")

        # exceptions
        self.exceptions = [f.text for f
                           in self._capabilities.findall(subcommon.nspath('Capability/Exception/Format',ns=WMS_NAMESPACE))]
    
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
    
    def __build_getmap_request(self, layers=None, styles=None, srs=None, bbox=None,
               format=None, size=None, time=None, transparent=False,
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

        request['srs'] = str(srs)
        request['bbox'] = ','.join([repr(x) for x in bbox])
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
    
    def getmap(self, layers=None, styles=None, srs=None, bbox=None,
               format=None, size=None, time=None, transparent=False,
               bgcolor='#FFFFFF',
               exceptions='application/vnd.ogc.se_xml',
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
        bbox : tuple
            (left, bottom, right, top) in srs units.
        format : string
            Output image format such as 'image/jpeg'.
        size : tuple
            (width, height) in pixels.
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
            wms = WebMapService('http://giswebservices.massgis.state.ma.us/geoserver/wms', version='1.1.1')
            img = wms.getmap(layers=['massgis:GISDATA.SHORELINES_ARC'],\
                                 styles=[''],\
                                 srs='EPSG:4326',\
                                 bbox=(-70.8, 42, -70, 42.8),\
                                 size=(300, 300),\
                                 format='image/jpeg',\
                                 transparent=True)
            out = open('example.jpg', 'wb')
            bytes_written = out.write(img.read())
            out.close()

        """
        try:
            base_url = next((m.get('url') for m in self.getOperationByName('GetMap').methods if m.get('type').lower() == method.lower()))
        except StopIteration:
            base_url = self.url
        request = {'version': self.version, 'request': 'GetMap'}

        request = self.__build_getmap_request(
            layers=layers,
            styles=styles,
            srs=srs,
            bbox=bbox,
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

        self.request = bind_url(base_url) + data

        u = openURL(base_url, data, method, username=self.username, password=self.password, timeout=timeout or self.timeout)

        # check for service exceptions, and return
        if u.info()['Content-Type'].split(';')[0] in ['application/vnd.ogc.se_xml']:
            se_xml = u.read()
            se_tree = etree.fromstring(se_xml)
            err_message = six.text_type(se_tree.find('ServiceException').text).strip() + self.request
            raise ServiceException(err_message)
        return [u, self.request]

    def Subgetmap_url(self, layers=None, styles=None, srs=None, bbox=None,
               format=None, size=None, time=None, transparent=False,
               bgcolor='#FFFFFF',
               exceptions='application/vnd.ogc.se_xml',
               method='Get',
               timeout=None,
               **kwargs
               ):        
        try:
            base_url = next((m.get('url') for m in self.getOperationByName('GetMap').methods if m.get('type').lower() == method.lower()))
        except StopIteration:
            base_url = self.url
        request = {'version': self.version, 'request': 'GetMap'}

        request = self.__build_getmap_request(
            layers=layers,
            styles=styles,
            srs=srs,
            bbox=bbox,
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
        
        # GetMap validity
        u = openURL(base_url, data, method, username=self.username, password=self.password, timeout=timeout or self.timeout)
        # check for service exceptions, and return
        if u.info()['Content-Type'].split(';')[0] in ['application/vnd.ogc.se_xml']:
            se_xml = u.read()
            se_tree = etree.fromstring(se_xml)
            err_message = six.text_type(se_tree.find('ServiceException').text).strip()
            raise ServiceException(err_message)
        return request


class SubContentMetadata(ContentMetadata):    
    def getlegendgraphicrequest(self):
        request = None
        
        for styleName in self.styles:
            style = self.styles[styleName]
            if style['legend']:
                request = style['legend']
                break
            
        return request
    
    def __init__(self, elem, parent=None, children=None, index=0, parse_remote_metadata=False, timeout=30):
        if xmltag_split(elem.tag) != 'Layer':
            raise ValueError('%s should be a Layer' % (elem,))

        self.parent = parent
        if parent:
            self.index = "%s.%d" % (parent.index, index)
        else:
            self.index = str(index)

        self._children = children

        self.id = self.name = testXMLValue(elem.find(subcommon.nspath('Name',
                                              ns=WMS_NAMESPACE)))

        # layer attributes
        self.queryable = int(elem.attrib.get('queryable', 0))
        self.cascaded = int(elem.attrib.get('cascaded', 0))
        self.opaque = int(elem.attrib.get('opaque', 0))
        self.noSubsets = int(elem.attrib.get('noSubsets', 0))
        self.fixedWidth = int(elem.attrib.get('fixedWidth', 0))
        self.fixedHeight = int(elem.attrib.get('fixedHeight', 0))

        # title is mandatory property
        self.title = None
        title = testXMLValue(elem.find(subcommon.nspath('Title',
                                              ns=WMS_NAMESPACE)))
        if title is not None:
            self.title = title.strip()

        self.abstract = testXMLValue(elem.find(subcommon.nspath('Abstract',
                                              ns=WMS_NAMESPACE)))
        # keywords
        self.keywords = [f.text for f in elem.findall(subcommon.nspath('KeywordList/Keyword',ns=WMS_NAMESPACE))]
        
        # ScaleHint
        sh = elem.find(subcommon.nspath('ScaleHint',ns=WMS_NAMESPACE))
        self.scaleHint = None
        if sh is not None:
            if 'min' in sh.attrib and 'max' in sh.attrib:
                self.scaleHint = {'min': sh.attrib['min'], 'max': sh.attrib['max']} 

        attribution = elem.find(subcommon.nspath('Attribution',ns=WMS_NAMESPACE))
        if attribution is not None:
            self.attribution = dict()
            title = attribution.find(subcommon.nspath('Title',ns=WMS_NAMESPACE))
            url = attribution.find(subcommon.nspath('OnlineResource',ns=WMS_NAMESPACE))
            logo = attribution.find(subcommon.nspath('LogoURL',ns=WMS_NAMESPACE))
            if title is not None: 
                self.attribution['title'] = title.text
            if url is not None:
                self.attribution['url'] = url.attrib['{http://www.w3.org/1999/xlink}href']
            if logo is not None: 
                self.attribution['logo_size'] = (int(logo.attrib['width']), int(logo.attrib['height']))
                self.attribution['logo_url'] = logo.find(subcommon.nspath('OnlineResource',ns=WMS_NAMESPACE)).attrib['{http://www.w3.org/1999/xlink}href']

        b = elem.find(subcommon.nspath('LatLonBoundingBox',ns=WMS_NAMESPACE))
        if b is not None:
            self.boundingBoxWGS84 = (
                float(b.attrib['minx']),
                float(b.attrib['miny']),
                float(b.attrib['maxx']),
                float(b.attrib['maxy']),
            )
        elif self.parent:
            self.boundingBoxWGS84 = self.parent.boundingBoxWGS84
        else:
            self.boundingBoxWGS84 = None

        # bboxes
        bbs = elem.findall(subcommon.nspath('BoundingBox', WMS_NAMESPACE))
        if not bbs:
            crs_list = []
            for bb in bbs:
                srs_str = bb.attrib.get('SRS', None)                
                srs = Crs(srs_str)    
                box = tuple(map(float, [bb.attrib['minx'], bb.attrib['miny'], bb.attrib['maxx'], bb.attrib['maxy']]))
                minx, miny, maxx, maxy = box[0], box[1], box[2], box[3]    
                # handle the ordering so that it always
                # returns (minx, miny, maxx, maxy)
                if srs and srs.axisorder == 'yx':
                    # reverse things
                    minx, miny, maxx, maxy = box[1], box[0], box[3], box[2]    
                crs_list.append(( minx, miny, maxx, maxy,srs_str))
            self.crs_list = crs_list
            
        elif self.parent:
            self.crs_list = self.parent.crs_list
        else:
            self.crs_list = None
            
        # and maintain the original boundingBox attribute (first in list)
        # or the wgs84 bbox (to handle cases of incomplete parentage)
        self.boundingBox = self.crs_list[0] if self.crs_list else self.boundingBoxWGS84

        # SRS options
        self.crsOptions = []
        # Copy any parent SRS options (they are inheritable properties)
        if self.parent:
            self.crsOptions = list(self.parent.crsOptions)
        # Look for SRS option attached to this layer
        if elem.find(subcommon.nspath('SRS',ns=WMS_NAMESPACE)) is not None:
            ## some servers found in the wild use a single SRS
            ## tag containing a whitespace separated list of SRIDs
            ## instead of several SRS tags. hence the inner loop
            for srslist in [x.text for x in elem.findall(subcommon.nspath('SRS',ns=WMS_NAMESPACE))]:
                if srslist:
                    for srs in srslist.split():
                        self.crsOptions.append(srs)
        #Get rid of duplicate entries
        self.crsOptions = list(set(self.crsOptions))
        #Set self.crsOptions to None if the layer (and parents) had no SRS options
        if len(self.crsOptions) == 0:
            #raise ValueError('%s no SRS available!?' % (elem,))
            #Comment by D Lowe.
            #Do not raise ValueError as it is possible that a layer is purely a parent layer and does not have SRS specified. Instead set crsOptions to None
            # Comment by Jachym:
            # Do not set it to None, but to [], which will make the code
            # work further. Fixed by anthonybaxter
            self.crsOptions = None

        #Styles
        self.styles = {}
        #Copy any parent styles (they are inheritable properties)
        if self.parent:
            self.styles = self.parent.styles.copy()
        #Get the styles for this layer (items with the same name are replaced)
        for s in elem.findall(subcommon.nspath('Style',ns=WMS_NAMESPACE)):
            name = s.find(subcommon.nspath('Name',ns=WMS_NAMESPACE))
            title = s.find(subcommon.nspath('Title',ns=WMS_NAMESPACE))
            if not name:
                continue
            if title is None:
                style = {'title':None}
            else:
                style = {'title': title.text}
#             if name is None or title is None:
#                 raise ValueError('%s missing name or title' % (s,))
#             style = { 'title' : title.text }
            # legend url
            legend = s.find(subcommon.nspath('LegendURL/OnlineResource',ns=WMS_NAMESPACE))
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


        # timepositions - times for which data is available.
        self.timepositions = None
        self.defaulttimeposition = None
        for extent in elem.findall(subcommon.nspath('Extent',ns=WMS_NAMESPACE)):
            if extent.attrib.get("name").lower() == 'time':
                if extent.text:
                    self.timepositions=extent.text.split(',')
                    self.defaulttimeposition = extent.attrib.get("default")
                    break

        # Elevations - available vertical levels
        self.elevations=None
        for extent in elem.findall(subcommon.nspath('Extent',ns=WMS_NAMESPACE)):
            if extent.attrib.get("name").lower() == 'elevation':
                if extent.text:
                    self.elevations = extent.text.split(',')
                    break
            
        # MetadataURLs
        self.metadataUrls = []
        for m in elem.findall(subcommon.nspath('MetadataURL',ns = WMS_NAMESPACE)):
            metadataUrl = {
#                 'type': testXMLValue(m.attrib['type'], attrib=True),
#                 'format': testXMLValue(m.find(subcommon.nspath('Format',ns=WMS_NAMESPACE))),
#                 'url': testXMLValue(m.find(subcommon.nspath('OnlineResource',ns=WMS_NAMESPACE)).attrib['{http://www.w3.org/1999/xlink}href'], attrib=True)
                'type': testXMLValue(subcommon.attrib_extraction(m,'type',None), attrib=True),
                'format': testXMLValue(m.find(subcommon.nspath('Format',ns=WMS_NAMESPACE))),
                'url': testXMLValue(subcommon.attrib_extraction(m.find(subcommon.nspath('OnlineResource',ns=WMS_NAMESPACE)),'href','xlink}'), attrib=True)
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
        
        # FeatureListURLs
        self.featureListUrls = []
        for m in elem.findall(subcommon.nspath('FeatureListURL', ns=WMS_NAMESPACE)):
            featureListUrl = {
                'format': str_strip(m.find(subcommon.nspath('Format',ns=WMS_NAMESPACE)).text),
                'url': subcommon.attrib_extraction(m.find(subcommon.nspath('OnlineResource',ns=WMS_NAMESPACE)),'href','xlink')
            }
            self.featureListUrls.append(featureListUrl)
        
        # DataURLs
        self.dataUrls = []
        for m in elem.findall(subcommon.nspath('DataURL',ns=WMS_NAMESPACE)):
            dataUrl = {
                'format': str_strip(m.find(subcommon.nspath('Format',ns=WMS_NAMESPACE)).text),
                'url': subcommon.attrib_extraction(m.find(subcommon.nspath('OnlineResource',ns=WMS_NAMESPACE)),'href','xlink')
            }
            self.dataUrls.append(dataUrl)

        self.layers = []
        for child in elem.findall(subcommon.nspath('Layer',ns=WMS_NAMESPACE)):
            self.layers.append(SubContentMetadata(child, self))
            
class ServiceIdentification(object):
    ''' Implements IServiceIdentificationMetadata '''

    def __init__(self, infoset, version):
        self._root=infoset
        self.type = testXMLValue(self._root.find(subcommon.nspath('Name',ns=WMS_NAMESPACE)))
        self.version = version
        self.title = testXMLValue(self._root.find(subcommon.nspath('Title',ns=WMS_NAMESPACE)))
        self.abstract = testXMLValue(self._root.find(subcommon.nspath('Abstract',ns=WMS_NAMESPACE)))
        self.keywords = extract_xml_list(self._root.findall(subcommon.nspath('KeywordList/Keyword',ns=WMS_NAMESPACE)))
        self.accessconstraints = testXMLValue(self._root.find(subcommon.nspath('AccessConstraints',ns=WMS_NAMESPACE)))
        self.fees = testXMLValue(self._root.find(subcommon.nspath('Fees',ns=WMS_NAMESPACE)))
        
class ServiceProvider(object):
    ''' Implements IServiceProviderMetatdata '''
    def __init__(self, infoset):
        self._root=infoset
        name=self._root.find(subcommon.nspath('ContactInformation/ContactPersonPrimary/ContactOrganization',ns=WMS_NAMESPACE))
        if name is not None:
            self.name=name.text
        else:
            self.name=None
        self.url=subcommon.attrib_extraction(self._root.find(subcommon.nspath('OnlineResource',ns=WMS_NAMESPACE)),'href', 'xlink')
        #contact metadata
        contact = self._root.find(subcommon.nspath('ContactInformation',ns=WMS_NAMESPACE))
        ## sometimes there is a contact block that is empty, so make
        ## sure there are children to parse
        if contact is not None and contact[:] != []:
            self.contact = ContactMetadata(contact)
        else:
            self.contact = None

    def getContentByName(self, name):
        """Return a named content item."""
        for item in self.contents:
            if item.name == name:
                return item
        raise KeyError("No content named %s" % name)

    def getOperationByName(self, name):
        """Return a named content item."""
        for item in self.operations:
            if item.name == name:
                return item
        raise KeyError("No operation named %s" % name)

class ContentMetadata:
    """
    Abstraction for WMS layer metadata.

    Implements IContentMetadata.
    """
    def __init__(self, elem, parent=None, children=None, index=0, parse_remote_metadata=False, timeout=30):
        if xmltag_split(elem.tag) != 'Layer':
            raise ValueError('%s should be a Layer' % (elem,))

        self.parent = parent
        if parent:
            self.index = "%s.%d" % (parent.index, index)
        else:
            self.index = str(index)

        self._children = children

        self.id = self.name = testXMLValue(elem.find(subcommon.nspath('Name',ns=WMS_NAMESPACE)))

        # layer attributes
        self.queryable = int(elem.attrib.get('queryable', 0))
        self.cascaded = int(elem.attrib.get('cascaded', 0))
        self.opaque = int(elem.attrib.get('opaque', 0))
        self.noSubsets = int(elem.attrib.get('noSubsets', 0))
        self.fixedWidth = int(elem.attrib.get('fixedWidth', 0))
        self.fixedHeight = int(elem.attrib.get('fixedHeight', 0))

        # title is mandatory property
        self.title = None
        title = testXMLValue(elem.find(subcommon.nspath('Title',ns=WMS_NAMESPACE)))
        if title is not None:
            self.title = title.strip()

        self.abstract = testXMLValue(elem.find(subcommon.nspath('Abstract',ns=WMS_NAMESPACE)))
        
        # keywords
        self.keywords = [f.text for f in elem.findall(subcommon.nspath('KeywordList/Keyword',ns=WMS_NAMESPACE))]

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
        
        # LatLonBoundingBox
        b = elem.find(subcommon.nspath('LatLonBoundingBox',ns=WMS_NAMESPACE))
        if b is not None:
            self.boundingBoxWGS84 = (
                float(b.attrib['minx']),
                float(b.attrib['miny']),
                float(b.attrib['maxx']),
                float(b.attrib['maxy']),
            )
        # If not exist, try to inherit it from its parent
        elif self.parent:
            self.boundingBoxWGS84 = self.parent.boundingBoxWGS84
        else:
            self.boundingBoxWGS84 = None
            
        # BoundingBox
        b = elem.find(subcommon.nspath('BoundingBox',ns=WMS_NAMESPACE))
        self.boundingBox = None
        if b is not None:
            try:  # sometimes the SRS attribute is (wrongly) not provided
                srs = b.attrib['SRS']
            except KeyError:
                srs = None
            self.boundingBox = (
                float(b.attrib['minx']),
                float(b.attrib['miny']),
                float(b.attrib['maxx']),
                float(b.attrib['maxy']),
                srs,
            )
        elif self.parent:
            if hasattr(self.parent, 'boundingBox'):
                self.boundingBox = self.parent.boundingBox


        # SRS options
        self.crsOptions = []

        # Copy any parent SRS options (they are inheritable properties)
        if self.parent:
            self.crsOptions = list(self.parent.crsOptions)

        # Look for SRS option attached to this layer
        if elem.find(subcommon.nspath('SRS',ns=WMS_NAMESPACE)) is not None:
            ## some servers found in the wild use a single SRS
            ## tag containing a whitespace separated list of SRIDs
            ## instead of several SRS tags. hence the inner loop
            for srslist in [x.text for x in elem.findall(subcommon.nspath('SRS',ns=WMS_NAMESPACE))]:
                if srslist:
                    for srs in srslist.split():
                        self.crsOptions.append(srs)

        #Get rid of duplicate entries
        self.crsOptions = list(set(self.crsOptions))

        #Set self.crsOptions to None if the layer (and parents) had no SRS options
        if len(self.crsOptions) == 0:
            #raise ValueError('%s no SRS available!?' % (elem,))
            #Comment by D Lowe.
            #Do not raise ValueError as it is possible that a layer is purely a parent layer and does not have SRS specified. Instead set crsOptions to None
            # Comment by Jachym:
            # Do not set it to None, but to [], which will make the code
            # work further. Fixed by anthonybaxter
            self.crsOptions = []

        #Styles
        self.styles = {}

        #Copy any parent styles (they are inheritable properties)
        if self.parent:
            self.styles = self.parent.styles.copy()

        #Get the styles for this layer (items with the same name are replaced)
        for s in elem.findall(subcommon.nspath('Style',ns=WMS_NAMESPACE)):
            name = s.find(subcommon.nspath('Name',ns=WMS_NAMESPACE))
            title = s.find(subcommon.nspath('Title',ns=WMS_NAMESPACE))
            if name is None or title is None:
                raise ValueError('%s missing name or title' % (s,))
            style = { 'title' : title.text }
            # legend url
            legend = s.find(subcommon.nspath('LegendURL/OnlineResource',ns=WMS_NAMESPACE))
            if legend is not None:
                style['legend'] = legend.attrib['{http://www.w3.org/1999/xlink}href']
            self.styles[name.text] = style

        
        # timepositions - times for which data is available.
        self.timepositions=None
        self.defaulttimeposition = None
        for extent in elem.findall(subcommon.nspath('Extent',ns=WMS_NAMESPACE)):
            if extent.attrib.get("name").lower() =='time':
                if extent.text:
                    self.timepositions=extent.text.split(',')
                    self.defaulttimeposition = extent.attrib.get("default")
                    break

        # Elevations - available vertical levels
        self.elevations=None
        for extent in elem.findall(subcommon.nspath('Extent',ns=WMS_NAMESPACE)):
            if extent.attrib.get("name").lower() == 'elevation':
                if extent.text:
                    self.elevations = extent.text.split(',')
                    break

        # MetadataURLs
        self.metadataUrls = []
        for m in elem.findall(subcommon.nspath('MetadataURL',ns=WMS_NAMESPACE)):
            metadataUrl = {
                'type': testXMLValue(m.attrib['type'], attrib=True),
                'format': testXMLValue(m.find(subcommon.nspath('Format',ns=WMS_NAMESPACE))),
                'url': testXMLValue(m.find(subcommon.nspath('OnlineResource',ns=WMS_NAMESPACE)).attrib['{http://www.w3.org/1999/xlink}href'], attrib=True)
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

        # DataURLs
        self.dataUrls = []
        for m in elem.findall(subcommon.nspath('DataURL',ns=WMS_NAMESPACE)):
            dataUrl = {
                'format': m.find(subcommon.nspath('Format',ns=WMS_NAMESPACE)).text.strip(),
                'url': m.find(subcommon.nspath('OnlineResource',ns=WMS_NAMESPACE)).attrib['{http://www.w3.org/1999/xlink}href']
            }
            self.dataUrls.append(dataUrl)

        self.layers = []
        for child in elem.findall(subcommon.nspath('Layer',ns=WMS_NAMESPACE)):
            self.layers.append(ContentMetadata(child, self))

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


class OperationMetadata:
    """Abstraction for WMS OperationMetadata.

    Implements IOperationMetadata.
    """
    def __init__(self, elem):
        """."""
        self.name = xmltag_split(elem.tag)
        # formatOptions
        self.formatOptions = [f.text for f in elem.findall(subcommon.nspath('Format',ns=WMS_NAMESPACE))]
        self.methods = []
        for verb in elem.findall(subcommon.nspath('DCPType/HTTP/*',ns=WMS_NAMESPACE)):
            url = verb.find(subcommon.nspath('OnlineResource',ns=WMS_NAMESPACE))
            xlink_ns = url.nsmap['xlink']
            url = url.attrib[subcommon.nspath('href',ns=xlink_ns)]
            self.methods.append({'type' : xmltag_split(verb.tag), 'url': url})


class ContactMetadata:
    """Abstraction for contact details advertised in GetCapabilities.
    """
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
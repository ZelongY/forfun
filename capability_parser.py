#! /usr/bin/env python
# coding: UTF-8

# Libraries provided by revised owslib, whose functions are modified based on our test instances 
import owslib.map.subcommon as subcommon

from owslib.namespaces import Namespaces
n = Namespaces()
WMS_NAMESPACE = n.get_namespace("wms")
OGC_NAMESPACE = n.get_namespace('ogc')
OWS_NAMESPACE = 'http://www.opengis.net/ows/1.1'

# Local libraries
from mysql_connector import DB
from logging_logger import fileLogger
from logging_logger import consoleLogger

'''
Files organization in the folder:
* Each WMS instance occupies a individual sub-folder in the root directory, whose name is the urlid of the WMS
* All layer map thumbnails and their legends provided by a WMS are stored in the same directory
* The name for a layer map thumbnail is generated using the reName function with the layer name as 
    the 'name' parameter and 'png' as the 'suffix' parameter
* The name for a layer map legend is also generated using the reName function, but a string "_legend" 
    is appended to the file name before its suffix 
'''
homeDirectory = "/Users/wenwenlab/Documents/WMS_Thumbnails"

'''
Please refer the imghdr to initialize the thumbnail_format values. Because the imghdr library is adopted to check whether the response content 
is a valid picture.
'''
thumbnail_format = ['png', 'jpg']

'''
Default length of the thumbnail width
'''
thumbnail_width = 600
        
'''
Replace all symbols in the name with underlines
* name: a string name needs to be processed, and the name can contain its suffix
# suffix: a suffix specified for the new name. It will replace the old suffix if a suffix exists in the name. 
          Otherwise, it will be directly appended to the name if no suffix exist in the name 
'''
def reName(name, suffix = None):
    if not name:
        raise ValueError("the 'name' parameter cannot be empty string or None")
    
    import re
    
    suffix_index = name.rfind(".")
    if suffix_index != -1:
        if not suffix:
            suffix = name[suffix_index + 1: len(name)]
        name = name[0: suffix_index]
    
    new_name = re.sub(r'[^a-z0-9_]', r'_', name, flags=re.IGNORECASE)
    
    if suffix:
        new_name = new_name + "." + suffix
        
    return new_name


'''
Construct the absolute path of a thumbnail based on their organization rules
* urlid: a id assigned for a WMS instance, which is generated randomly and maintained in the MySQL database
* layer_name: the name of a layer of interest, which shall be contained in the WMS with the specified urlid
'''
def thumbnail_path(urlid, layer_name, suffix = None):
    if not urlid or not layer_name:
        raise ValueError("Both parameters cannot be empty string or None")
    
    import os
    
    thumbnail_name = reName(layer_name, suffix)
    return os.path.join(homeDirectory, str(urlid) + "/" + thumbnail_name)

'''
Save pictures into the local folder whose structure is described in the beginning
* If the file exists or the new file is a valid picture in PNG format, save it and return 1. 
* If not: return 0.
'''
def save2local(content, urlid, layer_name, suffix = None):
    import os 
    file_path = thumbnail_path(urlid, layer_name, suffix)
    # If the picture exists, return
    if os.path.exists(file_path):
        return
    
    else:
        import imghdr
        response_format = imghdr.what(None, h = content.read())
        if response_format in thumbnail_format:    
            parent_dir = os.path.dirname(filePath)
            if not os.path.exists(parent_dir):
                os.makedirs(parent_dir)
                
            file_writer = open(filePath,'wb')
            bytes_written = file_writer.write(content.read())
            file_writer.close()
            
        else:
            raise ValueError("""The format '{}' of the response content is not supported by current configuration specified using  
            thumbnail_format: {}""".format(response_format, thumbnail_format))
    

'''
Return the version of the WMS specification implemented by the URL
* url: a valid URL for a WMS GetCapabilities request
********
If the version attribute extracted successfully, the version value will be returned.
If not, a value error exception will be thrown out with the error information
'''
def owsVersion(url):
    import requests     
    '''
    Get the version information from the service capability document.
    '''
    try:
        response = requests.get(url)
    except:
        raise ValueError("Cannot open the URL: ".format(url))
    
    status_code = response.status_code
    if status_code >= 400:
        raise ValueError("Server Error: " + url)
    
    content = response._content
    if subcommon.WMSExceptionDetection(content):
        raise ValueError("Service Exception contained in the response from the URL: " + url)
     
    try:
        from lxml import etree
        root = etree.fromstring(content)
        version = root.get('version')
        return version
    except:
        raise ValueError("No version attribute found in the response from the URL: " + url)
    
'''
Keep the ratio between width and height
* width: pre-configured width in the Capabilities document
* height: pre-configured height in the Capabilities document
* bbox: a coordinate list containing four values in the format [minx, miny, maxx, maxy]
'''
def mapSize(width, height, bbox):
    if width == 0:
        if height == 0:
            if not bbox or len(bbox) != 4 or bbox[3] - bbox[1] == 0 or bbox[2] - bbox[0] == 0:
                raise ValueError("Invalid bbox parameter is provided")
            
            width = thumbnail_width
            height = int((bbox[3] - bbox[1]) * 600/(bbox[2] - bbox[0]))
        else:
            width = int((bbox[2] - bbox[0]) * height/(bbox[3] - bbox[1]))    
    else:
        if height == 0:
            height = int((bbox[3] - bbox[1]) * 600/(bbox[2] - bbox[0]))
            
    return (width, height)

'''
Select a provided style randomly
'''
def style_selection(styles):
    if not styles:
        for style_name in styles:
            return style_name
    else:
        return None

'''
Layer legend size decision
'''
def legend_size(styles, style):
    if not styles:
        return (200, 200)
    
    else:
        for style_name in styles:
            if style_name == style:
                legend_width = styles[style_name]['legend_width'] if styles[style_name]['legend_width'] is not None else 200
                legend_height = styles[style_name]['legend_height'] if styles[style_name]['legend_height'] is not None else 200
                return (legend_width, legend_height)
        return (200,200)

'''
Layer legend format
'''
def legend_format(styles, style):
    if not styles:
        return None
    
    else:
        for style_name in styles:
            if style_name == style:
                legendFormat = styles[style_name]['legend_format']
                return legendFormat
        return None

'''
Srs and boundingBox decision
* If any boundingBox element exists with bbox and srs attribute, return its bbox and srs. If not:
    * Check whether epsg:4326 or crs:84 is supported.
        * If yes, return its boundingBoxWGS84 as bbox. epsg:4326 or crs:84 as srs.
        * If not, throw ValueError
'''
def srs_bbox_selection(layer):
    for bbox in layer.crs_list:
        try:
            srs = bbox[4]
            boundingbox = [bbox[0],bbox[1],bbox[2],bbox[3]]
            return [srs, boundingbox]
        except:
            continue
        
    try:
        srs_options = ['epsg:4326', 'crs:84']
        srs = None
        for srs_item in layer.crsOptions:
            if srs_item in srs_options:
                srs = srs_item
        
        boundingbox = layer.boundingBoxWGS84
        return [srs, boundingbox]
    except:
        raise ValueError('Exception in fetching reasonable BBox and SRS')
    
'''
Map thumbnail format decision. The supported formats are specified in the format_list together with image/png.
* The image/png is the first option.
'''
def wms_format_selection(formatOptions):
    format_list = ['image/jpeg', 'image/gif', 'image/tiff']
    formatOption2 = None
    
    for formatOption in formatOptions:
        if formatOption.lower() == 'image/png':
            return formatOption
        elif formatOption.lower() in format_list:
            formatOption2 = formatOption
    
    if formatOption2:
        return formatOption2
    else:
        raise ValueError("No desired format is found GetMap or GetLegendGraphic request")

'''
Reformat items in a list as a string  with semicolons among each of them
'''
def list2str_with_semicolons(list_variable):
    if len(list_variable) == 0:
        return None
    else:
        str_object = ""
        for item in list_variable:
            str_object += item + "; "
        str_object = str_object[0: len(str_object) - 1]
        return str_object
    
'''
Update WMS layer metadata
'''
def update_layer_metadata(layer,urlid, srs, bbox, style): 
    import re
    layerid = str(urlid) + layer.layerid
    if layer.title:
        layerTitle = re.sub('"', "'", layer.title, flags=re.IGNORECASE)
    else:
        layerTitle = layer.title
    layerName = layer.name
    new_layerName = reName(layerName)
    if layer.abstract:
        layerAbstract = re.sub('"', "'", layer.abstract, flags=re.IGNORECASE)
    else:
        layerAbstract = layer.abstract
    print layerAbstract
    layerKeywords = list2str_with_semicolons(layer.keywords)
    
    sql = u"insert into owsLayerMD (layerid, urlid, layerTitle, layerName, new_layerName, layerAbstract, layerKeywords, layerSRS, minx, miny, maxx, maxy, layerStyle) values \
    ('{}', {}, \"{}\", '{}', '{}', \"{}\", '{}', '{}', {}, {}, {}, {}, '{}')".format(layerid, urlid, layerTitle, layerName, new_layerName, layerAbstract, layerKeywords, srs, bbox[0], bbox[1],bbox[2],bbox[3],style).encode('utf8')
    
    import MySQLdb
    db = DB()
    try:
        print(sql)
        db.setBySql(sql)
    except MySQLdb.IntegrityError as e:
        if e[0] == 1062:
            sql = u"update owsLayerMD set layerTitle=\"{}\", urlid={}, layerName='{}', new_layerName='{}', layerAbstract=\"{}\", layerKeywords='{}', layerSRS='{}', minx={}, miny={}, \
            maxx={}, maxy={}, layerStyle='{}' where layerid='{}'".format(layerTitle, urlid, layerName, new_layerName, layerAbstract, layerKeywords, srs, bbox[0], bbox[1], bbox[2], bbox[3], style, layerid).encode('utf8')
            # print(sql)
            db.setBySql(sql)
            
'''
Update service metadata
'''
def update_service_metadata(wms, url):
    elements_dict = dict()
    elements_dict['url'] = url
    
    identification_elements = ['title', 'abstract', 'keywords', 'fees', 'accessconstraints', 'version']
    identification_attributes = {key:value for key, value in wms.identification.__dict__.items() if not key.startswith('_') and not callable(key)}
    for elem in identification_elements:
        elements_dict[elem] = identification_attributes.get(elem)
    
    contact_elements = ['email']
    contact_attributes = {key:value for key, value in wms.provider.contact.__dict__.items() if not key.startswith('_') and not callable(key)}
    for elem in contact_elements:
        elements_dict[elem] = contact_attributes.get(elem)

    db = DB()
    sql_select = "select id from qose_wms_metadata where url='{}'".format(url)
    records = db.getBySql(sql_select)
    if len(records) == 0:
        placeholders = ', '.join(['%s'] * len(elements_dict))
        columns = ', '.join(elements_dict.keys())
        sql_insert = "INSERT INTO qose_wms_metadata ( %s ) VALUES ( %s )" % (columns, placeholders)
        db.setBySql(sql_insert, elements_dict.values())
    else:
        id = records[0][0]
        sql_update = 'UPDATE qose_wms_metadata SET {} where id={}'.format(', '.join('{} = %s'.format(k) for k in elements_dict), id)
        db.setBySql(sql_update, elements_dict.values())
    
'''
Thumbnails cache and metadata update
* Insert or Update service metadata
* Insert or Update layers metadata
* Cache layer map thumbnail and legend
'''
def wms_getMap(url):
    from owslib.subwms import WebMapService
    logger = fileLogger("wms.log",'wms_getmap')
    
    # Get the specification version implemented by the current WMS
    version = owsVersion(url)
    if not version:
        logger.exception("No version found for {}".format(url))
        return
        
    # Get parsed elements from the Capability document of the current WMS
    try:        
        wms = WebMapService(url, version = version)
    except:
        logger.exception("OWSLib library failed in digesting the capability document from {}".format(url))
        return
    
    # Update or insert WMS service metadata
    update_service_metadata(wms, url)
    
    # 
#     getmap_format = None
#     getlegend_format = None    
#     for operation in wms.operations:
#         if operation.name.lower() == 'getmap':
#             try:
#                 getmap_format = wms_format_selection(operation.formatOptions)
#             except:
#                 logger.exception('Error in selecting thumbnail format for wms {} {}'.format(urlid, url))
#                 continue
#         elif operation.name.lower() == 'getlegendgraphic':
#             try:
#                 getlegend_format = wms_format_selection(operation.formatOptions)
#             except:
#                 continue         
#     if getmap_format is None:
#         logger.exception('No GetMap operation is detected for WMS {} {}',format(urlid, url))
#         return None    
#             
#     contents = wms.contents
#     for layerName in contents:
#         print(layerName)
#         layer = wms[layerName]
#         
#         # SRS and boundingBox decision
#         try:
#             [srs, boundingBox] = srs_bbox_selection(layer)
#         except:
#             logger.exception('Error in downloading map for layer {} in WMS {} {}'.format(layerName,urlid, url))
#             continue
#         
#         # Map size and style decision
#         mapsize = mapSize(layer.fixedWidth, layer.fixedHeight, boundingBox)        
#         style = style_selection(layer.styles)
#         
#         # Insert layer record into the owsLayerMD table
#         update_layer_metadata(layer, urlid, srs, boundingBox, style)
#         
#         # Download layer map thumbnail
#         try:    
#             img, map_request_url = wms.getmap(layers=[layerName], srs=srs, bbox=boundingBox, style=style, format=getmap_format, size=mapsize)
#         except:
#             logger.exception("Exception from owslib GetMap for the layer {} in WMS {} {}".format(layerName,urlid, url))
#             continue
#         map_existence = save2local(img, urlid, layerName, 'png')
#           
#         # Download layer legend thumbnail
#         legendName = layerName + "_legend"
#         legendsize = legend_size(layer.styles, style)
#         layer_legend_format = legend_format(layer.styles, style)
#         getlegend_format = layer_legend_format if layer_legend_format is not None else getlegend_format
#         try:
#             thumbnail, legend_request_url = wms.getlegendgraphic(layerName,size=legendsize,styles=style,format=getlegend_format)
#         except:
#             logger.exception("Exception from owslib GetLegendGraphic for the layer {} in WMS {} {}".format(layerName,urlid, url))
#             continue
#         legend_existence = save2local(thumbnail, urlid, legendName, 'png')
#           
#         sql = "update owsLayerMD set map_existence={}, legend_existence={} where layerid='{}'".format(map_existence, legend_existence, str(urlid) + layer.layerid)
#         db = DB()
#         db.setBySql(sql)              

wms_getMap("http://localhost/WMSServer.xml")

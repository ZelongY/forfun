# Set the thumbnailName as NULL when there is no related file in the corresponding path.
def thumbnail_clean():
    db = DB()
    parentDir = "/Library/WebServer/Documents/wms/"
    
    sql = "select layerid,urlid,thumbnailName from owsLayerMD where thumbnailName is not null"
    records = db.getBySql(sql)
    
    for record in records:
        layerid = record[0]
        urlid = record[1]
        thumbnailname = record[2]
        
        fileDir = parentDir + str(urlid) + "/" + thumbnailname + ".png"
        if os.path.isfile(fileDir):
            print(layerid)
            continue
        else:
            sql1 = "update owsLayerMD set thumbnailName=NULL where layerid='{}'".format(layerid)
            db.setBySql(sql1)
            print(sql1)
            
# Set the thumbnailName as NULL when there is no related file in the corresponding path.            
def legend_clean():
    db = DB()
    parentDir = "/Library/WebServer/Documents/wms/"
    
    sql = "select layerid,urlid,legendName from owsLayerMD where legendName is not null"
    records = db.getBySql(sql)
    
    for record in records:
        layerid = record[0]
        urlid = record[1]
        legendName = record[2]
        
        fileDir = parentDir + str(urlid) + "/" + legendName + ".png"
        if os.path.isfile(fileDir):
            print(layerid)
            continue
        else:
            sql1 = "update owsLayerMD set legendName=NULL where layerid='{}'".format(layerid)
            db.setBySql(sql1)
            print(sql1)
            
# Detect what the non-PNG file is. There are 3 results returned:
# **empty: a file whose size is zero
# **exception: the WMS exception information found in the file
# **html: 

def exception_detection_wms(file_path):
    import mmap
    
    # If the file size is zero
    if os.stat(file_path).st_size == 0:
        return "empty"
    
    else:    
        with open(file_path, 'rb', 0) as file:
            s = mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ)            
            if re.search(br'(?i)exceptionreport', s):
                return "exception"
            elif re.search(br'(?i)<html>',s):
                return "html"
            else:
                return "other"

namespaces = {'ows':'http://www.opengis.net/ows#'}
def exception_tag_finding(root):
    print(root.findall('ExceptionText',namespaces))

# Extract exception from thumbnails or legends of WMS
def exception_content_wms(file_path):
    import xml.etree.ElementTree as ET
    exceps = ""
    
    tree = ET.parse(file_path)
    root = tree.getroot()    
    exception_tag_finding(root)
    # WMS version 1.1.x and later
    child_tag = ""
    for child in root:
        if re.search(br'(?i)serviceexception', child.tag):
            child_tag = child.tag
            break
        
    if child_tag != "":      
        for excep in root.iter(child_tag):
            exceps += excep.text
        
    # WMS version 1.0.0
    child_tag = ""
    for child in root.findall("ows:ExceptionText"):
        exceps += excep.text
          
    
    return exceps
        
def urlid_dataName_extraction(file_path):
    split_index = file_path.rfind("/")
    dataName = file_path[split_index + 1:len(file_path)-4]
    
    dataType = "thumbnailName"
    if "legend" in dataName:
        dataType = "legendName"
    
    parent_path = file_path[0:split_index]
    urlid = parent_path[parent_path.rfind("/")+1:len(parent_path)]
    
    return [urlid,dataName,dataType]
        
def error_detection_file(file_path):
    import logging
    import csv
    
    logs_file = "/Users/zelong/Documents/Cache/wms/program_logs.txt"
    logging.basicConfig(filename=logs_file,level=logging.ERROR)
         
    # If the file is not a valid PNG picture
    import imghdr
    if imghdr.what(file_path) != "png":
        # Record the content of exceptions of WMS services
        try:
            if exception_detection_wms(file_path):
                exception_content = exception_content_wms(file_path)
                if exception_content not in exception_types:
                    exception_types.append(exception_content)
                    wms_exception_types_writer.writerow([exception_content, file_path])
            else:
                other_exception_writer.writerow([file_path,"Not a valid PNG picture!"])
        except:
            logging.exception('Got exception on errors_detection')
            logging.info(file_path)
    else:
        keys = urlid_dataName_extraction(file_path)
        sql = "update owsLayerMD set dataerror=0 where urlid={} and {}='{}'".format(keys[0],keys[2],keys[1])
    
    wms_exception_file.close()
    other_exception_file.close()

def files_traverse(dir):
    files_path_collection = []

# Find out the invalid pictures in legends and thumbnails about WMS
def invalid_PNG_move(search_dir, target_dir):    
    # Traverse all services
    service_dirs = [dir for dir in os.listdir(home_dir) if os.path.isdir(os.path.join(home_dir,dir))]
    exception_types = []
    for service_dir in service_dirs:
        service_dir = os.path.join(home_dir,service_dir)
        os.remove(os.path.join(service_dir,'.DS_Store'))
        
        # Traverse all maps and legends in the current service
        pic_dirs = [dir for dir in os.listdir(service_dir) if os.path.isfile(os.path.join(service_dir,dir))]
        for pic_dir in pic_dirs:
            pic_dir = os.path.join(service_dir,pic_dir)
#             error_detection_file(pic_dir)
            keys = urlid_dataName_extraction(pic_dir)
            sql = "update owsLayerMD set {}='{}' where "
    
    wms_exception_file.close()
    other_exception_file.close()
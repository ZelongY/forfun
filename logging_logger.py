import logging

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s') 
    
    
def fileLogger(file_name, logger_name=None):
    # create logger with 'spam_application'
    logger = logging.getLogger(logger_name)
    # create file handler which logs even debug messages
    fh = logging.FileHandler(file_name)
    fh.setLevel(logging.ERROR)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    return logger
    
     
def consoleLogger(logger_name=None):
    # create console handler with a higher log level
    logger = logging.getLogger(logger_name)
    ch = logging.StreamHandler()
    ch.setLevel(logging.ERROR)
    # create formatter and add it to the handlers
    ch.setFormatter(formatter)
    # add the handlers to the logger
    logger.addHandler(ch)
    return logger
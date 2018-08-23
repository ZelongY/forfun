#! /usr/bin/env python
# coding: UTF-8

import MySQLdb
class DB: 
    conn=None;#这里的None相当于其它语言的NULL
      
    def __init__(self):#构造函数  
        self.conn=MySQLdb.connect(host="cici.lab.asu.edu",user="zelong",passwd="CoorHall5509",db="QoSE",port=3306)
        #数据库连接，localhost python不认，必须127.0.0.1
          
    def getBySqlWithNum(self,sql):  
        cursor=self.conn.cursor();#初始化游标
        result=cursor.fetchmany(cursor.execute(sql));
        rowCount = cursor.rowcount  
        self.conn.commit();#提交上面的sql语句到数据库执行  
        return (rowCount,result)
    
    def getBySql(self,sql):  
        cursor=self.conn.cursor();#初始化游标  
        result=cursor.fetchmany(cursor.execute(sql));
        self.conn.commit();#提交上面的sql语句到数据库执行  
        return result
      
    def getBySql_result_unique(self,sql):  
        cursor=self.conn.cursor();#初始化游标  
        result=cursor.fetchmany(cursor.execute(sql));  
        self.conn.commit();#提交上面的sql语句到数据库执行  
        return result[0][0];  
    
    def setBySql(self,sql):  
        cursor=self.conn.cursor();#初始化游标  
        cursor.execute(sql);  
        self.conn.commit();#提交上面的sql语句到数据库执行  
        
    def __del__(self):#析构函数  
        self.conn.close();#关闭数据库连接
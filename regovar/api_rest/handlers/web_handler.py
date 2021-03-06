#!env/python3
# coding: utf-8

# Developers additional dependencies
try:
    import ipdb
except ImportError:
    pass



import os
import json
import aiohttp
import aiohttp_jinja2
import datetime
import time
import requests

import aiohttp_security
from aiohttp_session import get_session
from aiohttp_security import remember, forget, authorized_userid, permits

import asyncio
import functools
import inspect
from aiohttp import web
from urllib.parse import parse_qsl

from config import *
from core.framework.common import *
from core.model import *
from core.core import core
from api_rest.rest import *
from api_rest.handlers import PipelineHandler
 





# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 
# Web regovar "light viewer" HANDLER
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 
class WebHandler:
    def __init__(self):
        pass

    
    #@user_role('Authenticated')
    @aiohttp_jinja2.template('web_home.html')
    def home(self, request):
        # Get message
        sql = "SELECT value FROM parameter WHERE key = 'message'"
        message = None
        for res in execute(sql):
            message = json.loads(res.value)

        return {
            "hostname" : HOST_P,
            "error": None,
            "path": [],
            "message": message
        }


    @aiohttp_jinja2.template('web_search.html')
    def search(self, request):
        searchQuery = request.match_info.get('query', None)
        if searchQuery is None :
            return { "hostname" : HOST_P, "error": "Nothing to search...", "path": ["search"] }
        try:
            result = core.search.search(searchQuery)
        except RegovarException as ex:
            return { "hostname" : HOST_P, "error": "Error occured while trying to search", "path": ["search"] }
        return {
            "hostname" : HOST_P,
            "error": None,
            "path": ["search"],
            "data": result
        }


    @aiohttp_jinja2.template('web_info.html')
    def info(self, request):
        asset_type = request.match_info.get('type', "unknow")
        asset_id = request.match_info.get('id', None)

        if asset_type == "file":
            file = File.from_id(asset_id)
            if file:
                pass

        pass


    @aiohttp_jinja2.template('web_viewer.html')
    def viewer(self, request):
        asset_id = request.match_info.get('id', -1)
        file = File.from_id(asset_id)
        reference = None
        viewer = "bin"
        result = None
        ftype = None
        
        if file:
            # if image
            if file.type in ["jpg", "jpeg", "png", "bmp", "tiff", "gif"]:
                viewer = "img"
                ftype = file.type
                result = check_local_path(file.path)
            # if bam
            elif file.type == "bam":
                viewer = "igv"
                ftype = "bam"
                result = [check_local_path(file.path)]
                reference = "hg19"
                # need to find the bai
                ifile = File.from_name(file.name + ".bai")
                if ifile:
                    result.append(check_local_path(ifile.path))
                else:
                    result.append(None)
            # if vcf
            elif file.type == "vcf":
                viewer = "igv"
                ftype = "vcf"
                result = check_local_path(file.path)
                reference = "hg19"
            else:
                # else try to parse txt file        
                viewer = "txt"
                ftype = file.type
                result = []
                try:
                    if file and file.status in ['uploaded', 'checked']:
                        with open(file.path, "r") as f:
                            for l in range(1000):
                                result.append(next(f))
                except Exception as ex:
                    if not isinstance(ex, StopIteration):
                        # cannot parse binary file => no preview available
                        viewer = "bin"

        return {
            "hostname" : HOST_P,
            "error": None,
            "path": ["view"],
            "viewer": viewer,
            "file_type": ftype,
            "reference": reference,
            "filename" : file.name if file else "-",
            "data": result
        }

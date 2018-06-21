 
#!env/python3
# coding: utf-8
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


from aiohttp import web
from urllib.parse import parse_qsl

from config import *
from core.framework.common import *
from core.model import *
from api_rest.rest import *








class EventHandler:
    

    @user_role('Authenticated')
    def list(self, request):
        """
            Get list of last 100 events
        """
        return rest_success(core.events.list())
    
    
    
    @user_role('Authenticated')
    async def search(self, request):
        """
            Get events list corresponding to provided filters
        """
        data = await request.json()
        try:
            data = json.loads(data) if isinstance(data, str) else data
            return rest_success(core.events.list(**data))
        except Exception as ex:
            return rest_error("Error occured when retriving list of requested events. {}".format(ex), ex=ex)
    
    
    
    @user_role('Authenticated')
    def get(self, request):
        """
            Get details about the event
        """
        event_id = request.match_info.get('event_id', -1)
        event = core.events.get(event_id)
        if not event:
            return rest_error("Unable to find the event (id={})".format(event_id))
        return rest_success(event)
        
        
    
    @user_role('Authenticated')
    async def new(self, request):
        """
            Create new event with provided data
        """
        data = await request.json()
        data = json.loads(data) if isinstance(data, str) else data
        message = check_string(data.pop("message")) if "message" in data else None
        details = check_string(data.pop("details")) if "detals" in data else None
        author_id = 1 # TODO: retrieve author_id from session
        date = check_date(data.pop("date")) if "date" in data else datetime.datetime.now()
        # Create the event
        try:
            event = core.events.new(author_id, date, message, details, data)
        except Exception as ex:
            return rest_error("Error occured when creating the new event. {}".format(ex), ex=ex)
        if event is None:
            return rest_error("Unable to create a new event with provided information.")
        return rest_success(event)
        
        
        
    @user_role('Authenticated')
    async def edit(self, request):
        """
            Edit event data
        """
        data = await request.json()
        data = json.loads(data) if isinstance(data, str) else data
        message = check_string(data.pop("message")) if "message" in data else None
        author_id = 1 # TODO: retrieve author_id from session
        date = check_date(data.pop("date")) if "date" in data else datetime.datetime.now()
        # Edit the event
        try:
            event = core.events.edit(author_id, event_id, date, message, data)
        except Exception as ex:
            return rest_error("Error occured when creating the new event. {}".format(ex), ex=ex)
        if event is None:
            return rest_error("Unable to create a new event with provided information.")
        return rest_success(event)
    
    
    
    @user_role('Authenticated')
    def delete(self, request):
        """
            Delete the event
        """
        event_id = request.match_info.get('event_id', -1)
        event = core.events.delete(event_id)
        if not event:
            return rest_error("Unable to delete the event (id={})".format(event_id))
        return rest_success(event)
    
    












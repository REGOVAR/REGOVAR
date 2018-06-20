#!env/python3
# coding: utf-8
import ipdb; 


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
from core.framework.tus import *
from core.model import *
from core.core import core
from api_rest.rest import *





# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 
# SAMPLE HANDLER
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 





class SampleHandler:

    # def build_tree(subject_id):
    #     from core.core import core
    #     currentLevelProjects = core.projects.get(None, {"subject_id": subject_id, "is_sandbox": False}, None, None, None, 1)
    #     result = []
    #     for p in currentLevelProjects:
    #         entry = p.to_json(["id", "name", "comment", "subject_id", "update_date", "create_date", "is_sandbox", "is_folder"])
    #         if p.is_folder:
    #             entry["children"] = ProjectHandler.build_tree(p.id)
    #         else:
    #             entry["subjects"] = [o.to_json(["id", "name", "comment", "update_date", "create_date"]) for o in p.subjects]
    #             entry["analyses"] = [o.to_json(["id", "name", "comment", "update_date", "create_date"]) for o in p.analyses]
    #             entry["analyses"] += [o.to_json(["id", "name", "comment", "update_date", "create_date"]) for o in p.jobs]
    #         result.append(entry)
    #     return result


    # def tree(self, request):
    #     """
    #         Get samples as tree of samples (with subject as folders)
    #         Samples that are not linked to a subject are grouped into an "empty" subject
    #     """
    #     ref_id = request.match_info.get('ref_id', None)
    #     if ref_id is None:
    #         return rest_error("A valid referencial id must be provided to get samples tree")
    #     # TODO : check that ref_id exists in database
    #     # TODO : pagination
    #     # TODO : search parameters
    #     result = []
    #     samples = [s for s in Session().query(Sample).filter_by(reference_id=ref_id).order_by(Sample.subject_id).all()]
    #     current_subject = {"id":-1}
    #     for s in samples:
    #         if s.subject_id != current_subject["id"]:
    #             if current_subject["id"] != -1: result.append(current_subject)
    #             current_subject = {"id": s.subject_id, "samples": []}
    #         s.init(1)
    #         current_subject["samples"].append(s.to_json())
    #     if current_subject["id"] != -1: 
    #         result.append(current_subject)
    #     return rest_success(result)

    
    



    @user_role('Authenticated')
    def list(self, request):
        """
            List all samples to init data of Client
        """
        ref_id = int(request.match_info.get('ref_id', 0)) if request else 0
        return rest_success(core.samples.list(ref_id))


    @user_role('Authenticated')
    def get(self, request):
        sid = request.match_info.get('sample_id', None)
        if sid is None:
            return rest_error("No valid sample id provided")
        sample = Sample.from_id(sid, 1)
        if sample is None:
            return rest_error("No sample found with id="+str(sid))
        return rest_success(sample.to_json())




    @user_role('Authenticated')
    async def import_from_file(self, request):

        params = request.rel_url.query # get_query_parameters(request.query_string, ["subject_id", "analysis_id"])
        file_id = request.match_info.get('file_id', None)
        ref_id = request.match_info.get('ref_id', None)
        
        
        try:
            samples = await core.samples.import_from_file(file_id, ref_id)
        except Exception as ex:
            return rest_error("Import error : Unable to import samples.", exception=ex)
        if samples:
            for s in samples:
                if "subject_id" in params and params["subject_id"]: 
                    s.subject_id = params["subject_id"]
                if "analysis_id" in params and params["analysis_id"]: 
                    AnalysisSample.new(s.id, params["analysis_id"])
            return rest_success(samples)
        
        return rest_error("unable to import samples from file.")
    
    
    
    
    @user_role('Authenticated')
    async def update(self, request):
        """
            Update a sample with provided data
        """
        sample_id = request.match_info.get('sample_id', -1)
        data = await request.json()
        try:
            sample = Sample.from_id(sample_id, 1)
            sample.load(data)
            sample.save()
        except Exception as ex:
            return rest_error("Unable to update sample data with provided informations. {}".format(str(ex)))
        return rest_success(sample.to_json())
    
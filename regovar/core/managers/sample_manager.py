#!env/python3
# coding: utf-8
import ipdb

import os
import json
import datetime
import uuid
import psycopg2
import hashlib
import asyncio
import ped_parser



from config import *
from core.framework.common import *
import core.model as Model





# =====================================================================================================================
# Samples MANAGER
# =====================================================================================================================


class SampleManager:
    def __init__(self):
        pass





    def get(self, fields=None, query=None, order=None, offset=None, limit=None, sublvl=0):
        """
            Generic method to get files metadata according to provided filtering options
        """
        if fields is None:
            fields = Sample.public_fields
        if query is None:
            query = {}
        if order is None:
            order = ['-create_date', "name"]
        if offset is None:
            offset = 0
        if limit is None:
            limit = offset + RANGE_MAX

        result = []
        for s in execute("SELECT sp.id, sp.name, sp.comment  FROM sample sp"):
            result.append({"id": s[0], "name": s[1], "comment": s[2], "analyses": []})
        return result
 
 
 
    async def import_from_file(file_id, analysis_id=None, reference_id=DEFAULT_REFERENCIAL_ID):
        from core.managers.imports.vcf_manager import VcfManager
        # Check ref_id
        if analysis_id:
            analysis = Model.Analysis.from_id(analysis_id)
            if analysis:
                reference_id=analysis.reference_id
        # Only import from VCF is supported for samples
        success = await VcfManager.import_data(file_id, reference_id=reference_id)
        
        # if analysis_id set, associate it to sample
        #if success and analysis_id:
            #samples = Model.session().query(Sample).filter_by(file_id=file_id).all()
            #for s in samples:
                #AnalysisSample.new(s.id, analysis_id)
                
        return success
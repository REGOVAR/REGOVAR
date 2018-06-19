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
from core.model import *










# =====================================================================================================================
# FILTER ENGINE
# =====================================================================================================================


class FilterEngine:
    op_map = {'AND': ' AND ', 'OR': ' OR ', '==': '=', '!=': '<>', '>': '>', '<': '<', '>=': '>=', '<=': '<=', '~': ' LIKE ', '!~': ' NOT LIKE ',
              # As a left join will be done on the chr+pos or chr+pos+ref+alt according to the type of the set operation (by site or by variant)
              # We just need to test if one of the "joined" field is set or not
              'IN': '{0}.chr is not null',
              'NOTIN': '{0}.chr is null'}
    sql_type_map = {'int': 'integer', 'string': 'text', 'float': 'real', 'enum': 'text', 'range': 'int8range', 'bool': 'boolean', 'sequence': 'text', 'list' : 'varchar(250)[]'}
    sql_agg_map = {'int': 'avg({0}) AS {0}', 
                   'string': 'string_agg(DISTINCT {0}, \', \') AS {0}', 
                   'float': 'avg({0}) AS {0}', 
                   'enum': 'string_agg(DISTINCT {0}, \', \') AS {0}', 
                   'range': 'int8range(min(lower({0})), max(upper({0}))) as {0}', 
                   'bool': 'bool_and({0}) AS {0}', 
                   'sequence': 'string_agg(DISTINCT {0}, \', \') AS {0}', 
                   'list' : 'array_agg(DISTINCT {0}, \', \') AS {0}'}


    def __init__(self):
        self.load_annotation_metadata()


    def load_annotation_metadata(self):
        """
            Init Annso Filtering engine.
            Init mapping collection for annotations databases and fields
        """
        self.fields_map = {}
        self.db_map = {}
        query = "SELECT d.uid AS duid, d.name AS dname, d.name_ui AS dname_ui, d.jointure, d.reference_id, d.type AS dtype, d.db_pk_field_uid, a.uid AS fuid, a.name AS fname, a.type, a.meta FROM annotation_field a LEFT JOIN annotation_database d ON a.database_uid=d.uid"
        result = execute(query)
        for row in result:
            if row.duid not in self.db_map:
                self.db_map[row.duid] = {"name": row.dname, "join": row.jointure, "fields": {}, "reference_id": row.reference_id, "type": row.dtype, "db_pk_field_uid" : row.db_pk_field_uid}
            self.db_map[row.duid]["fields"][row.fuid] = {"name": row.fname, "type": row.type}
            self.fields_map[row.fuid] = {"name": row.fname, "type": row.type, "meta": row.meta, "db_uid": row.duid, "db_name_ui": row.dname_ui, "db_name": row.dname, "db_type": row.dtype, "join": row.jointure}


    def create_working_table(self, analysis_id):
        """
            This method is called in another thread and will create the working table
            for the provided analysis_id
        """
        # As we are in another thread, we have to work in another sql session to avoid conflics
        analysis = Analysis.from_id(analysis_id)

        if analysis is None:
            err("Analysis cannot be null. Creation of working table for the analysis {} aborded".format(analysis_id))
            return

        try:
            analysis.reference = execute("SELECT table_suffix FROM reference WHERE id={}".format(analysis.reference_id)).first().table_suffix 
            analysis.db_suffix = "_" + analysis.reference
            progress = {"id": analysis.id, "status": analysis.status, "error_message": "", "log": [
                {"label": "Checking prequisites", "status": "done", "progress": 1}, # done in the request method : checking that sample data are ready
                {"label": "Creating Working Table", "status": "waiting", "progress": 0},
                {"label": "Getting variants", "status": "waiting", "progress": 0},
                {"label": "Getting samples fields", "status": "waiting", "progress": 0},
                {"label": "Computing predefined filters", "status": "waiting", "progress": 0},
                {"label": "Computing indexes", "status": "waiting", "progress": 0},
                {"label": "Getting annotations", "status": "waiting", "progress": 0},
                {"label": "Mergin annotations", "status": "waiting", "progress": 0},
                {"label": "Restoring saved filters", "status": "waiting", "progress": 0},
                {"label": "Restoring selections", "status": "waiting", "progress": 0},
                {"label": "Computing analysis statistics", "status": "waiting", "progress": 0},
            ]}


            # Refresh list of annotations db available
            self.load_annotation_metadata()

            execute("SET work_mem='1GB'")

            # create wt table
            self.create_wt_schema(analysis, progress)


            # insert variant
            self.insert_wt_variants(analysis, progress)

            # set sample's fields (GT, DP, ...)
            self.update_wt_samples_fields(analysis, progress)

            # compute stats and predefined filter (attributes, panels, trio, ...)
            self.update_wt_stats_prefilters(analysis, progress)

            # variant's indexes
            self.create_wt_variants_indexes(analysis, progress)

            # insert trx annotations
            self.insert_wt_trx(analysis, progress)

            # merge single trw into their annotation, and mergin trx annotation into root variant annotations
            self.update_wt_mergin_trx_variant(analysis, progress)

            # trx's indexes # TODO: DO WE NEED IT ?
            # self.create_wt_trx_indexes(analysis)
            
            # Recreate stored filter
            self.create_wt_stored_filters(analysis, progress)
            
            # Restore is_selected state for var/trx a
            self.update_wt_set_restore_selection(analysis, progress)
            
            # Compute sample's stats (done one time)
            self.update_wt_samples_stats(analysis, progress)

            execute("RESET work_mem")
            
            # Update count stat of the analysis
            progress["status"] = "ready"
            analysis.status = "ready"
            self.working_table_creation_update_status(analysis, progress)
            log(" > wt is ready")

        except Exception as ex:
            msg = "An error occurred during the ASYNCH creation of the working table of the analysis {}".format(analysis_id)
            err_file = err(msg.format(analysis_id), exception=ex)
            self.working_table_creation_update_status(analysis, progress, error="[{}] {}".format(err_file, msg))


    def working_table_creation_update_status(self, analysis, progress, step=None, status=None, percent=None, error=None):
        from core.core import core
        if step and status and percent:
            progress["log"][step]["status"] = status
            progress["log"][step]["progress"] = percent
        if error:
            progress["error_message"] += error
            progress["status"] = "error"
            analysis.status = "error"
        analysis.computing_progress = progress
        analysis.save()
        core.notify_all({'action':'wt_creation', 'data': progress})


    def create_wt_schema(self, analysis, progress):
        self.working_table_creation_update_status(analysis, progress, 1, "computing", 0.1)

        wt = "wt_{}".format(analysis.id)
        query = "DROP TABLE IF EXISTS {0} CASCADE; CREATE UNLOGGED TABLE {0} (\
            is_variant boolean DEFAULT False, \
            variant_id bigint, \
            vcf_line bigint, \
            is_selected boolean DEFAULT False, \
            regovar_score smallint, \
            bin integer, \
            chr integer, \
            pos bigint, \
            ref text, \
            alt text,\
            trx_pk_uid character varying(32), \
            trx_pk_value character varying(100), \
            is_transition boolean, \
            sample_tlist integer[], \
            sample_tcount integer, \
            sample_alist integer[], \
            sample_acount integer, \
            is_dom boolean DEFAULT False, \
            is_rec_hom boolean DEFAULT False, \
            is_rec_htzcomp boolean DEFAULT False, \
            is_denovo boolean DEFAULT False, \
            is_exonic boolean DEFAULT False, \
            is_aut boolean DEFAULT False, \
            is_xlk boolean DEFAULT False, \
            is_mit boolean DEFAULT False, "
        query += ", ".join(["s{}_gt integer".format(i) for i in analysis.samples_ids]) + ", "
        query += ", ".join(["s{}_dp integer".format(i) for i in analysis.samples_ids]) + ", "
        query += ", ".join(["s{}_dp_alt integer".format(i) for i in analysis.samples_ids]) + ", "
        query += ", ".join(["s{}_vaf real".format(i) for i in analysis.samples_ids]) + ", "
        query += ", ".join(["s{}_qual real".format(i) for i in analysis.samples_ids]) + ", "
        query += ", ".join(["s{}_filter JSON".format(i) for i in analysis.samples_ids]) + ", "
        query += ", ".join(["s{}_is_composite boolean".format(i) for i in analysis.samples_ids]) + ", "

        # Add annotation's columns
        for dbuid in analysis.settings["annotations_db"]:
            for fuid in self.db_map[dbuid]["fields"]:
                default = ""
                if "meta" in self.fields_map[fuid] and isinstance(self.fields_map[fuid]["meta"], dict) and "default" in self.fields_map[fuid]["meta"]:
                    default = " DEFAULT {}".format(self.fields_map[fuid]["meta"]["default"])
                query += "_{} {}{}, ".format(fuid, self.sql_type_map[self.fields_map[fuid]["type"]], default)
                
        # Add attribute's columns
        for attr in analysis.attributes:
            for value, col_id in attr["values_map"].items():
                query += "attr_{} boolean DEFAULT False, ".format(col_id)

        query = query[:-2] + ");"
        log(" > create wt schema")
        execute(query.format(wt))
        
        # We just update progress without calling notify_all as a notify will be send by the next step
        progress["log"][1]["status"] = "done"
        progress["log"][1]["progress"] = 1


    def insert_wt_variants(self, analysis, progress):
        self.working_table_creation_update_status(analysis, progress, 2, "computing", 0.1)
        wt = "wt_{}".format(analysis.id)

        # create temp table with id of variants
        query  = "DROP TABLE IF EXISTS {0}_var CASCADE; CREATE UNLOGGED TABLE {0}_var (id bigint, vcf_line bigint); "
        execute(query.format(wt))
        
        query = "INSERT INTO {0}_var (id, vcf_line) SELECT DISTINCT variant_id, vcf_line FROM sample_variant{1} WHERE sample_id IN ({2});"
        res = execute(query.format(wt, analysis.db_suffix, ",".join([str(sid) for sid in analysis.samples_ids])))
        
        # set total number of variant for the analysis
        log(" > {} variants found".format(res.rowcount))
        query = "UPDATE analysis SET total_variants={1} WHERE id={0};".format(analysis.id, res.rowcount)
        #query += "CREATE INDEX {0}_var_idx_id ON {0}_var USING btree (id);"
        execute(query.format(wt))
        self.working_table_creation_update_status(analysis, progress, 2, "computing", 0.33)

        # Insert variants and their annotations
        q_fields = "is_variant, variant_id, vcf_line, regovar_score, bin, chr, pos, ref, alt, is_transition, sample_tlist"
        q_select = "True, _vids.id, _vids.vcf_line, _var.regovar_score, _var.bin, _var.chr, _var.pos, _var.ref, _var.alt, _var.is_transition, _var.sample_list"
        q_from   = "{0}_var _vids LEFT JOIN variant{1} _var ON _vids.id=_var.id".format(wt, analysis.db_suffix)

        for dbuid in analysis.settings["annotations_db"]:
            if self.db_map[dbuid]["type"] == "variant":
                dbname = "_db_{}".format(dbuid)
                q_from += " LEFT JOIN {0}".format(self.db_map[dbuid]['join'].format(dbname, '_var'))
                q_fields += ", " + ", ".join(["_{}".format(fuid) for fuid in self.db_map[dbuid]["fields"]])
                q_select += ", " + ", ".join(["{}.{}".format(dbname, self.fields_map[fuid]["name"]) for fuid in self.db_map[dbuid]["fields"]])

        # execute query
        query = "INSERT INTO {0} ({1}) SELECT {2} FROM {3};".format(wt, q_fields, q_select, q_from)
        execute(query)
        self.working_table_creation_update_status(analysis, progress, 2, "computing", 0.66)
        
        # Create index on variant_id and vcf_line 
        log(" > create variants index")
        query = "CREATE INDEX {0}_idx_vid ON {0} USING btree (variant_id);".format(wt)
        query += "CREATE INDEX {0}_idx_vcfline ON {0} USING btree (vcf_line);".format(wt)
        query += "CREATE INDEX {0}_idx_chrpos ON {0} USING btree (chr, pos);".format(wt)
        execute(query)
        
        # We just update progress without calling notify_all as a notify will be send by the next step
        progress["log"][2]["status"] = "done"
        progress["log"][2]["progress"] = 1
        

    def update_wt_samples_fields(self, analysis, progress):
        self.working_table_creation_update_status(analysis, progress, 3, "computing", 0.01)
        log(" > import samples informations")
        wt = "wt_{}".format(analysis.id)
        step = 1/(2*len(analysis.samples_ids))
        prg = 0
        for sid in analysis.samples_ids:
            # Retrive informations chr-pos-ref-alt dependent
            execute("UPDATE {0} SET s{2}_gt=_sub.genotype, s{2}_dp=_sub.depth, s{2}_dp_alt=_sub.depth_alt, s{2}_vaf=CASE WHEN _sub.depth > 0 THEN _sub.depth_alt/_sub.depth::float ELSE 0 END, s{2}_is_composite=_sub.is_composite FROM (SELECT variant_id, genotype, depth, depth_alt, is_composite FROM sample_variant{1} WHERE sample_id={2}) AS _sub WHERE {0}.variant_id=_sub.variant_id".format(wt, analysis.db_suffix, sid))
            prg += step
            self.working_table_creation_update_status(analysis, progress, 3, "computing", prg)
            # Retrive informations vcf'line dependent (= chr-pos without trimming)
            execute("UPDATE {0} SET s{2}_qual=_sub.quality, s{2}_filter=_sub.filter FROM (SELECT vcf_line, chr, pos, quality, filter FROM sample_variant{1} WHERE sample_id={2}) AS _sub WHERE {0}.vcf_line=_sub.vcf_line".format(wt, analysis.db_suffix, sid))
            prg += step
            self.working_table_creation_update_status(analysis, progress, 3, "computing", prg)
            
        # We just update progress without calling notify_all as a notify will be send by the next step
        progress["log"][3]["status"] = "done"
        progress["log"][3]["progress"] = 1


    def update_wt_stats_prefilters(self, analysis, progress):
        self.working_table_creation_update_status(analysis, progress, 4, "computing", 0.01)
        wt = "wt_{}".format(analysis.id)
        step = 1/(2+ len(analysis.attributes)*len(analysis.samples_ids) + len(analysis.panels) + (2 if analysis.settings["trio"] else len(analysis.samples_ids)))
        prg = 0
        # Variant occurence stats
        query = "UPDATE {0} SET \
            sample_tcount=array_length(sample_tlist,1), \
            sample_alist=array_intersect(sample_tlist, array[{1}]), \
            sample_acount=array_length(array_intersect(sample_tlist, array[{1}]),1)"
        log(" > compute statistics")
        execute(query.format(wt, ",".join([str(i) for i in analysis.samples_ids])))
        prg += step
        self.working_table_creation_update_status(analysis, progress, 4, "computing", prg)
        
        # Attributes
        for attr in analysis.attributes:
            log(" > compute attribute {}".format(attr["name"]))
            for sid, attr_data in attr["samples_values"].items():
                execute("UPDATE {0} SET attr_{1}=True WHERE s{2}_gt IS NOT NULL".format(wt, attr_data["wt_col_id"], sid))
                prg += step
                self.working_table_creation_update_status(analysis, progress, 4, "computing", prg)

        # Panels
        for panel in analysis.panels:
            log(" > compute panel {} ({})".format(panel["name"], panel["version"]))
            sql = "UPDATE {0} SET panel_{1}=True WHERE {2}"
            sql_where = []
            where_pattern = "(chr={} AND pos <@ int8range({},{}))"
            # build test condition for the panel
            for region in panel["entries"]:
                sql_where.append(where_pattern.format(region["chr"], region["start"], region["end"]))
            execute(sql.format(wt, panel["version_id"].replace("-", "_"), ' OR '.join(sql_where)))
            prg += step
            self.working_table_creation_update_status(analysis, progress, 4, "computing", prg)
        
        # Predefinied quickfilters
        if analysis.settings["trio"]:
            self.update_wt_compute_prefilter_trio(analysis, analysis.samples_ids, analysis.settings["trio"], progress, prg, step)
        else:
            for sid in analysis.samples_ids:
                # TODO: retrieve sex of sample if subject associated, otherwise, do it with default "Female"
                self.update_wt_compute_prefilter_single(analysis, sid, "F", progress, prg, step)
                
                
        # Compute is_exonic filter thanks to refgene
        sql = "UPDATE {1} AS w SET is_exonic=True FROM refgene_exon{0} AS r WHERE w.chr=r.chr AND w.pos <@ r.exonrange"
        execute(sql.format(analysis.db_suffix, wt))
        
        
        # We just update progress without calling notify_all as a notify will be send by the next step
        progress["log"][4]["status"] = "done"
        progress["log"][4]["progress"] = 1
        
        
    def create_wt_variants_indexes(self, analysis, progress):
        self.working_table_creation_update_status(analysis, progress, 5, "computing", 0.01)
        wt = "wt_{}".format(analysis.id)

        # Common indexes for variants
        query = "".join(["CREATE INDEX {0}_idx_s{1}_gt ON {0} USING btree (s{1}_gt);".format(wt, i) for i in analysis.samples_ids])
        query += "".join(["CREATE INDEX {0}_idx_s{1}_dp ON {0} USING btree (s{1}_dp);".format(wt, i) for i in analysis.samples_ids])
        query += "".join(["CREATE INDEX {0}_idx_s{1}_dpa ON {0} USING btree (s{1}_dp_alt);".format(wt, i) for i in analysis.samples_ids])
        query += "".join(["CREATE INDEX {0}_idx_s{1}_vaf ON {0} USING btree (s{1}_vaf);".format(wt, i) for i in analysis.samples_ids])
        query += "".join(["CREATE INDEX {0}_idx_s{1}_qual ON {0} USING btree (s{1}_qual);".format(wt, i) for i in analysis.samples_ids])
        #query += "".join(["CREATE INDEX {0}_idx_s{1}_filter ON {0} USING btree (s{1}_filter);".format(wt, i) for i in analysis.samples_ids])
        # Index useless on bool column
        # query += "".join(["CREATE INDEX {0}_idx_s{1}_is_composite ON {0} USING btree (s{1}_is_composite);".format(wt, i) for i in analysis.samples_ids])
        # query += "CREATE INDEX {0}_idx_is_dom ON {0} USING btree (is_dom);".format(wt)
        # query += "CREATE INDEX {0}_idx_is_rec_hom ON {0} USING btree (is_rec_hom);".format(wt)
        # query += "CREATE INDEX {0}_idx_is_rec_htzcomp ON {0} USING btree (is_rec_htzcomp);".format(wt)
        # query += "CREATE INDEX {0}_idx_is_denovo ON {0} USING btree (is_denovo);".format(wt)
        # query += "CREATE INDEX {0}_idx_is_exonic ON {0} USING btree (is_exonic);".format(wt)
        # query += "CREATE INDEX {0}_idx_is_aut ON {0} USING btree (is_aut);".format(wt)
        # query += "CREATE INDEX {0}_idx_is_xlk ON {0} USING btree (is_xlk);".format(wt)
        # query += "CREATE INDEX {0}_idx_is_mit ON {0} USING btree (is_mit);".format(wt)

        # Add indexes on attributes columns
        for attr in analysis.attributes:
            for value, col_id in attr["values_map"].items():
                query += "CREATE INDEX {0}_idx_attr_{1} ON {0} USING btree (attr_{1});".format(wt, col_id)

        # Add indexes on panel columns
        # for panel in analysis.panels:
        #     query += "CREATE INDEX {0}_idx_panel_{1} ON {0} USING btree (panel_{1});".format(wt, panel["version_id"].replace("-", "_"))
        
        log(" > create index for variants random access")
        execute(query)
        
        # We just update progress without calling notify_all as a notify will be send by the next step
        progress["log"][5]["status"] = "done"
        progress["log"][5]["progress"] = 1
        

    def insert_wt_trx(self, analysis, progress):
        self.working_table_creation_update_status(analysis, progress, 6, "computing", 0.01)
        wt = "wt_{}".format(analysis.id)

        # Insert trx and their annotations
        q_fields  = "is_variant, variant_id, trx_pk_uid, trx_pk_value, vcf_line, regovar_score, bin, chr, pos, ref, alt, is_transition, "
        q_fields += "sample_tlist, sample_tcount, sample_alist, sample_acount, is_dom, is_rec_hom, is_rec_htzcomp, is_denovo, is_exonic, is_aut, is_xlk, is_mit, "
        q_fields += ", ".join(["s{}_gt".format(i) for i in analysis.samples_ids]) + ", "
        q_fields += ", ".join(["s{}_dp".format(i) for i in analysis.samples_ids]) + ", "
        q_fields += ", ".join(["s{}_dp_alt".format(i) for i in analysis.samples_ids]) + ", "
        q_fields += ", ".join(["s{}_qual".format(i) for i in analysis.samples_ids]) + ", "
        q_fields += ", ".join(["s{}_filter".format(i) for i in analysis.samples_ids]) + ", "
        q_fields += ", ".join(["s{}_is_composite".format(i) for i in analysis.samples_ids])
        # Add attribute's columns
        for attr in analysis.attributes:
            for value, col_id in attr["values_map"].items():
                q_fields += ", attr_{}".format(col_id)

        # Add panel's columns
        for panel in analysis.panels:
            q_fields += ", panel_{}".format(panel["version_id"].replace("-", "_"))
        
        q_select  = "False, _wt.variant_id, '{0}', {1}.regovar_trx_id, _wt.vcf_line, _wt.regovar_score, _wt.bin, _wt.chr, _wt.pos, "
        q_select += "_wt.ref, _wt.alt, _wt.is_transition, _wt.sample_tlist, _wt.sample_tcount, _wt.sample_alist, _wt.sample_acount, _wt.is_dom, _wt.is_rec_hom, "
        q_select += "_wt.is_rec_htzcomp, _wt.is_denovo, _wt.is_exonic, _wt.is_aut, _wt.is_xlk, _wt.is_mit, "
        q_select += ", ".join(["_wt.s{}_gt".format(i) for i in analysis.samples_ids]) + ", "
        q_select += ", ".join(["_wt.s{}_dp".format(i) for i in analysis.samples_ids]) + ", "
        q_select += ", ".join(["_wt.s{}_dp_alt".format(i) for i in analysis.samples_ids]) + ", "
        q_select += ", ".join(["_wt.s{}_qual".format(i) for i in analysis.samples_ids]) + ", "
        q_select += ", ".join(["_wt.s{}_filter".format(i) for i in analysis.samples_ids]) + ", "
        q_select += ", ".join(["_wt.s{}_is_composite".format(i) for i in analysis.samples_ids])
        
        # Add attribute's columns
        for attr in analysis.attributes:
            for value, col_id in attr["values_map"].items():
                q_select += ", _wt.attr_{}".format(col_id)

        # Add panel's columns
        for panel in analysis.panels:
            q_select += ", _wt.panel_{}".format(panel["version_id"].replace("-", "_"))
        
        q_from   = "{0} _wt".format(wt)

        # first loop over "variant db" in order to set common annotation to trx
        for dbuid in analysis.settings["annotations_db"]:
            if self.db_map[dbuid]["type"] == "variant":
                q_fields += ", " + ", ".join(["_{}".format(fuid) for fuid in self.db_map[dbuid]["fields"]])
                q_select += ", " + ", ".join(["_{}".format(fuid) for fuid in self.db_map[dbuid]["fields"]])


        # Second loop to execute insert query by trx annotation db
        for dbuid in analysis.settings["annotations_db"]:
            if self.db_map[dbuid]["type"] == "transcript":
                dbname = "_db_{}".format(dbuid)
                q_from_db   = q_from + " INNER JOIN {0}".format(self.db_map[dbuid]['join'].format(dbname, '_wt'))
                q_fields_db = q_fields + ", " + ", ".join(["_{}".format(fuid) for fuid in self.db_map[dbuid]["fields"]])
                pk_uid = self.db_map[dbuid]["db_pk_field_uid"]
                q_select_db = q_select.format(pk_uid, dbname)
                q_select_db += ", " + ", ".join(["{}.{}".format(dbname, self.fields_map[fuid]["name"]) for fuid in self.db_map[dbuid]["fields"]])

                # execute query
                query = "INSERT INTO {0} ({1}) SELECT {2} FROM {3} WHERE _wt.is_variant;".format(wt, q_fields_db, q_select_db, q_from_db)
                res = execute(query)
                log(" > {} trx inserted for {} annotations".format(res.rowcount, self.db_map[dbuid]["name"]))

        # We just update progress without calling notify_all as a notify will be send by the next step
        progress["log"][6]["status"] = "done"
        progress["log"][6]["progress"] = 1


    def create_wt_trx_indexes(self, analysis, progress):
        # query = "CREATE INDEX {0}_idx_vid ON {0} USING btree (variant_id);".format(w_table)
        # query += "CREATE INDEX {0}_idx_var ON {0} USING btree (bin, chr, pos, trx_pk_uid, trx_pk_value);".format(w_table)
        pass


    def update_wt_compute_prefilter_single(self, analysis, sample_id, sex, progress, prg, step):
        query = "UPDATE wt_{0} SET "
        # Dominant
        if sex == "F":
            query += "is_dom=(s{1}_gt>1), "
        else: # sex == "M"
            query += "is_dom=(chr=23 OR s{1}_gt>1), "
        # Recessif Homozygous
        query += "is_rec_hom=(s{1}_gt=1), "
        # Recessif Heterozygous compoud
        query += "is_rec_htzcomp=(s{1}_is_composite), "
        # Inherited and denovo are not available for single
        # Autosomal
        query += "is_aut=(chr<23), "
        # X-Linked
        query += "is_xlk=(chr=23), "
        # Mitochondrial
        query += "is_mit=(chr=25);"
        execute(query.format(analysis.id, sample_id))
        prg += step
        self.working_table_creation_update_status(analysis, progress, 4, "computing", prg)


    def update_wt_compute_prefilter_trio(self, analysis, samples_ids, trio, progress, prg, step):
        sex = trio["child_sex"]
        child_id = trio["child_id"]
        mother_id = trio["mother_id"]
        father_id = trio["father_id"]
        child_idx = trio["child_index"]
        mother_idx = trio["mother_index"]
        father_idx = trio["father_index"]
        query = "UPDATE wt_{0} SET "
        # Dominant
        if sex == "F":
            query += "is_dom=(s{1}_gt>1), "
        else: # sex == "M"
            query += "is_dom=(chr=23 OR s{1}_gt>1), "
        # Recessif Homozygous
        query += "is_rec_hom=(s{1}_gt=1), "
        # Inherited and denovo
        query += "is_denovo=(s{1}_gt>0 AND COALESCE(s{2}_gt,0)<=0 AND COALESCE(s{3}_gt,0)<=0), "
        # Autosomal
        query += "is_aut=(chr<23), "
        # X-Linked
        query += "is_xlk=(chr=23 AND " 
        query += "s{1}_gt=1" if trio["child_sex"] == "M" else "s{1}_gt>1"
        query += " AND s{2}_gt>1"
        query += " AND s{3}_gt>1), " if trio["child_sex"] == "F" else "), "
        # mitochondrial
        query += "is_mit=(chr=25)"
        execute(query.format(analysis.id, child_id, mother_id, father_id, analysis.db_suffix))
        prg += step
        self.working_table_creation_update_status(analysis, progress, 4, "computing", prg)
        
        # Recessif Heterozygous compoud
        query = "UPDATE wt_{0} u SET is_rec_htzcomp=True WHERE u.variant_id IN (SELECT DISTINCT UNNEST(sub.vids) as variant_id FROM ( SELECT array_agg(w.variant_id) as vids, g.name2 FROM wt_{0} w  INNER JOIN refgene{4} g ON g.chr=w.chr AND g.trxrange @> w.pos  WHERE  s{1}_gt > 1 AND ( (s{2}_gt > 1 AND (s{3}_gt = NULL or s{3}_gt < 2)) OR (s{3}_gt > 1 AND (s{2}_gt = NULL or s{2}_gt < 2))) GROUP BY name2 HAVING count(*) > 1) AS sub )"
        res = execute(query.format(analysis.id, child_id, mother_id, father_id, analysis.db_suffix))
        prg += step
        self.working_table_creation_update_status(analysis, progress, 4, "computing", prg)


    def update_wt_mergin_trx_variant(self, analysis, progress):
        self.working_table_creation_update_status(analysis, progress, 7, "computing", 0.1)
        
        
        query = "UPDATE wt_{0} w SET {1} FROM (SELECT variant_id, {2} FROM wt_{0} WHERE NOT is_variant GROUP BY variant_id) as sub WHERE w.is_variant AND w.variant_id=sub.variant_id"
        
        
        # Step 1: mergin trx annotation into variant
        q1 = []
        q2 = [] 
        list_field = []
        for dbuid in analysis.settings["annotations_db"]:
            if self.db_map[dbuid]["type"] == "transcript":
                for fuid in self.db_map[dbuid]["fields"]:
                    if self.fields_map[fuid]['type'] != 'list':
                        q1.append("_{0} = sub._{0}".format(fuid))
                        q2.append(self.sql_agg_map[self.fields_map[fuid]['type']].format("_" + fuid))
                    else:
                        list_field.append(fuid)
        if len(q1) > 0 and len(q2) > 0        :
            res = execute(query.format(analysis.id, ','.join(q1), ','.join(q2)))
            log(" > {} trx annotation merged into their respective variant".format(res.rowcount))
        self.working_table_creation_update_status(analysis, progress, 7, "computing", 0.25)
        
        # Manage special sql query for list fields
        if len(list_field) > 0:
            query = "UPDATE wt_{0} w SET {1} FROM (SELECT variant_id, {2} FROM (SELECT variant_id, {3} FROM  wt_{0}) AS t GROUP BY variant_id) AS sub WHERE w.is_variant AND w.variant_id=sub.variant_id"
            q1 = []
            q2 = []
            q3 = []
            for fuid in list_field:
                q1.append("_{0} = sub._{0}".format(fuid))
                q2.append("array_agg(DISTINCT _{0}) AS _{0}".format(fuid))
                q3.append("unnest(_{0}) as _{0}".format(fuid))
            
            res = execute(query.format(analysis.id, ','.join(q1), ','.join(q2), ','.join(q3)))
            log(" > {} trx list typed annotation merged into their respective variant".format(res.rowcount))
        self.working_table_creation_update_status(analysis, progress, 7, "computing", 0.5)

        # Step 2: deleting trx when only one by variant annotation for variant that have more than 1 trx
        # merge variant and trx id
        query = "UPDATE wt_{0} w SET trx_pk_uid=sub.trx_pk_uid, trx_pk_value=sub.trx_pk_value FROM "
        query+= "(SELECT variant_id, max(trx_pk_uid) as trx_pk_uid, max(trx_pk_value) as trx_pk_value FROM wt_{0} WHERE NOT is_variant GROUP BY variant_id HAVING count(*) = 1) AS sub "
        query+= "WHERE w.is_variant AND w.variant_id=sub.variant_id"
        res = execute(query.format(analysis.id))
        self.working_table_creation_update_status(analysis, progress, 7, "computing", 0.75)
        # delete useless trx entries
        query = "DELETE FROM wt_{0} w WHERE not w.is_variant AND w.variant_id IN (SELECT variant_id FROM wt_{0} WHERE NOT is_variant GROUP BY variant_id HAVING count(*) = 1)"
        res = execute(query.format(analysis.id))
        log(" > {} single trx annotation removed (merged with the variant)".format(res.rowcount))
        
        # We just update progress without calling notify_all as a notify will be send by the next step
        progress["log"][7]["status"] = "done"
        progress["log"][7]["progress"] = 1
    

    def create_wt_stored_filters(self, analysis, progress):
        self.working_table_creation_update_status(analysis, progress, 8, "computing", 0.1)
        
        for flt in analysis.filters:
            log(" > compute filter {}: {}".format(flt.id, flt.name))
            self.update_wt(analysis, "filter_{}".format(flt.id), flt.filter)
            
        # We just update progress without calling notify_all as a notify will be send by the next step
        progress["log"][8]["status"] = "done"
        progress["log"][8]["progress"] = 1
    

    def update_wt_set_restore_selection(self, analysis, progress):
        self.working_table_creation_update_status(analysis, progress, 9, "computing", 0.1)
        # TODO: create sql request from json selection data.
        
        # We just update progress without calling notify_all as a notify will be send by the next step
        progress["log"][9]["status"] = "done"
        progress["log"][9]["progress"] = 1


    def update_wt_samples_stats(self, analysis, progress):
        # TODO: improve progress feedback according to sample count and vep consequences
        self.working_table_creation_update_status(analysis, progress, 10, "computing", 0.1)
        wt  = "wt_{}".format(analysis.id)
        
        with_vep = None
        
        # check annotations available to knwo which stats will be computed
        for dbuid in analysis.settings["annotations_db"]:
            if self.db_map[dbuid]["name"].upper().startswith("VEP_"):
                with_vep = dbuid
        
        #
        # Compute stats for all sample 
        #
        astats = {
            "total_variant" : execute("SELECT COUNT(*) FROM {} WHERE is_variant".format(wt)).first()[0],
            "total_transcript": execute("SELECT COUNT(*) FROM {} WHERE NOT is_variant".format(wt)).first()[0],
            
            # TODO: OPTIMIZATION : find better way with postgresql sql JSON operators
            # "filter": {fid: execute("SELECT COUNT(*) FROM {0} WHERE is_variant AND s{1}_filter::text LIKE '%{2}%'".format(wt, sample.id, fid)).first()[0] for fid in sample.filter_description.keys()},
            
            "variants_classes": {
                "ref": execute("SELECT COUNT(*) FROM {0} WHERE is_variant AND ref=alt".format(wt)).first()[0],
                "snv": execute("SELECT COUNT(*) FROM {0} WHERE is_variant AND ref<>alt AND char_length(ref)=1 AND char_length(alt)=1".format(wt)).first()[0],
                "mnv": execute("SELECT COUNT(*) FROM {0} WHERE is_variant AND ref<>alt AND char_length(ref)>1 AND char_length(alt)=char_length(ref)".format(wt)).first()[0],
                "insertion": execute("SELECT COUNT(*) FROM {0} WHERE is_variant AND char_length(ref)=0 AND char_length(alt)>0".format(wt)).first()[0],
                "deletion":  execute("SELECT COUNT(*) FROM {0} WHERE is_variant AND char_length(ref)>0 AND char_length(alt)=0".format(wt)).first()[0],
                "others": execute("SELECT COUNT(*) FROM {0} WHERE is_variant AND char_length(ref)<>char_length(alt) AND char_length(ref)>0 AND char_length(alt)>0".format(wt)).first()[0]
                }
            }
        self.working_table_creation_update_status(analysis, progress, 10, "computing", 0.20)
        
        consequences = []
        if with_vep:
            for k, v in self.db_map[with_vep]["fields"].items():
                if v["name"] == "consequence":
                    test_field_uid = k
            consequences = [f[0] for f in execute("SELECT DISTINCT(UNNEST(_{1})) FROM {0} WHERE NOT is_variant ".format(wt, test_field_uid))]
            vep_consequences = {c: execute("SELECT count(*) FROM {0} WHERE NOT is_variant AND '{2}'=ANY(_{1})".format(wt, test_field_uid, c)).first()[0] for c in consequences}
            astats.update({"vep_consequences": vep_consequences})

        analysis.statistics = astats
        analysis.save()
        self.working_table_creation_update_status(analysis, progress, 10, "computing", 0.40)


        #
        # Compute stats by sample
        #
        analysis.init(1)
        for sample in analysis.samples:
            # skip if not need
            if sample.stats is not None:
                continue
            # Compute simple common stats
            stats = {
                "total_variant" : execute("SELECT COUNT(*) FROM sample_variant{} WHERE sample_id={}".format(analysis.db_suffix, sample.id)).first()[0],
                "total_transcript": execute("SELECT COUNT(*) FROM {} WHERE s{}_gt>=0 AND NOT is_variant".format(wt, sample.id)).first()[0],
                
                # TODO : this stat can only be computed by the vcf_import manager by checking vcf header
                "matching_reference": True, 
                
                # TODO: OPTIMIZATION : find better way with postgresql sql JSON operators
                "filter": {fid: execute("SELECT COUNT(*) FROM {0} WHERE s{1}_gt>=0 AND is_variant AND s{1}_filter::text LIKE '%{2}%'".format(wt, sample.id, fid)).first()[0] for fid in sample.filter_description.keys()},
                
                "sample_total_variant": execute("SELECT COUNT(*) FROM {0} WHERE s{1}_gt>=0 AND is_variant".format(wt, sample.id)).first()[0],
                "variants_classes": {
                    "not": execute("SELECT COUNT(*) FROM {0} WHERE s{1}_gt=-1 AND is_variant".format(wt, sample.id)).first()[0],
                    "ref": execute("SELECT COUNT(*) FROM {0} WHERE s{1}_gt=0 AND is_variant".format(wt, sample.id)).first()[0],
                    "snv": execute("SELECT COUNT(*) FROM {0} WHERE s{1}_gt>0 AND is_variant AND char_length(ref)=1 AND char_length(alt)=1".format(wt, sample.id)).first()[0],
                    "mnv": execute("SELECT COUNT(*) FROM {0} WHERE s{1}_gt>0 AND is_variant AND char_length(ref)>1 AND char_length(alt)=char_length(ref)".format(wt, sample.id)).first()[0],
                    "insertion": execute("SELECT COUNT(*) FROM {0} WHERE s{1}_gt>0 AND is_variant AND char_length(ref)=0 AND char_length(alt)>0".format(wt, sample.id)).first()[0],
                    "deletion":  execute("SELECT COUNT(*) FROM {0} WHERE s{1}_gt>0 AND is_variant AND char_length(ref)>0 AND char_length(alt)=0".format(wt, sample.id)).first()[0],
                    "others": execute("SELECT COUNT(*) FROM {0} WHERE s{1}_gt>0 AND is_variant AND char_length(ref)<>char_length(alt) AND char_length(ref)>0 AND char_length(alt)>0".format(wt, sample.id)).first()[0]
                    }
                }
            
            if with_vep:
                for k, v in self.db_map[with_vep]["fields"].items():
                    if v["name"] == "consequence":
                        test_field_uid = k
                vep_consequences = {c: execute("SELECT count(*) FROM {0} WHERE NOT is_variant AND s{3}_gt>0 AND '{2}'=ANY(_{1})".format(wt, test_field_uid, c, sample.id)).first()[0] for c in consequences}
                stats.update({"vep_consequences": vep_consequences})
            
            # Save stats
            sample.stats = stats
            sample.save()
            
        # We just update progress without calling notify_all as a notify will be send by the next step
        progress["log"][10]["status"] = "done"
        progress["log"][10]["progress"] = 1







    def create_panel_table(self, panel_id, ref):
        panel_table = "panel_{}_{}".format(ref, panel_id.replace("-", "_"))

        # Do nothing if panel table alread exits
        sql = "SELECT * FROM information_schema.tables WHERE table_name='panel_{}'".format(panel_id)
        panel_exists = execute(sql).rowcount > 0
        if panel_exists: return

        # Retrieve panel data
        sql = "SELECT * FROM panel_entry WHERE id='{}'".format(panel_id)
        result = execute(sql)
        if result.rowcount == 0:
            raise RegovarException("Unable to retrieve panel with id \"{}\"".format(panel_id))
        panel_data = result.first().data

        # Create sql query
        query = "DROP TABLE IF EXISTS {0} CASCADE; CREATE UNLOGGED TABLE {0} (\
            chr bigint, \
            loc int8range); \
            INSERT INTO {0} (chr, loc) VALUES ".format(panel_table)

        genes = []
        for entry in panel_data:
            if entry["type"] == "gene":
                genes.append(entry["symbol"])
            else:
                query += "({}, int8range({}, {})), ".format(entry["chr"], entry["start"], entry["end"])
        
        if len(genes) > 0:
            for ge in execute("SELECT chr, trxrange FROM refgene_{} WHERE name2 IN ({})".format(ref, ",".join(["'{}'".format(t) for t in genes]))):
                query += "({}, int8range({}, {})), ".format(ge.chr, ge.trxrange.lower, ge.trxrange.upper)

        execute(query[:-2])



    def create_wt_panel_table(self, analysis, panel_id):
        wt = "wt_{}".format(analysis.id)
        col = "panel_{}".format(panel_id.replace("-", "_"))
        ref = execute("SELECT table_suffix FROM reference WHERE id={}".format(analysis.reference_id)).first().table_suffix

        # Do nothing if panel table alread exits
        sql = "SELECT column_name FROM information_schema.columns WHERE table_name='{}' AND column_name='{}'".format(wt, col)
        col_exists = execute(sql).rowcount > 0
        if col_exists: return
        
        # Ensure that panels exists
        self.create_panel_table(panel_id, ref)

        # Create sql query
        panel = "panel_{}_{}".format(ref, panel_id.replace("-", "_"))
        query = "ALTER TABLE {0} ADD COLUMN {1} boolean; update {0} w SET {1}=True FROM {2} p WHERE w.chr=p.chr AND w.pos <@ p.loc;".format(wt, col, panel)
        execute(query)








    async def prepare(self, analysis, filter_json, order=[]):
        """
            Build tmp table for the provided filter/order by parameters
            set also the total count of variant/transcript
        """
        from core.core import core
        log("---\nPrepare tmp working table for analysis {}".format(analysis.id))
        progress = {"start": datetime.datetime.now().ctime(), "analysis_id": analysis.id, "progress": 0}
        await core.notify_all_co({'action':'filtering_prepare', 'data': progress})
        if order and len(order) == 0: order = None
        order = remove_duplicates(order)

        # Check if need to create new columns to the table (custom filters, panels or phenotypes filters)
        def get_panels_filters(data):
            """ 
                Recursive method to retrieve lists of panels and custom filters
            """
            panels = []
            filters = []
            operator = data[0]
            
            if operator in ['AND', 'OR']:
                if len(data[1]) > 0:
                    for d in data[1]:
                        p, f = get_panels_filters(d)
                        panels += p
                        filters += f
            elif operator in ['IN', 'NOTIN']:
                field = data[1]
                if field[0] == 'filter':
                    filters.append(field[1])
                elif field[0] == 'panel':
                    panels.append(field[1])
            return panels, filters
                
        panels, filters = get_panels_filters(filter_json)
        for p in panels:
            self.create_wt_panel_table(analysis, p)        

        # Create schema
        w_table = 'wt_{}'.format(analysis.id)
        query = "DROP TABLE IF EXISTS {0}_tmp CASCADE; SET LOCAL work_mem='1GB'; CREATE UNLOGGED TABLE {0}_tmp AS "
        query += "SELECT ROW_NUMBER() OVER(ORDER BY {3}) as page, variant_id, array_remove(array_agg(trx_pk_value), NULL) as trx, count(trx_pk_value) as trx_count{1} FROM {0}{2} GROUP BY variant_id{1}"
        
        f_fields = ", " + ", ".join([self.parse_order_field(analysis, f) for f in  order]) if order else ", chr, pos"
        f_order  = ", ".join(["{}{}".format(self.parse_order_field(analysis, f), " DESC" if f[0] == "-" else "") for f in  order]) if order else "chr, pos"
        f_filter = self.parse_filter(analysis, filter_json, order)
        f_filter = " WHERE {0}".format(f_filter) if len(filter_json[1]) > 0 else " WHERE is_variant"
        query = query.format(w_table, f_fields, f_filter, f_order)

        sql_result = None
        log("Filter: {0}\nFields:{1} \nOrder: {2}\nQuery: {3}".format(filter_json, analysis.fields, order, query))
        with Timer() as t:
            sql_result = execute(query)
            execute("CREATE INDEX {0}_tmp_page ON {0}_tmp USING btree (page);".format(w_table))
        
        total_variant = sql_result.rowcount
        log("Time: {0}\nResults count: {1}".format(t, total_variant))
        
        # Save filter data
        settings = {}
        try:
            analysis.filter = filter_json
            analysis.order = order or []
            analysis.total_variants = total_variant
            analysis.save()
        except:
            err("Not able to save current filter")
        
        progress.update({"progress": 1})
        await core.notify_all_co({'action':'filtering_prepare', 'data': progress})


    def update_wt(self, analysis, column, filter_json):
        """
            Add of update working table provided boolean's column with variant that match the provided filter
            Use this method to dynamically Add/Update saved filter or panel filter
            
            Note that as we need to run this method async when creating filter (filter_manager.create_update_filter), 
            we cannot use async (incompatible with mutithread)
        """
        from core.core import core
        log("---\nUpdating working table of analysis {}".format(analysis.id))
        progress = {"start": datetime.datetime.now().ctime(), "analysis_id": analysis.id, "progress": 0, "column": column}
        core.notify_all({'action':'wt_update', 'data': progress})
        
        # Alter schema
        w_table = 'wt_{}'.format(analysis.id)
        query = "ALTER TABLE {0} DROP COLUMN IF EXISTS {1} CASCADE, ADD COLUMN {1} boolean; "
        execute(query.format(w_table, column))
        log("Column: {0} init".format(column))
        
        progress.update({"progress": 0.33})
        core.notify_all({'action':'wt_update', 'data': progress})
        
        # Set filtered data
        # Note : As trx_pk_value may be null, we cannot use '=' operator and must use 'IS NOT DISTINCT FROM' 
        #        as two expressions that return 'null' are not considered as equal in SQL
        query = "UPDATE {0} SET {1}=True FROM (SELECT variant_id, trx_pk_value FROM {0} {2}) AS _sub WHERE {0}.variant_id=_sub.variant_id AND {0}.trx_pk_value IS NOT DISTINCT FROM _sub.trx_pk_value; " 
        subq = self.parse_filter(analysis, filter_json, [])
        subq = "WHERE " + subq if subq else ""
        query = query.format(w_table, column, subq)
        sql_result = None
        log("Filter: {0}\nQuery: {1}".format(filter_json, query))
        with Timer() as t:
            sql_result = execute(query)
        total_variant = sql_result.rowcount
        log("Time: {0}\nResults count: {1}".format(t, total_variant))
        
        progress.update({"progress": 0.66})
        core.notify_all({'action':'wt_update', 'data': progress})
        
        # Create index
        query = "CREATE INDEX IF NOT EXISTS {0}_idx_{1} ON {0} USING btree ({1});"
        execute(query.format(w_table, column))
        log("Index updated: idx_{0}".format(column))
        
        progress.update({"progress": 1})
        progress.update({"count": total_variant})
        core.notify_all({'action':'wt_update', 'data': progress})
        # force analysis to reload it's filter data
        analysis.filters_ids = analysis.get_filters_ids()
        analysis.filters = analysis.get_filters(0)
        return total_variant


    async def get_variant(self, analysis, fields, limit=RANGE_DEFAULT, offset=0):
        """
            Return results from current temporary table according to provided fields and pagination information
            
        """
        from core.core import core
        limit = min(limit, RANGE_MAX)
        w_table = 'wt_{}'.format(analysis.id)
        query = "SELECT ws.variant_id, wt.is_selected, ws.trx_count, {1} FROM {0}_tmp ws INNER JOIN {0} wt ON ws.variant_id=wt.variant_id WHERE wt.is_variant AND ws.page>={2} ORDER BY ws.page LIMIT {3}"
        
        query = query.format(w_table, self.parse_fields(analysis, fields, "wt."), offset, limit)
        sql_result = None
        with Timer() as t:
            sql_result = await execute_aio(query)
            
        log("--- Select:\nFrom: {0}\nTo: {1}\nFields: {2}\nQuery: {3}\nTime: {4}".format(offset, limit, fields, query, t))
        return sql_result
    

    async def get_trx(self, analysis, fields, variant_id):
        """
            Return results from current temporary table according to provided fields and variant
        """
        from core.core import core
        w_table = 'wt_{}'.format(analysis.id)
        
        sub_query = "SELECT unnest(trx) FROM {0}_tmp WHERE variant_id={1}".format(w_table, variant_id)
        query = "SELECT variant_id, trx_pk_value as trx_id, is_selected, {1} FROM {0} WHERE variant_id={2} AND trx_pk_value IN ({3})"
        
        query = query.format(w_table, self.parse_fields(analysis, fields, ""), variant_id, sub_query)
        sql_result = None
        with Timer() as t:
            sql_result = await execute_aio(query)
            
        log("--- Select trx:\nVariantId: {0}\nTrx count: {1}\nTime: {2}".format(variant_id, sql_result.rowcount, t))
        return sql_result




    async def request(self, analysis_id, filter_json=None, fields=None, order=None, variant_id=None, limit=RANGE_DEFAULT, offset=0):
        """
            Commont request to manage all different cases
        """
        limit = max(1, min(limit, RANGE_MAX))
        fields = remove_duplicates(fields)
        order = remove_duplicates(order)
        if fields is None or not isinstance(fields, list) or len(fields) == 0:
            raise RegovarException("You must specify which fields shall be returned by the filtering query.")
        
        # Get analysis data and check status if ok to do filtering
        analysis = Analysis.from_id(analysis_id)
        if analysis is None:
            raise RegovarException("Not able to retrieve analysis with provided id: {}".format(analysis_id))
        
        # If need to create working table
        if not analysis.status or analysis.status in ["empty", "waiting"]:
            # check if all samples are ready to be use for the creation of the working table
            in_samples = {"loading": [], "error": [], "empty": [], "ready": []}
            for sid in analysis.samples_ids:
                sample = Sample.from_id(sid)
                in_samples[sample.status].append(sid)
                
            if len(in_samples["error"]) > 0:
                analysis.status = "error"
                analysis.computing_progress = {
                    "error_message": "Import of the sample () for the analysis {} failled.".format(", ".join(in_samples["error"]), analysis.id),
                    "status" : "error"}
                analysis.save()
            elif len(in_samples["loading"]) > 0:
                analysis.status = "waiting"
                analysis.computing_progress = {
                    "error_message": "Import of the sample () for the analysis {} are in progress.".format(", ".join(in_samples["loading"]), analysis.id),
                    "status" : "waiting"}
                analysis.save()

            if sample.status != "ready":
                return {"status": analysis.status, "progress": analysis.computing_progress}
            
            # Execute the creation of the working table async
            analysis.status = "computing"
            analysis.computing_progress = None
            analysis.save()
            run_async(self.create_working_table, analysis.id)
            return {"status": analysis.status, "progress": analysis.computing_progress}
        
        elif analysis.status != "ready":
            return {"status": analysis.status, "progress": analysis.computing_progress}
        
        
        # Prepare wt for specific filter query
        # if filter_json is None, we assume that we are requesting the current tmp working table formerly prepared
        # We need to prepare only if provided filter is different from current or if order is different
        former_filter = json.dumps(analysis.filter)
        former_order = json.dumps(analysis.order)
        current_filter = former_filter if filter_json is None else json.dumps(filter_json)
        current_order = former_order if order is None else json.dumps(order)
        
        # Check if temp working table exists 
        sql = "SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME='wt_{}_tmp'".format(analysis.id)
        wtmp_exists = execute(sql).rowcount > 0

        if not wtmp_exists or former_filter != current_filter or former_order != current_order:
            # Need to prepare temp table
            await self.prepare(analysis, filter_json, order)
        elif not analysis.filter:
            if filter_json is None:
                raise RegovarException("Analysis {} is not ready. You need to 'prepare' your filter by providing the filter and ordering parameters before requesting results.".format(analysis.id))
                
        # Get results
        vmode = variant_id is None or variant_id == ""
        if vmode:
            sql_result = await self.get_variant(analysis, fields, limit, offset+1)
        else:
            sql_result = await self.get_trx(analysis, fields, variant_id)
            
        # Format result
        result = []
        
        with Timer() as t:
            if sql_result is not None:
                for row in sql_result:
                    if vmode:
                        entry = {"id" : str(row.variant_id), "is_selected": row.is_selected, "trx_count": row.trx_count}
                    else:
                        entry = {"id" : "{}_{}".format(row.variant_id, row.trx_id), "is_selected": row.is_selected}
                    for f_uid in fields:
                        # Manage special case for fields splitted by sample
                        if self.fields_map[f_uid]["name"].startswith("s{}_"):
                            pattern = "row." + self.fields_map[f_uid]["name"]
                            r = {}
                            for sid in analysis.samples_ids:
                                r[sid] = FilterEngine.parse_result(eval(pattern.format(sid)))
                            entry[f_uid] = r
                        else:
                            if f_uid == "7166ec6d1ce65529ca2800897c47a0a2": # field = pos
                                entry[f_uid] = FilterEngine.parse_result(eval("row.{}".format(self.fields_map[f_uid]["name"])) + 1)
                            elif self.fields_map[f_uid]["db_name_ui"] in ["Variant", "Regovar"]:
                                entry[f_uid] = FilterEngine.parse_result(eval("row.{}".format(self.fields_map[f_uid]["name"])))
                            else:
                                entry[f_uid] = FilterEngine.parse_result(eval("row._{}".format(f_uid)))
                    result.append(entry)
        log("Result processing: {0}\n".format(t))
        
        
        
        return {"status": "ready", "wt_total_variants" : analysis.total_variants, "wt_total_results" : 0, "from":0, "to": 0, "results" : result}



    def parse_fields(self, analysis, fields, prefix):
        """
            Parse the json fields and return the corresponding postgreSQL query
            /!\ Note: warning when updating, this method is also used by the analysis_manager.get_selection method.
        """
        fields_names = []
        for f_uid in fields:
            if self.fields_map[f_uid]["db_name_ui"] in ["Variant", "Regovar"]:
                # Manage special case for fields splitted by sample
                if self.fields_map[f_uid]["name"].startswith("s{}_"):
                    fields_names.extend([prefix + self.fields_map[f_uid]["name"].format(s) for s in analysis.samples_ids])
                else:
                    fields_names.append(prefix+"{}".format(self.fields_map[f_uid]["name"]))
            else:
                fields_names.append(prefix+"_{}".format(f_uid))
        return ', '.join(fields_names)

       
       

    def parse_order_field(self, analysis, uid):
        """
            Return the SQL column name to use for the provided field uid
        """
        # Manage case of uid comming from order json (which can prefix uid by "-" for ordering DESC
        uid = uid[1:] if uid[0] == '-' else uid
                  

        if self.fields_map[uid]["db_name_ui"] in ["Variant", "Regovar"]:
            # Manage special case for fields splitted by sample
            if self.fields_map[uid]["name"].startswith("s{}_"):
                # Manage special case for filter field which have type JSON that is not complient with GROUP BY sql operator
                suffix = " #>> '{}'" if self.fields_map[uid]["name"] == "s{}_filter" else ""
                return self.fields_map[uid]["name"].format(analysis.samples_ids[0]) + suffix
            else:
                return self.fields_map[uid]["name"]
        return "_" + uid



    def parse_filter(self, analysis, filters, order=None):
        """
            Parse the json filter and return the corresponding postgreSQL query
        """
        # Init some global variables
        wt = "wt_{}".format(analysis.id)


        # Build WHERE
        temporary_to_import = {}


        def build_filter(data):
            """ 
                Recursive method that build the query from the filter json data at operator level 
            """
            operator = data[0]
            if operator in ['AND', 'OR']:
                if len(data[1]) == 0:
                    return ''
                return ' (' + FilterEngine.op_map[operator].join([build_filter(f) for f in data[1]]) + ') '
            elif operator in ['==', '!=', '>', '<', '>=', '<=']:
                # Comparaison with a field: the field MUST BE the first operande
                if data[1][0] != 'field':
                    raise RegovarException("Comparaison operator MUST have field as left operande.")
                    pass
                metadata = self.fields_map[data[1][1]]
                
                
                # Manage special case for fields splitted by sample
                if metadata['name'].startswith('s{}_'):
                    return ' (' + ' OR '.join(['{0}{1}{2}'.format(metadata['name'].format(s), FilterEngine.op_map[operator], parse_value(metadata["type"], data[2])) for s in analysis.samples_ids]) + ') '
                elif metadata["type"] == "list":
                    return '{2}{1} ANY({0})'.format(parse_value(metadata["type"], data[1]), FilterEngine.op_map[operator], parse_value(metadata["type"], data[2]))
                else:
                    return '{0}{1}{2}'.format(parse_value(metadata["type"], data[1]), FilterEngine.op_map[operator], parse_value(metadata["type"], data[2]))
            elif operator in ['~', '!~']:
                return '{0}{1}{2}'.format(parse_value('string', data[1]), FilterEngine.op_map[operator], parse_value('string%', data[2]))
            elif operator in ['IN', 'NOTIN']:
                field = data[1]
                if field[0] == 'sample':
                    sql = 'NOT NULL' if operator == 'IN' else 'NULL'
                    return "s{}_gt IS ".format(field[1]) + sql
                elif field[0] == 'filter':
                    sql = '' if operator == 'IN' else 'NOT '
                    return sql + "filter_{}".format(field[1])
                elif field[0] == 'attr':
                    sql = '' if operator == 'IN' else 'NOT '
                    return sql + "attr_{}".format(field[1])
                elif field[0] == 'panel':
                    sql = '' if operator == 'IN' else 'NOT '
                    return sql + "panel_{}".format(field[1].replace("-", "_"))

                

        def parse_value(ftype, data):
            if data[0] == 'field':
                if self.fields_map[data[1]]["type"] == ftype:
                    if self.fields_map[data[1]]['db_name'] == "wt" :
                        return "{0}".format(self.fields_map[data[1]]["name"])
                    else:
                        return "_{0}".format(data[1])
            if data[0] == 'value':
                if ftype in ['int', 'float', 'enum', 'bool', 'sample_array']:
                    return str(data[1])
                elif ftype in ['string', 'list', 'sequence']:
                    return "'{0}'".format(data[1])
                elif ftype == 'string%':
                    return "'%%{0}%%'".format(data[1])
                elif ftype == 'range' and len(data) == 3:
                    return 'int8range({0}, {1})'.format(data[1], data[2])
            raise RegovarException("FilterEngine.request.parse_value - Unknow type: {0} ({1})".format(ftype, data))


        query = build_filter(filters)
        if query is not None:
            query =query.strip()


        return query






    @staticmethod
    def get_hasname(analysis_id, mode, fields, filter_json):
        # clean and sort fields list
        clean_fields = fields
        clean_fields.sort()
        clean_fields = list(set(clean_fields))

        string_id = "{0}{1}{2}{3}".format(analysis_id, mode, clean_fields, json.dumps(filter_json))
        return hashlib.md5(string_id.encode()).hexdigest()


    @staticmethod
    def parse_result(value):
        """
            Parse value returned by sqlAlchemy and cast it, if needed, into "simples" python types
        """
        # if value is None:
        #     return ""
        if type(value) == psycopg2._range.NumericRange:
            return (value.lower, value.upper)
        return value
 

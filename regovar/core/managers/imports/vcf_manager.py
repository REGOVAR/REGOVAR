#!env/python3
# coding: utf-8

try:
    import ipdb
except ImportError:
    pass


import os
import datetime
import sqlalchemy
import subprocess
import reprlib
import gzip
from pysam import VariantFile
import json

from core.managers.imports.abstract_import_manager import AbstractImportManager, AbstractTranscriptDataImporter
from core.framework.common import *
import core.model as Model

from config import *
from core.managers.imports.vcf_import_vep import VepImporter
from core.managers.imports.vcf_import_snpeff import SnpEffImporter







# =======================================================================================================
# Tools
# =======================================================================================================

def count_vcf_row(filename):
    """
        Use linux OS commands to quickly count variant to parse in the vcf file
    """
    bashCommand = 'grep -v "^#" ' + str(filename) +' | wc -l'
    if filename.endswith("gz"):
        bashCommand = "z" + bashCommand
    process = subprocess.Popen(bashCommand, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    cmd_out = process.communicate()[0]
    # returns results
    return int(cmd_out.decode('utf8'))


def debug_clear_header(filename):
    """
        A workaround to fix a bug with GVCF header with pysam
        EDIT : in fact the problem to be that pysam do not support some kind of compression, so this command 
        is still used to rezip the vcf in a supported format.
    """
    bashCommand = "grep -v '^##GVCFBlock' {0} > {0}.regovar_import".format(filename)
    if filename.endswith("gz") or filename.endswith("zip"):
        bashCommand = "z" + bashCommand
    process = subprocess.Popen(bashCommand, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    #bashCommand = "mv /var/regovar/downloads/tmp_workaround  {} ".format(filename)
    #process = subprocess.Popen(bashCommand, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    process.wait()
    return "{}.regovar_import".format(filename)


def prepare_vcf_parsing(reference_id, filename):
    """
        Parse vf headers and return information about which data shall be parsed
        and stored in the database
    """
    # Extract headers
    filename = debug_clear_header(filename)

    hcount = 0
    headers = {}
    samples = []
    _op = open
    #if filename.endswith('gz') or filename.endswith('zip'):
        #_op = gzip.open
    try:
        with _op(filename) as f:
            for line in f:
                hcount += 1
                if _op != open:
                    line = line.decode()
                if line.startswith('##'):
                    l = line[2:].strip()
                    l = [l[0:l.index('=')], l[l.index('=')+1:]]
                    if l[0] not in headers.keys():
                        if l[0] == 'INFO' :
                            headers[l[0]] = {}
                        else:
                            headers[l[0]] = []
                    if l[0] == 'INFO' :
                        data = l[1][1:-1].split(',')
                        info_id   = data[0][3:]
                        info_type = data[2][5:]
                        info_desc = data[3][13:-1]
                        headers['INFO'].update({info_id : {'type' : info_type, 'description' : info_desc}})
                    else:
                        headers[l[0]].append(l[1])
                elif line.startswith('#'):
                    samples = line[1:].strip().split('\t')[9:]
                else :
                    hcount -= 1
                    break;

        # Check for VEP
        vep_imp = VepImporter()
        if vep_imp.init(headers, reference_id):
            vep = {'vep' : vep_imp}
        else:
            vep = {'vep' : False}
        
        # Check for SnpEff
        snpeff_imp = SnpEffImporter()
        if snpeff_imp.init(headers, reference_id):
            snpeff = {'snpeff' : snpeff_imp}
        else:
            snpeff = {'snpeff' : False }

        ## Check for dbNSFP
        dbnsfp = {'dbnsfp' : False }
        #dbnsfp_fields = [f.replace("dbNSFP_", "", 1) for f in headers['INFO'].keys() if f.startswith("dbNSFP_")]
        #dbnsfp_fields = sorted(dbnsfp_fields)
        #if len(dbnsfp_fields) > 0:
            #dbnsfp = {
                #'dbnsfp' : {
                    #'type' : 'column_annotation', # use this key for standard annotations (one by column in INFO field)
                    #'version' : "", # how to get version dbNSFP used by SnpSift ?
                    #'flag' : '',
                    #'name' : 'dbNSFP',
                    #'prefix' : 'dbNSFP_',
                    #'db_type' : 'variant',
                    #'columns' : dbnsfp_fields,
                    #'description' : "A database for functional prediction and annotation of all potential non-synonymous single-nucleotide variants (nsSNVs) in the human genome.",
                #}
            #}


        # Retrieve extension
        file_type = os.path.split(filename)[1].split('.')[-1]
        if not ('vcf' in file_type or 'gvcf' in file_type) :
            file_type = "{}.{}".format(os.path.split(filename)[1].split('.')[-2], file_type)

        # Return result
        result = {
            'vcf_version' : headers['fileformat'][0],
            'name'  : os.path.split(filename)[1],
            'header_count': hcount,
            'count' : count_vcf_row(filename),
            'size'  : os.path.getsize(filename),
            'type'  : file_type,
            'samples' : samples,
            'annotations' : {}
        }
        result['annotations'].update(vep)
        result['annotations'].update(snpeff)
        result['annotations'].update(dbnsfp)
    except Exception as ex:
        err("Error when parsing vcf headers", exception=ex)
        result=None
    return result





    


def normalise(pos, ref, alt):
    """
        Normalise given (position, ref and alt) from VCF into Database format
            - Assuming that position in VCF are 1-based (0-based in Database)
            - triming ref and alt to get minimal alt (and update position accordingly)
    """
    # input pos comming from VCF are 1-based.
    # to be consistent with UCSC databases we convert it into 0-based
    pos -= 1
    
    if ref is None:
        ref = ''
    if alt is None:
        alt = ''
    # ref/ref special case
    if ref==alt:
        return pos, ref, alt
    # trim left
    while len(ref) > 0 and len(alt) > 0 and ref[0]==alt[0] :
        ref = ref[1:]
        alt = alt[1:]
        pos += 1
    # trim right
    if len(ref) == len(alt):
        while ref[-1:]==alt[-1:]:
            ref = ref[0:-1]
            alt = alt[0:-1]
    return pos, ref, alt








def normalise_annotation_name(name):
    """
        Tool to convert a name of a annotation tool/db/field/version into the corresponding valid name for the database
    """
    if name[0].isdigit():
        name = '_'+name
    def check_char(char):
        if char in ['.', '-', '_', '/']:
            return '_'
        elif char.isalnum():
            # TODO : remove accents
            return char.lower()
        else:
            return ''
    return ''.join(check_char(c) for c in name)


def create_annotation_db(reference_id, reference_name, table_name, vcf_annotation_metadata):
    """
        Create an annotation database according to information retrieved from the VCF file with the prepare_vcf_parsing method
    """
    # Create annotation table
    isTranscript = vcf_annotation_metadata['db_type'] == 'transcript'
    pk = 'regovar_trx_id character varying(100), ' if isTranscript else ''
    pk2 = ',regovar_trx_id' if isTranscript else ''
    pattern = "CREATE TABLE {0} (variant_id bigint, bin integer, chr integer, pos bigint, ref text, alt text, " + pk + "{1}, CONSTRAINT {0}_ukey UNIQUE (variant_id" + pk2 +"));"
    query   = ""
    db_map = {}
    fields = []
    for col in vcf_annotation_metadata['columns']:
        col_name = normalise_annotation_name(col)
        fields.append("{} text".format(col_name))
        db_map[col_name] = { 'name' : col_name, 'type' : 'string', 'name_ui' : col }  # By default, create a table with only text field. Type can be changed by user via a dedicated UI
    
    query += pattern.format(table_name, ', '.join(fields))
    query += "CREATE INDEX {0}_idx_vid ON {0} USING btree (variant_id);".format(table_name)
    query += "CREATE INDEX {0}_idx_var ON {0} USING btree (bin, chr, pos);".format(table_name)
        


    if isTranscript:
        # Register annotation
        db_uid, pk_uid = Model.execute("SELECT MD5('{0}'), MD5(concat(MD5('{0}'), '{1}'))".format(table_name, normalise_annotation_name(vcf_annotation_metadata['db_pk_field']))).first()
    
        query += "CREATE INDEX {0}_idx_tid ON {0} USING btree (regovar_trx_id);".format(table_name)
        query += "INSERT INTO annotation_database (uid, reference_id, name, version, name_ui, description, ord, type, db_pk_field_uid, jointure) VALUES "
        q = "('{0}', {1}, '{2}', '{3}', '{4}', '{5}', {6}, '{7}', '{8}', '{2} {{0}} ON {{0}}.bin={{1}}.bin AND {{0}}.chr={{1}}.chr AND {{0}}.pos={{1}}.pos AND {{0}}.ref={{1}}.ref AND {{0}}.alt={{1}}.alt');"
        query += q.format(
            db_uid, 
            reference_id, 
            table_name, 
            vcf_annotation_metadata['version'], 
            vcf_annotation_metadata['name'], 
            vcf_annotation_metadata['description'], 
            30, 
            vcf_annotation_metadata['db_type'],
            pk_uid)
    else:
        db_uid = Model.execute("SELECT MD5('{0}')".format(table_name)).first()[0]
    
        query += "INSERT INTO annotation_database (uid, reference_id, name, version, name_ui, description, ord, type, jointure) VALUES "
        q = "('{0}', {1}, '{2}', '{3}', '{4}', '{5}', {6}, '{7}', '{2} {{0}} ON {{0}}.bin={{1}}.bin AND {{0}}.chr={{1}}.chr AND {{0}}.pos={{1}}.pos AND {{0}}.ref={{1}}.ref AND {{0}}.alt={{1}}.alt');"
        query += q.format(
            db_uid, 
            reference_id, 
            table_name, 
            vcf_annotation_metadata['version'], 
            vcf_annotation_metadata['name'], 
            vcf_annotation_metadata['description'], 
            30, 
            vcf_annotation_metadata['db_type'])

    query += "INSERT INTO annotation_field (database_uid, ord, name, name_ui, type) VALUES "
    for idx, f in enumerate(vcf_annotation_metadata['columns']):
        query += "('{0}', {1}, '{2}', '{3}', 'string'),".format(db_uid, idx, normalise_annotation_name(f), f)
    Model.execute(query[:-1])
    Model.execute("UPDATE annotation_field SET uid=MD5(concat(database_uid, name)) WHERE uid IS NULL;")
    return db_uid, db_map


def prepare_annotation_db(reference_id, vcf_annotation_metadata):
    """
        Prepare database for import of custom annotation, and set the mapping between VCF info fields and DB schema
    """

    reference  = Model.execute("SELECT table_suffix FROM reference WHERE id={}".format(reference_id)).first()[0]
    table_name = normalise_annotation_name('{}_{}_{}'.format(vcf_annotation_metadata['name'], vcf_annotation_metadata['version'], reference))
    
    # Get database schema (if available)
    table_cols = {}
    db_uid     = Model.execute("SELECT uid FROM annotation_database WHERE name='{}'".format(table_name)).first()

    if db_uid is None:
        # No table in db for these annotation : create new table
        db_uid, table_cols = create_annotation_db(reference_id, reference, table_name, vcf_annotation_metadata)
    else:
        db_uid = db_uid[0]
        # Table already exists : retrieve columns already defined
        for col in Model.execute("SELECT name, name_ui, type FROM annotation_field WHERE database_uid='{}'".format(db_uid)):
            table_cols[col.name] = {'name': col.name, 'type': col.type, 'name_ui': col.name_ui}
    # Get diff between columns in vcf and columns in DB, and update DB schema
    diff = []
    for col in vcf_annotation_metadata['columns']:
        if normalise_annotation_name(col) not in table_cols.keys():
            diff.append(col)
    if len(diff) > 0 :
        offset = len(vcf_annotation_metadata['columns'])
        query = ""
        for idx, col in enumerate(diff):
            name=normalise_annotation_name(col)
            query += "ALTER TABLE {0} ADD COLUMN {1} text; INSERT INTO public.annotation_field (database_uid, ord, name, name_ui, type) VALUES ('{2}', {3}, '{1}', '{4}', 'string');".format(table_name, name, db_uid, offset + idx, col)
            table_cols[name] = {'name': name, 'type': 'string', 'name_ui': col}

        # execute query
        Model.execute(query)
    # Update vcf_annotation_metadata with database mapping
    db_pk_field_uid = Model.execute("SELECT db_pk_field_uid FROM annotation_database WHERE uid='{}'".format(db_uid)).first().db_pk_field_uid
    vcf_annotation_metadata.update({'table': table_name, 'db_uid': db_uid, 'db_pk_field_uid': db_pk_field_uid})
    vcf_annotation_metadata['db_map'] = {}
    for col in vcf_annotation_metadata['columns']:
        vcf_annotation_metadata['db_map'][col] = table_cols[normalise_annotation_name(col)]
    return vcf_annotation_metadata


def normalize_chr(chrm):
    """
        Normalize chromosome number from VCF format into Database format
    """
    chrm = chrm.upper()
    if chrm.startswith("CHROM"):
        chrm = chrm[5:]
    if chrm.startswith("CHRM") and chrm != "CHRM":
        chrm = chrm[4:]
    if chrm.startswith("CHR"):
        chrm = chrm[3:]

    if chrm == "X":
        chrm = 23
    elif chrm == "Y":
        chrm = 24
    elif chrm == "M":
        chrm = 25
    else:
        try:
            chrm = int(chrm)
        except Exception as error:
            # TODO log /report error
            chrm = None
    return chrm



def normalize_gt(infos):
    """
        Normalize GT sample informatin from VCF format into Database format
        -50: err
        -1: None (variant don't have this variant)
         0: ref/ref
         1: alt/alt
         2: ref/alt
         3: alt1/alt2
    """
    gt = get_info(infos, "GT")
    if gt != "NULL":
        if len(infos["GT"]) == 0:
            log ("WARNING GT empty: " + str(infos["GT"]) )
            return -50
        elif len(infos["GT"]) == 1:
            # Happens on chrX in males (hemizygous) and in females when they are homozygous
            # TODO: manage hemizygous in Regovar
            # FIXME: considered for now as homozygous
            return "1"
        elif infos["GT"][0] == infos["GT"][1]:
            # Homozyous ref
            if infos["GT"][0] in [None, 0] : 
                return 0
            # Homozygous alt
            return "1"
        else :
            if 0 in infos["GT"] :
                # Heterozygous ref
                return "2"
            else :
                return "3"
    log ("WARNING GT error: " + str(infos["GT"]) )
    return -50


def get_alt(alt):
    """
        Retrieve alternative values from VCF data
    """
    if ("|" in alt):
        return alt.split("|")
    else:
        return alt.split("/")


def get_info(infos, key):
    """
        Retrieving info annotation from VCF data
    """
    if (key in infos):
        if infos[key] is None : return "NULL"
        return infos[key]
    return "NULL"

def sqlc(data, default="NULL"):
    if data:
        return data
    return default



def is_transition(ref, alt):
    """
        Return true if the variant is a transversion; false otherwise
    """
    tr = ref+alt
    if len(ref) == 1 and tr in ("AG", "GA", "CT", "TC"):
        return True
    return False



def escape_value_for_sql(value):
    if type(value) is str:
        value = value.replace(':', ': ') # As :X is a interpreted as a variable by sqlalchemy
        value = value.replace("'", "''") 
    return value





# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Tiers code from vtools.  Bin index calculation 
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #


#
# Utility function to calculate bins.
#
# This function implements a hashing scheme that UCSC uses (developed by Jim Kent) to 
# take in a genomic coordinate range and return a set of genomic "bins" that your range
# intersects.  I found a Java implementation on-line (I need to find the URL) and I
# simply manually converted the Java code into Python code.  
    
# IMPORTANT: Because this is UCSC code the start coordinates are 0-based and the end 
# coordinates are 1-based!!!!!!
        
# BINRANGE_MAXEND_512M = 512 * 1024 * 1024
# binOffsetOldToExtended = 4681; #  (4096 + 512 + 64 + 8 + 1 + 0)

_BINOFFSETS = (
    512+64+8+1,   # = 585, min val for level 0 bins (128kb binsize)    
    64+8+1,       # =  73, min val for level 1 bins (1Mb binsize) 
    8+1,          # =   9, min val for level 2 bins (8Mb binsize)  
    1,            # =   1, min val for level 3 bins (64Mb binsize)  
    0)            # =   0, only val for level 4 bin (512Mb binsize)
        
#    1:   0000 0000 0000 0001    1<<0       
#    8:   0000 0000 0000 1000    1<<3
#   64:   0000 0000 0100 0000    1<<6
#  512:   0000 0010 0000 0000    1<<9
    
_BINFIRSTSHIFT = 17;            # How much to shift to get to finest bin.
_BINNEXTSHIFT = 3;              # How much to shift to get to next larger bin.
_BINLEVELS = len(_BINOFFSETS)
    
#
# IMPORTANT: the start coordinate is 0-based and the end coordinate is 1-based.
#
def getUcscBins(start, end):
    bins = []
    startBin = start >> _BINFIRSTSHIFT
    endBin = (end-1) >> _BINFIRSTSHIFT
    for i in range(_BINLEVELS):
        offset = _BINOFFSETS[i];
        if startBin == endBin:
            bins.append(startBin + offset)
        else:
            for bin in range(startBin + offset, endBin + offset):
                bins.append(bin);
        startBin >>= _BINNEXTSHIFT
        endBin >>= _BINNEXTSHIFT
    return bins

def getMaxUcscBin(start, end):
    bin = 0
    startBin = start >> _BINFIRSTSHIFT
    endBin = (end-1) >> _BINFIRSTSHIFT
    for i in range(_BINLEVELS):
        offset = _BINOFFSETS[i];
        if startBin == endBin:
            if startBin + offset > bin:
                bin = startBin + offset
        else:
            for i in range(startBin + offset, endBin + offset):
                if i > bin:
                    bin = i 
        startBin >>= _BINNEXTSHIFT
        endBin >>= _BINNEXTSHIFT
    return bin









# =======================================================================================================
# Import manager
# =======================================================================================================

# from queue import Queue
# from threading import Thread





# # define bw worker
# def vcf_import_worker(queue, file_id, samples):
#     while True:
#         query = queue.get()
#         if query is None:
#             break
        
#         Model.execute(query)
#         queue.task_done()
        
        




            
            
class VcfManager(AbstractImportManager):
    metadata = {
        "name" : "VCF",
        "input" :  ["vcf", "vcf.gz"],
        "description" : "Import variants from vcf file"
    }


    def import_delegate(self, file_id, vcf_reader, reference_id, db_ref_suffix, vcf_metadata, samples):
        """
            This delegate will do the "real" import.
            It will be called by the "import_data" method in a new thread in order to don't block the main thread
        """
        from core.core import core
        # parsing vcf file
        records_count = vcf_metadata['count']
        records_current = 0
        vcf_line = vcf_metadata['header_count']
        table = "variant" + db_ref_suffix
        
        sql_pattern1 = "INSERT INTO {0} (chr, pos, ref, alt, is_transition, bin, sample_list) VALUES ({1}, {2}, '{3}', '{4}', {5}, {6}, array[{7}]) ON CONFLICT (chr, pos, ref, alt) DO UPDATE SET sample_list=array_intersect({0}.sample_list, array[{7}])  WHERE {0}.chr={1} AND {0}.pos={2} AND {0}.ref='{3}' AND {0}.alt='{4}';"
        sql_pattern2 = "INSERT INTO sample_variant" + db_ref_suffix + " (sample_id, variant_id, vcf_line, bin, chr, pos, ref, alt, genotype, depth, depth_alt, quality, filter) SELECT {0}, id, {1}, {2}, '{3}', {4}, '{5}', '{6}', {7}, {8}, {9}, {10}, '{11}' FROM variant" + db_ref_suffix + " WHERE bin={2} AND chr={3} AND pos={4} AND ref='{5}' AND alt='{6}' ON CONFLICT (sample_id, variant_id) DO NOTHING;"
        
        sql_annot_trx = "INSERT INTO {0} (variant_id, bin,chr,pos,ref,alt, regovar_trx_id, {1}) SELECT id, {3},{4},{5},'{6}','{7}', '{8}', {2} FROM variant" + db_ref_suffix + " WHERE bin={3} AND chr={4} AND pos={5} AND ref='{6}' AND alt='{7}' ON CONFLICT (variant_id, regovar_trx_id) DO  NOTHING; " # TODO : do update on conflict
        sql_annot_var = "INSERT INTO {0} (variant_id, bin,chr,pos,ref,alt, {1}) SELECT id, {3},{4},{5},'{6}','{7}', {2} FROM variant" + db_ref_suffix + " WHERE bin={3} AND chr={4} AND pos={5} AND ref='{6}' AND alt='{7}' ON CONFLICT (variant_id) DO  NOTHING;"

        sql_query1 = ""
        sql_query2 = ""
        sql_query3 = ""
        count = 0
        
        for row in vcf_reader: 
            records_current += 1 
            vcf_line += 1
            #log("> {} : {}".format(records_current, count))
            #if records_current == 14356:
                #ipdb.set_trace()
                    
            # TODO : update sample's progress indicator
            
            
            chrm = normalize_chr(str(row.chrom))
            
            for allele in row.alleles:
                pos, ref, alt = normalise(row.pos, row.ref, allele)
                bin = getMaxUcscBin(pos, pos + len(ref))
                
                # get list of sample that have this variant (chr-pos-ref-alt)
                samples_array = []
                for sn, sp in row.samples.items():
                    if allele in sp.alleles:
                        samples_array.append(samples[sp.name]["id"])
                if len(samples_array) == 0: continue
                # save variant
                samples_array = ",".join([str(s) for s in samples_array])
                sql_query1 += sql_pattern1.format(table, chrm, pos, ref, alt, is_transition(ref, alt), bin, samples_array)
                        
                # Register variant/sample associations
                for sn, sp in row.samples.items():
                    gt = normalize_gt(sp)
                    filters = escape_value_for_sql(json.dumps(row.filter.keys()))
                    count += 1
                    if allele in sp.alleles:
                        if "AD" in sp.keys():
                            # Get allelic depth if exists (AD field)
                            depth_alt = sp["AD"][sp.alleles.index(allele)] 
                        elif "DP4" in sp.keys():
                            if gt == 0:
                                depth_alt = sum(sp["DP4"])
                            else:
                                depth_alt = sp["DP4"][2] + sp["DP4"][3] if alt != ref else sp["DP4"][0] + sp["DP4"][1]
                        else :
                            depth_alt = "NULL"
                        
                        sql_query2 += sql_pattern2.format(samples[sn]["id"], vcf_line, bin, chrm, pos, ref, alt, gt, get_info(sp, "DP"), sqlc(depth_alt), sqlc(row.qual), filters)
                    else:
                        # save that the sample HAVE NOT this variant
                        sql_query2 += sql_pattern2.format(samples[sn]["id"], vcf_line, bin, chrm, pos, ref, alt, "NULL", get_info(sp, "DP"), "NULL", sqlc(row.qual), filters)
                
                # Register variant annotations
                for ann_name, importer in vcf_metadata["annotations"].items():
                    if importer:
                        importer_query, importer_count = importer.import_annotations(sql_annot_trx, bin, chrm, pos, ref, alt, row.info)
                        sql_query3 += importer_query
                        count += importer_count
                        
                            


            # split big request to avoid sql out of memory transaction or too long freeze of the server
            if count >= 1000:
                progress = records_current / records_count
                count = 0
                transaction = "BEGIN; " + sql_query1 + sql_query2 + sql_query3 + "COMMIT; "
                log("VCF import : line {} (chrm {})".format(records_current, chrm))
                log("VCF import : Execute sync query {}/{} ({}%)".format(records_current, records_count, round(progress * 100, 2)))
                
                    
                # update sample's progress indicator
                # note : as we are updating lot of data in the database with several asynch thread
                #        so to avoid conflict with session, we update data from "manual query"
                sps = []
                sql = "UPDATE sample SET loading_progress={} WHERE id IN ({})".format(progress, ",".join([str(samples[sid]["id"]) for sid in samples]))
                Model.execute(sql)
                core.notify_all({"action": "import_vcf_processing", "data" : {"reference_id": reference_id, "file_id" : file_id, "status" : "loading", "progress": progress, "samples": [ {"id" : samples[sname]["id"], "name" : sname} for sname in samples]}})
                
                #log("VCF import : enqueue query")
                #self.queue.put(transaction)
                log("VCF import : execute query")
                Model.execute(transaction)
                # Reset query buffers
                sql_query1 = ""
                sql_query2 = ""
                sql_query3 = ""

        # # Loop done, execute last pending query 
        # log("VCF import : Execute last async query")
        # transaction = sql_query1 + sql_query2 + sql_query3
        # if transaction:
        #     self.queue.put(transaction)


        # # Waiting that all query in the queue was executed
        # log("VCF parsing done. Waiting for async execution of sql queries")
        
        # # block until all tasks are done
        # self.queue.join()
        # log("No more sql query to proceed")
        
        # # stop vcf_import_thread_workers
        # for i in range(VCF_IMPORT_MAX_THREAD):
        #     self.queue.put(None)
        # for t in self.workers:
        #     t.join()

        # Compute composite variant by sample
        sql_pattern = "UPDATE sample_variant" + db_ref_suffix + " u SET is_composite=TRUE WHERE u.sample_id = {0} AND u.variant_id IN (SELECT DISTINCT UNNEST(sub.vids) as variant_id FROM (SELECT array_agg(v.variant_id) as vids, g.name2 FROM sample_variant" + db_ref_suffix + " v INNER JOIN refgene" + db_ref_suffix + " g ON g.chr=v.chr AND g.trxrange @> v.pos WHERE v.sample_id={0} AND v.genotype=2 or v.genotype=3 GROUP BY name2 HAVING count(*) > 1) AS sub)"
        log("Computing is_composite fields by samples :")
        # for sid in samples:
        #     query = sql_pattern.format(samples[sid]["id"])
        #     log(" - sample {}".format(samples[sid]["id"]))
        #     Model.execute(query)
        log("Sample import from VCF Done")
        end = datetime.datetime.now()
        
        # update sample's progress indicator
        Model.execute("UPDATE sample SET status='ready', loading_progress=1  WHERE id IN ({})".format(",".join([str(samples[sid]["id"]) for sid in samples])))
        
        core.notify_all({"action": "import_vcf_end", "data" : {"reference_id": reference_id, "file_id" : file_id, "msg" : "Import done without error.", "samples": [ {"id" : samples[s]["id"], "name" : samples[s]["name"]} for s in samples.keys()]}})


        # When import is done, check if analysis are waiting for creation and then start wt creation if all sample are ready 
        # TODO
        sql = "SELECT DISTINCT(analysis_id) FROM analysis_sample WHERE sample_id IN ({})".format(",".join([str(samples[sid]["id"]) for sid in samples]))
        for row in Model.execute(sql):
            analysis = Model.Analysis.from_id(row.analysis_id,1)
            if analysis.status == "waiting":
                log("Auto initialisation of the analysis in witing state : {} ({})".format(analysis.name, analysis.id))
                core.filters.request(analysis.id, analysis.filter, analysis.fields)





    async def import_data(self, file_id, **kargs):
        """
            Import samples, variants and annotations from the provided file.
            This method check provided parameters and parse the header of the vcf to get samples and compute the number of line
            that need to be parse to allow us to compute a progress indicator. The parsing is done in delegate called in another thread.
            Return the list of sample that have been added.
        """
        from core.core import core
        file = Model.File.from_id(file_id)
        filepath = file.path
        reference_id = kargs["reference_id"]
        start_0 = datetime.datetime.now()
        job_in_progress = []

        
        vcf_metadata = prepare_vcf_parsing(reference_id, filepath)
        db_ref_suffix= "_" + Model.execute("SELECT table_suffix FROM reference WHERE id={}".format(reference_id)).first().table_suffix

        if vcf_metadata:
            filepath += ".regovar_import" # a tmp file have been created by prepare_vcf_parsing() method to avoid pysam unsupported file format.
            start = datetime.datetime.now()
            
            # Create vcf parser
            vcf_reader = VariantFile(filepath)

            # get samples in the VCF 
            # samples = {i : Model.get_or_create(Model.Session(), Model.Sample, name=i)[0] for i in list((vcf_reader.header.samples))}
            samples = {}
            for i in vcf_reader.header.samples:
                sample = Model.Sample.new()
                sample.name = i
                sample.file_id = file_id
                sample.reference_id = reference_id
                sample.filter_description = {filter[0]:filter[1].description for filter in vcf_reader.header.filters.items()}
                sample.default_dbuid = []
                sample.status = "loading"
                for dbname in vcf_metadata["annotations"].keys():
                    if vcf_metadata["annotations"][dbname]:
                        sample.default_dbuid.append(vcf_metadata["annotations"][dbname].db_uid)
                # TODO : is_mosaic according to the data in the vcf
                sample.save()
                
                # As these sample will be shared with other threads, we remove them from the sql session to avoid error
                samples.update({i : sample.to_json()})
                
            if len(samples.keys()) == 0 : 
                war("VCF files without sample cannot be imported in the database.")
                await core.notify_all_co({"action": "import_vcf_error", "data" : {"reference_id": reference_id, "file_id" : file_id, "msg" : "VCF files without sample cannot be imported in the database."}})
                return;


            # # tasks queue shared by all thread
            # self.queue = Queue(maxsize=0)
            # # list of worker created to execute multithread tasks
            # self.workers = []
            
            # # init threading workers
            # for i in range(VCF_IMPORT_MAX_THREAD):
            #     t = Thread(target=vcf_import_worker, args=(self.queue, file_id, samples), daemon=True)
            #     t.start()
            #     self.workers.append(t)


            await core.notify_all_co({"action":"import_vcf_start", "data" : {"reference_id": reference_id, "file_id" : file_id, "samples" : [ {"id" : samples[sid]["id"], "name" : samples[sid]["name"]} for sid in samples.keys()]}})
            records_count = vcf_metadata["count"]
            log ("Importing file {0}\n\r\trecords  : {1}\n\r\tsamples  :  ({2}) {3}\n\r\tstart    : {4}".format(filepath, records_count, len(samples.keys()), reprlib.repr([sid for sid in samples.keys()]), start))
            
            run_async(self.import_delegate, file_id, vcf_reader, reference_id, db_ref_suffix, vcf_metadata, samples)
        
            return {"success": True, "samples": samples, "records_count": records_count }
        return {"success": False, "error": "File not supported"}

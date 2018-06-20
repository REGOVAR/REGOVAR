 #!env/python3
# coding: utf-8
try:
    import ipdb
except ImportError:
    pass


import os
import shutil
import json
import tarfile
import datetime
import time
import uuid
import subprocess
import requests



from config import *
from core.framework.common import *
from core.framework.postgresql import execute
from core.model import *




# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 
# Job MANAGER
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 
class JobManager:
    def __init__(self):
        pass


    def list(self):
        """
            List all jobs with minimal data
        """
        sql = "SELECT id, pipeline_id, project_id, name, comment, create_date, update_date, status, progress_value, progress_label FROM job ORDER BY id"
        result = []
        for res in execute(sql): 
            result.append({
                "id": res.id,
                "pipeline_id": res.pipeline_id,
                "project_id": res.project_id,
                "name": res.name,
                "comment": res.comment,
                "status": res.status,
                "progress_value": res.progress_value,
                "progress_label": res.progress_label,
                "create_date": res.create_date.isoformat(),
                "update_date": res.update_date.isoformat()
            })
        return result

    def get(self, fields=None, query=None, order=None, offset=None, limit=None, depth=0):
        """
            Generic method to get jobs according provided filtering options
        """
        if not isinstance(fields, dict):
            fields = None
        if query is None:
            query = {}
        if order is None:
            order = "name"
        if offset is None:
            offset = 0
        if limit is None:
            limit = RANGE_MAX
        jobs = Session().query(Job).filter_by(**query).order_by(order).limit(limit).offset(offset).all()
        for j in jobs: j.init(depth)
        return jobs



    def new(self, pipeline_id:int, name:str, config:dict, inputs_ids=[], asynch=False, auto_notify=True):
        """
            Create a new job for the specified pipepline (pipeline_id), with provided config and input's files ids
        """
        pipeline = Pipeline.from_id(pipeline_id)
        if not pipeline : 
            raise RegovarException("Pipeline not found (id={}).".format(pipeline_id))
        if pipeline.status != "ready":
            raise RegovarException("Pipeline status ({}) is not \"ready\". Cannot create a job.".format(pipeline.status))
        if not name:
            raise RegovarException("A name must be provided to create new job")
        # Init model
        job = Job.new()
        job.status = "initializing"
        job.name = name
        job.config = config
        job.progress_value = 0
        job.pipeline_id = pipeline_id
        job.progress_label = "0%"
        for fid in inputs_ids: JobFile.new(job.id, int(fid), True)
        job.save()
        # TODO : check if enough free resources to start the new job. otherwise, set status to waiting and return
        job.init(1, True)
        # Init directories entries for the container
        job.path = os.path.join(JOBS_DIR, DOCKER_CONFIG["job_name"].format("{}_{}".format(job.pipeline_id, job.id)))
        job.save()
        inputs_path = os.path.join(job.path, "inputs")
        outputs_path = os.path.join(job.path, "outputs")
        logs_path = os.path.join(job.path, "logs")
        if not os.path.exists(inputs_path): 
            os.makedirs(inputs_path)
        if not os.path.exists(outputs_path):
            os.makedirs(outputs_path)
            os.chmod(outputs_path, 0o777)
        if not os.path.exists(logs_path):
            os.makedirs(logs_path)
            os.chmod(logs_path, 0o777)
        
        # Set job's config in the inputs directory of the job
        config_path = os.path.join(inputs_path, "config.json")
        job_config = {
            "pirus" : {"notify_url" : NOTIFY_URL.format(job.id), "job_name" : job.name},
            "job" : config
        }

        # TODO: adding admin security to know if db connection is allowed for this job
        job_config["pirus"]["db_host"] = DATABASE_HOST
        job_config["pirus"]["db_port"] = DATABASE_PORT
        job_config["pirus"]["db_user"] = DATABASE_USER
        job_config["pirus"]["db_name"] = DATABASE_NAME
        job_config["pirus"]["db_pwd"] = DATABASE_PWD

        with open(config_path, 'w') as f:
            f.write(json.dumps(job_config, sort_keys=True, indent=4))
            os.chmod(config_path, 0o777)

        # Check that all inputs files are ready to be used
        for f in job.inputs:
            if f is None :
                print("new job.inputs none")
                self.set_status(job, "error")
                raise RegovarException("Inputs file deleted before the start of the job {} (id={}). Job aborded.".format(job.name, job.id))
            if f.status not in ["checked", "uploaded"]:
                # inputs not ready, we keep the run in the waiting status
                war("INPUTS of the run not ready. waiting")
                self.set_status(job, "waiting")
                return Job.from_id(job.id)
        for f in job.inputs:
            # copy all file in the f folder (because some file may have attached files like index bam.bai for bam files)
            file_directory = os.path.dirname(f.path)
            for fname in os.listdir(file_directory) :
                file_path = os.path.join(file_directory, fname)
                link_path = os.path.join(inputs_path, fname)
                os.link(file_path, link_path)
                os.chmod(link_path, 0o644)

        # Call init of the container
        if asynch: 
            run_async(self.__init_job, job.id, auto_notify)
        else:
            self.__init_job(job.id, auto_notify)

        # Return job object (refresh)
        return Job.from_id(job.id)



    def start(self, job_id, asynch=False):
        """
            Start or restart the job
        """
        job = Job.from_id(job_id)
        if not job:
            raise RegovarException("Job not found (id={}).".format(job_id))
        # If job is still initializing
        if job.status == "initializing":
            if asynch: 
                run_async(self.__init_job, job.id, True)
                return True
            else:
                return self.__init_job(job.id, True)

        if job.status not in ["waiting", "pause"]:
            raise RegovarException("Job status ({}) is not \"pause\" or \"waiting\". Cannot start the job.".format(job.status))
        # Call start of the container
        if asynch: 
            run_async(self.__start_job, job.id)
            return True
        else:
            return self.__start_job(job.id)



    def monitoring(self, job_id):
        """
            Return a Job object with a new attribute 'monitoring'
            monitoring = json with container monitoring informations; false otherwise when monitoring is not possible
        """
        from core.core import core
        job = Job.from_id(job_id, 1)
        if not job:
            raise RegovarException("Job not found (id={}).".format(job_id))
        if job.status == "initializing":
            war("Job {} status is \"initializing\". Cannot retrieve yet monitoring informations.".format(job.id))
            job.monitoring = False
        else:
            # Ask container manager to update data about container
            try:
                job.monitoring = core.container_manager.monitoring_job(job)
            except Exception as ex:
                err("Error occured when retrieving monitoring information for the job {} (id={})".format(os.path.basename(job.path), job.id), ex)
        return job



    def pause(self, job_id, asynch=False):
        """
            Pause the job
            Return False if job cannot be pause; True otherwise
        """
        from core.core import core

        job = Job.from_id(job_id, 1)
        if not job:
            raise RegovarException("Job not found (id={}).".format(job_id))
        if not job.pipeline:
            raise RegovarException("No Pipeline associated to this job.")
        if not job.pipeline.type:
            raise RegovarException("Type of pipeline for this job is not set.")
        if not core.container_manager.supported_features["pause_job"]:
            return False
        # Call pause of the container
        if asynch: 
            run_async(self.__pause_job, job.id)
            return True
        else:
            return self.__pause_job(job.id)




    def stop(self, job_id, asynch=False):
        """
            Stop the job
        """
        job = Job.from_id(job_id)
        if not job:
            raise RegovarException("Job not found (id={}).".format(job_id))
        if job.status in ["error", "canceled", "done"]:
            raise RegovarException("Job status is \"{}\". Cannot stop the job.".format(job.status))
        # Call stop of the container
        if asynch: 
            run_async(self.__stop_job, job.id)
            return True
        else:
            return self.__stop_job(job.id)



    def finalize(self, job_id, asynch=False):
        """
            Shall be called by the job itself when ending.
            save outputs files and ask the container manager to delete container
        """
        from core.core import core
        job = Job.from_id(job_id)
        if not job:
            raise RegovarException("Job not found (id={}).".format(job_id))
        if job.status in ["canceled", "done", "error"]:
            raise RegovarException("Job status is \"{}\". Cannot be finalized.".format(job.status))
        # Register outputs files
        outputs_path = os.path.join(job.path, "outputs")
        logs_path = os.path.join(job.path, "logs")
        for f in os.listdir(outputs_path):
            file_path = os.path.join(outputs_path, f)
            if os.path.isfile(file_path):
                # 1- register outputs file as into DB
                pf = core.files.from_job(file_path, job_id)
                # 2- update job's entry in db to link file to job's outputs
                JobFile.new(job_id, pf.id)
        # Stop container and delete it
        if asynch: 
            run_async(self.__finalize_job, job.id)
            return True
        else:
            return self.__finalize_job(job.id)



    def delete(self, job_id, asynch=False):
        """
            Delete a Job. Outputs that have not yet been saved in Pirus, will be deleted.
        """
        job = Job.from_id(job_id, 1)
        if not job:
            raise RegovarException("Job not found (id={}).".format(job_id))
        # Security, force call stop/delete the container
        if asynch: 
            run_async(self.__finalize_job, job.id)
        else:
            self.__finalize_job(job.id)
        # Deleting file in the filesystem
        shutil.rmtree(job.path, True)
        return job




    def set_status(self, job, new_status, notify=True, asynch=False):
        from core.core import core
        # Avoid useless notification
        # Impossible to change state of a job in error or canceled
        if job.status == new_status or job.status in  ["error", "canceled"]:
            return
        # Update status
        job.status = new_status
        job.save()
        
        # Need to do something according to the new status ?
        # Nothing to do for status : "waiting", "initializing", "running", "finalizing"
        if job.status in ["pause", "error", "done", "canceled"]:
            next_jobs = Session().query(Job).filter_by(status="waiting").order_by("priority").all()
            if len(next_jobs) > 0:
                if asynch: 
                    run_async(self.start, next_jobs[0].id)
                else:
                    self.start(next_jobs[0].id)
        elif job.status == "finalizing":
            if asynch: 
                run_async(self.finalize, job.id)
            else:
                self.finalize(job.id)
        # Push notification
        if notify:
            if new_status == "done":
                # Force reload to get generated outputs
                job.init(1, True)
                core.notify_all({"action": "job_updated", "data" : job.to_json(["id", "update_date", "status", "progress_value", "progress_label", "logs", "outputs"])})
            else:
                core.notify_all({"action": "job_updated", "data" : job.to_json(["id", "update_date", "status", "progress_value", "progress_label", "logs"])})


    def __init_job(self, job_id, auto_notify):
        """
            Call manager to prepare the container for the job.
        """
        from core.core import core
        job = Job.from_id(job_id, 1)
        if job and job.status == "initializing":
            try:
                success = core.container_manager.init_job(job, auto_notify)
            except Exception as ex:
                raise RegovarException("Error when trying to init the job.", exception=ex)
                print("__init_job")
                self.set_status(job, "error")
                return False
            print("__init_job : " + "running" if success else "error")
            self.set_status(job, "running" if success else "error") 
            return True
        err("Job initializing already done or failled. Not able to reinitialise it.")
        return False



    def __start_job(self, job_id):
        """
            Call the container manager to start or restart the execution of the job.
        """
        from core.core import core

        # Check that job exists
        job = Job.from_id(job_id, 1)
        if not job :
            # TODO : log error
            return False

        # Ok, job is now waiting
        self.set_status(job, "waiting")

        # Check that all inputs files are ready to be used
        for file in job.inputs:
            if file is None :
                err("Inputs file deleted before the start of the job {} (id={}). Job aborded.".format(job.name, job.id))
                self.set_status(job, "error")
                return False
            if file.status not in ["checked", "uploaded"]:
                # inputs not ready, we keep the run in the waiting status
                war("INPUTS of the run not ready. waiting")
                self.set_status(job, "waiting")
                return False

        # TODO : check that enough reszources to run the job
        # Inputs files ready to use, looking for lxd resources now
        # count = 0
        # for lxd_container in lxd_client.containers.all():
        #     if lxd_container.name.startswith(LXD_CONTAINER_PREFIX) and lxd_container.status == 'Running':
        #         count += 1
        # count = len(Run.objects(status="RUNNING")) + len(Run.objects(status="INITIALIZING")) + len(Run.objects(status="FINISHING"))
        # if len(Run.objects(status="RUNNING")) >= LXD_MAX:
        #     # too many run in progress, we keep the run in the waiting status
        #     print("To many run in progress, we keep the run in the waiting status")
        #     return 1

        #Try to run the job
        if core.container_manager.start_job(job):
            self.set_status(job, "running")
            return True
        return False





    def __pause_job(self, job_id):
        """
            Call manager to suspend the execution of the job.
        """
        from core.core import core

        job = Job.from_id(job_id, 1)
        if job:
            try:
                core.container_manager.pause_job(job)
            except Exception as ex:
                # TODO : Log error
                print("__pause_job")
                self.set_status(job, "error")
                return False
            self.set_status(job, "pause")
            return True
        return False


    def __stop_job(self, job_id):
        """
            Call manager to stop execution of the job.
        """
        from core.core import core

        job = Job.from_id(job_id, 1)
        if job:
            try:
                core.container_manager.stop_job(job)
            except Exception as ex:
                # Log error
                print("__stop_job")
                self.set_status(job, "error")
                return False
            self.set_status(job, "canceled")
            return True
        return False



    def __finalize_job(self, job_id):
        """
            Ask the manager to clear the container
        """
        from core.core import core
        
        job = Job.from_id(job_id, 1)
        if not job :
            # TODO : log error
            return 

        if core.container_manager.finalize_job(job):
            self.set_status(job, "done")
            return True
        else:
            print("__finalize_job")
            self.set_status(job, "error")
            return False
        return False

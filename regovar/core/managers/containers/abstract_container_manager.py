#!env/python3
# coding: utf-8


# =====================================================================================================================
# Container Manager Abstracts
# =====================================================================================================================

class AbstractContainerManager():
    """
        This abstract method shall be overrided by all pirus managers.
        Pirus managers clain to manage virtualisation of job with a specific technologie.
        Pirus managers implementations are in the core/managers/ directory
    """
    def __init__(self):
        # Job's control features supported by this bind of pipeline
        self.supported_features = {
            "pause_job" : False,
            "stop_job" : False,
            "monitoring_job" : False
        }

    def install_pipeline(self, pipeline):
        """
            IMPLEMENTATION REQUIRED
            Install the pipeline image according to the dedicated technology (LXD, Docker, Biobox, ...)
            Return True if success; False otherwise
        """
        raise NotImplementedError("The abstract method \"install_pipeline\" of PirusManager must be implemented.")


    def uninstall_pipeline(self, pipeline):
        """
            IMPLEMENTATION REQUIRED
            Uninstall the pipeline image according to the dedicated technology (LXD, Docker, Biobox, ...)
            Note that Database and filesystem clean is done by the core. 

            Return True if success; False otherwise
        """
        raise NotImplementedError("The abstract method \"uninstall_pipeline\" of PirusManager must be implemented.")



    def init_job(self, job, auto_notify=True):
        """
            IMPLEMENTATION REQUIRED
            Init a job by checking its settings (stored in database) and preparing the container for this job.
              auto_notify : tell the container to send 2 notifications :
                            the first one before starting to update status to "running"
                            the last one at the end of the job to update status to "finalizing"
                            if set to false, you will have to monitore yourself the execution of the job
                            to finalize it when its done.
            Return void. Must raise exception in case of error
        """
        raise NotImplementedError("The abstract method \"init_job\" of PirusManager must be implemented.")


    def start_job(self, job):
        """
            IMPLEMENTATION REQUIRED
            Start the job into the container. The container may already exists as this method can be call
            after init_job and pause_job.
            Return True if success; False otherwise
        """
        raise NotImplementedError("The abstract method \"start_job\" of PirusManager must be implemented.")


    def pause_job(self, job):
        """
            IMPLEMENTATION OPTIONAL
            Pause the execution of the job to save server resources by example
            Return True if success; False otherwise
        """
        if self.supported_features["pause_job"]:
            raise RegovarException("The abstract method \"pause_job\" of PirusManager shall be implemented.")


    def stop_job(self, job):
        """
            IMPLEMENTATION OPTIONAL
            Stop the job. The job is canceled and the container shall be destroyed
            Return True if success; False otherwise
        """
        if self.supported_features["stop_job"]:
            raise RegovarException("The abstract method \"stop_job\" of PirusManager shall be implemented.")


    def list_jobs(self, job):
        """
            IMPLEMENTATION OPTIONAL 
            Return list of all job (running or paused)
        """
        if self.supported_features["monitoring_job"]:
            raise RegovarException("The abstract method \"monitoring_job\" of PirusManager shall be implemented.")


    def monitoring_job(self, job):
        """
            IMPLEMENTATION OPTIONAL
            Provide monitoring information about the container (CPU/RAM used, update logs files if needed, etc)
            Return monitoring information as json; None otherwise
        """
        if self.supported_features["monitoring_job"]:
            raise RegovarException("The abstract method \"monitoring_job\" of PirusManager shall be implemented.")


    def finalize_job(self, job):
        """
            IMPLEMENTATION REQUIRED
            Clean temp resources created by the container (log shall be kept)
            Return True if success; False otherwise
        """
        raise NotImplementedError("The abstract method \"terminate_job\" of PirusManager must be implemented.")



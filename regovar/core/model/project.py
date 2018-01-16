#!env/python3
# coding: utf-8
import os
import json


from core.framework.common import *
from core.framework.postgresql import *





def project_init(self, loading_depth=0, force=False):
    """
        Init properties of a project :
            - id            : int           : the unique id of the project in the database
            - name          : str           : the name of the project
            - comment       : str           : an optional comment
            - parent_id     : int           : null or refer to another project which is a folder that contains this project
            - is_folder     : bool          : True if it's a folder, False if it's a project
            - update_date   : date          : The last time that the object have been updated
            - jobs_ids      : [int]         : The list of ids of jobs that contains the project
            - analyses_ids  : [int]         : The list of ids of analyses that contains the project
            - subjects_ids  : [int]         : The list of ids of subjets associated to the project
            - is_sandbox    : bool          : True if the project is the sandbox of an user; False otherwise
        If loading_depth is > 0, Following properties fill be loaded : (Max depth level is 2)
            - jobs          : [Job]         : The list of Job owns by the project
            - analyses      : [Analysis]    : The list of Analysis owns by the project
            - subjects      : [Subject]     : The list of Subjects linked to this project
            - parent        : Project       : The parent Project if defined
    """
    # Avoid recursion infinit loop
    if hasattr(self, "loading_depth") and not force:
        return
    else:
        self.loading_depth = min(2, loading_depth)
    try:
        self.subjects_ids = self.get_subjects_ids()
        self.jobs_ids = [j.id for j in self.get_jobs()]
        self.analyses_ids = [a.id for a in self.get_analyses()]

        self.jobs = []
        self.analyses = []
        self.subjects = []
        self.parent = None
        if self.loading_depth > 0:
            self.parent = Project.from_id(self.parent_id, self.loading_depth-1)
            self.jobs = self.get_jobs(self.loading_depth-1)
            self.analyses = self.get_analyses(self.loading_depth-1)
            self.subjects = self.get_subjects(self.loading_depth-1)
    except Exception as ex:
        raise RegovarException("Project data corrupted (id={}).".format(self.id), "", ex)


def project_from_id(project_id, loading_depth=0):
    """
        Retrieve project with the provided id in the database
    """
    project = Session().query(Project).filter_by(id=project_id).first()
    if project:
        project.init(loading_depth)
    return project


def project_from_ids(project_ids, loading_depth=0):
    """
        Retrieve projects corresponding to the list of provided id
    """
    projects = []
    if project_ids and len(project_ids) > 0:
        projects = Session().query(Project).filter(Project.id.in_(project_ids)).all()
        for f in projects:
            f.init(loading_depth)
    return projects


def project_to_json(self, fields=None, loading_depth=-1):
    """
        Export the project into json format with only requested fields
    """
    result = {}
    if loading_depth < 0:
        loading_depth = self.loading_depth
    if fields is None:
        fields = Project.public_fields
    for f in fields:
        if f in Project.public_fields:
            if f in ["create_date", "update_date"] :
                result.update({f: eval("self." + f + ".isoformat()")})
            elif f in ["jobs", "analyses", "subjects"]:
                if hasattr(self, f) and len(eval("self." + f)) > 0 and loading_depth > 0:
                    result[f] = [o.to_json(None, loading_depth-1) for o in eval("self." + f)]
                else :                           
                    result[f] = []
            elif f in ["parent"] and self.loading_depth > 0 and self.parent:
                result[f] = self.parent.to_json(None, loading_depth-1)
            else:
                result.update({f: eval("self." + f)})
    return result



def project_load(self, data):
    """
        Helper to update project's data by loading a json.
        Note that following properties cannot be set by this ways :
            - id / is_sandbox (which MUST not be changed. this property is managfed by regovar's Model itself)
            - update_date / create_date (which are managed automaticaly by the server)
            - subjects_ids / subjects (which are too complex to be set directly. 
              Need to use UserSubjectSharing objects to update these associations)
    """
    try:
        # Required fields
        if "name" in data.keys(): self.name = check_string(data['name'])
        if "comment" in data.keys(): self.comment = check_string(data['comment'])
        if "parent_id" in data.keys(): self.parent_id = check_int(data['parent_id'])
        if "is_folder" in data.keys(): self.is_folder = check_bool(data['is_folder'], False)
        self.save()
        
        # Update user sharing
        if "users" in data.keys():
            # Delete all associations
            Session().query(UserProjectSharing).filter_by(project_id=self.id).delete(synchronize_session=False)
            # Create new associations
            self.users = data["users"]
            for u in data["users"]:
                if isinstance(u, dict) and "id" in u.keys() and "write_authorisation" in u.keys():
                    UserProjectSharing.set(self.id, u["id"], u["write_authorisation"])
                else:
                    err("")
    
        
        # TODO : update 

        # Reload dynamics properties
        self.init(self.loading_depth, True)
    except KeyError as e:
        raise RegovarException('Invalid input project: missing ' + e.args[0])
    return self


def project_save(self):
    generic_save(self)


def project_delete(project_id):
    """
        Delete the project with the provided id in the database
    """
    Session().query(UserProjectSharing).filter_by(project_id=project_id).delete(synchronize_session=False)
    Session().query(ProjectSubject).filter_by(project_id=project_id).delete(synchronize_session=False)
    Session().query(Project).filter_by(id=project_id).delete(synchronize_session=False)
    # TODO : delete analyses and job linked to the project ? that means also deleting outputs files of these jobs


def project_new():
    """
        Create a new project and init/synchronise it with the database
    """
    p = Project()
    p.save()
    p.init()
    return p


def project_count(count_folder=False, count_sandbox=False):
    """
        Return total of Job entries in database
    """
    kargs = {}
    if not count_folder: kargs["is_folder"] = False
    if not count_sandbox: kargs["is_sandbox"] = False
    return Session().query(Project).filter_by(**kargs).count()



def projects_get_jobs(self, loading_depth=0):
    """
        Return the list of jobs linked to the project
    """
    from core.model.job import Job
    jobs = Session().query(Job).filter_by(project_id=self.id).all()
    for j in jobs: j.init(loading_depth)
    return jobs




def projects_get_analyses(self, loading_depth=0):
    """
        Return the list of analyses linked to the project
    """
    from core.model.analysis import Analysis
    analyses = Session().query(Analysis).filter_by(project_id=self.id).all()
    for a in analyses : a.init(loading_depth)
    return analyses





def projects_get_subjects_ids(self):
    sql  = "SELECT distinct(t3.id) FROM subject t3 INNER JOIN sample t2 ON t3.id=t2.subject_id "
    sql += "INNER JOIN analysis_sample t1 ON t2.id=t1.sample_id INNER JOIN analysis t0 ON t1.analysis_id=t0.id "
    sql += "WHERE t0.project_id={}"
    return [r.id for r in execute(sql.format(self.id))]
    


def projects_get_subjects(self, loading_depth=0):
    """
        Return the list of subjects linked to the project
    """
    from core.model.subject import Subject
    return Subject.from_ids(self.get_subjects_ids(), loading_depth)








Project = Base.classes.project
Project.public_fields = ["id", "name", "comment", "parent_id", "parent", "is_folder", "create_date", "update_date", "jobs_ids", "analyses_ids", "subjects_ids", "jobs", "analyses", "subjects", "is_sandbox"]
Project.init = project_init
Project.from_id = project_from_id
Project.from_ids = project_from_ids
Project.to_json = project_to_json
Project.load = project_load
Project.save = project_save
Project.new = project_new
Project.delete = project_delete
Project.count = project_count
Project.get_jobs = projects_get_jobs
Project.get_analyses = projects_get_analyses
Project.get_subjects = projects_get_subjects
Project.get_subjects_ids = projects_get_subjects_ids
















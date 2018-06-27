#!env/python3
# coding: utf-8

import aiohttp_jinja2
import jinja2
import base64

from aiohttp import web
from aiohttp_session import setup as setup_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from aiohttp_security import setup as setup_security
from aiohttp_security import SessionIdentityPolicy

from config import *
from api_rest.policy import RegovarAuthorizationPolicy
from api_rest.rest import *
from api_rest.handlers import *


# Handlers instances
apiHandler = ApiHandler()
webHandler = WebHandler()
userHandler = UserHandler()
projHandler = ProjectHandler()
subjectHandler = SubjectHandler()
eventHandler = EventHandler()
websocket = WebsocketHandler()

fileHdl = FileHandler()
jobHdl = JobHandler()
pipeHdl = PipelineHandler()
dbHdl = DatabaseHandler()

annotationHandler = AnnotationDBHandler()
analysisHandler = AnalysisHandler()
sampleHandler = SampleHandler()
phenoHandler = PhenotypeHandler()
searchHandler = SearchHandler()
panelHandler = PanelHandler()
adminHandler = AdminHandler()


# Create a auth ticket mechanism that expires after SESSION_MAX_DURATION seconds (default is 86400s = 24h), and has a randomly generated secret. 
# Also includes the optional inclusion of the users IP address in the hash
key = base64.b64encode(PRIVATE_KEY32.encode()).decode()


# Create server app
app = web.Application()
setup_session(app, EncryptedCookieStorage(key, max_age=SESSION_MAX_DURATION, cookie_name="regovar_session"))
setup_security(app, SessionIdentityPolicy(session_key='regovar_session_token'), RegovarAuthorizationPolicy())
app['websockets'] = []
aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(TEMPLATE_DIR)) 

# On shutdown, close all websockets
app.on_shutdown.append(on_shutdown)






# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 
# ROUTES
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 
app.router.add_route('GET',    "/welcome", apiHandler.welcome)                                                   # Get "welcome page of the rest API"
app.router.add_route('GET',    "/config",  apiHandler.config)                                                    # Get config of the server
app.router.add_route('GET',    "/api",     apiHandler.api)                                                       # Get html test api page
app.router.add_route('GET',    "/ws",      websocket.get)                                                        # Websocket url to use with ws or wss protocol

app.router.add_route('GET',    "/",                        webHandler.home)
app.router.add_route('GET',    "/w",                       webHandler.home)
app.router.add_route('GET',    "/w/search/{query}",        webHandler.search)
app.router.add_route('GET',    "/w/info/{type}/{id}",      webHandler.info)
app.router.add_route('GET',    "/w/viewer/{id}",           webHandler.viewer)



app.router.add_route('GET',    "/users", userHandler.list)                                                       # Get list of all users (allow search parameters)
app.router.add_route('POST',   "/user", userHandler.new)                                                         # Create new users with provided data
app.router.add_route('POST',   "/user/login", userHandler.login)                                                 # Start user's session if provided credentials are correct
app.router.add_route('GET',    "/user/logout", userHandler.logout)                                               # Kill user's session
app.router.add_route('GET',    "/user/{user_id}", userHandler.get)                                               # Get details about one user
app.router.add_route('PUT',    "/user/{user_id}", userHandler.edit)                                              # Edit user with provided data
app.router.add_route('DELETE', "/user/{user_id}", userHandler.delete)                                            # Delete a user

#app.router.add_route('GET',    "/project/browserTree",           projHandler.tree)                               # Get projects as tree (allow search parameters)
app.router.add_route('GET',    "/projects",                       projHandler.list)                              # Get list of all projects (allow search parameters)
app.router.add_route('POST',   "/project",                       projHandler.create_or_update)                   # Create new project with provided data
app.router.add_route('GET',    "/project/{project_id}",          projHandler.get)                                # Get details about the project
app.router.add_route('PUT',    "/project/{project_id}",          projHandler.create_or_update)                   # Edit project meta data
app.router.add_route('DELETE', "/project/{project_id}",          projHandler.delete)                             # Delete the project
app.router.add_route('GET',    "/project/{project_id}/events",   projHandler.events)                             # Get list of events of the project (allow search parameters)
app.router.add_route('GET',    "/project/{project_id}/subjects", projHandler.subjects)                           # Get list of subjects of the project (allow search parameters)
app.router.add_route('GET',    "/project/{project_id}/analyses", projHandler.analyses)                           # Get list of analyses (pipeline and filtering) of the project (allow search parameters)
app.router.add_route('GET',    "/project/{project_id}/files",    projHandler.files)                              # Get list of files (samples and attachments) of the project (allow search parameters)

app.router.add_route('GET',    "/events",           eventHandler.list)                                           # 100 last events
app.router.add_route('POST',   "/events",           eventHandler.search)                                         # Events list corresponding to provided filters
app.router.add_route('POST',   "/event",            eventHandler.new)                                            # Create a new event
app.router.add_route('GET',    "/event/{event_id}", eventHandler.get)                                            # Get details about an event
app.router.add_route('PUT',    "/event/{event_id}", eventHandler.edit)                                           # Edit event's data
app.router.add_route('DELETE', "/event/{event_id}", eventHandler.delete)                                         # Delete an event

app.router.add_route('GET',    "/subjects",                      subjectHandler.list)                            # Get subjects as list (allow search parameters)
app.router.add_route('POST',   "/subject",                       subjectHandler.create_or_update)                # Create subjects
app.router.add_route('GET',    "/subject/{subject_id}",          subjectHandler.get)                             # Get details about a subject
app.router.add_route('PUT',    "/subject/{subject_id}",          subjectHandler.create_or_update)                # Edit subject's data
app.router.add_route('DELETE', "/subject/{subject_id}",          subjectHandler.delete)                          # Delete a subject
app.router.add_route('GET',    "/project/{project_id}/events",   subjectHandler.events)                          # Get list of events of the project (allow search parameters)
app.router.add_route('GET',    "/project/{project_id}/samples",  subjectHandler.samples)                         # Get list of subjects of the subject (allow search parameters)
app.router.add_route('GET',    "/project/{project_id}/analyses", subjectHandler.samples)                         # Get list of analyses (pipeline and filtering) of the subject (allow search parameters)
app.router.add_route('GET',    "/project/{project_id}/files",    subjectHandler.files)                           # Get list of files of the subject (allow search parameters)

app.router.add_route('GET',    "/files",                 fileHdl.list)                                           # Get list of all file (allow search parameters)
app.router.add_route('GET',    "/file/{file_id}",        fileHdl.get)                                            # Get details about a file
app.router.add_route('PUT',    "/file/{file_id}",        fileHdl.edit)                                           # Edit file's details
app.router.add_route('DELETE', "/file/{file_id}",        fileHdl.delete)                                         # Delete the file
app.router.add_route('POST',   "/file/upload",           fileHdl.tus_upload_init)
app.router.add_route('OPTIONS',"/file/upload",           fileHdl.tus_config)
app.router.add_route('HEAD',   "/file/upload/{file_id}", fileHdl.tus_upload_resume)
app.router.add_route('PATCH',  "/file/upload/{file_id}", fileHdl.tus_upload_chunk)
app.router.add_route('DELETE', "/file/upload/{file_id}", fileHdl.tus_upload_delete)

app.router.add_route('GET',    "/pipelines",                  pipeHdl.list)
app.router.add_route('GET',    "/pipeline/{pipe_id}",         pipeHdl.get)
app.router.add_route('PUT',    "/pipeline/{pipe_id}",         pipeHdl.update)
app.router.add_route('DELETE', "/pipeline/{pipe_id}",         pipeHdl.delete)
app.router.add_route('GET',    "/pipeline/install/{file_id}", pipeHdl.install)

app.router.add_route('GET',    "/jobs",                    jobHdl.list)
app.router.add_route('POST',   "/job",                     jobHdl.new)
app.router.add_route('GET',    "/job/{job_id}",            jobHdl.get)
app.router.add_route('GET',    "/job/{job_id}/pause",      jobHdl.pause)
app.router.add_route('GET',    "/job/{job_id}/start",      jobHdl.start)
app.router.add_route('GET',    "/job/{job_id}/cancel",     jobHdl.cancel)
app.router.add_route('GET',    "/job/{job_id}/monitoring", jobHdl.monitoring)
app.router.add_route('GET',    "/job/{job_id}/finalize",   jobHdl.finalize)

app.router.add_route('GET',    "/db",       dbHdl.get)
app.router.add_route('GET',    "/db/{ref}", dbHdl.get)


app.router.add_route('GET',   "/phenotypes",           phenoHandler.list)
app.router.add_route('POST',   "/phenotypes/search",   phenoHandler.search)
app.router.add_route('GET',    "/phenotype/{hpo_id}",  phenoHandler.get)                # Get all available information about the given phenotype or disease (HPO/OMIM/ORPHA)




app.router.add_route('GET',    "/annotation", annotationHandler.list)                                                # Get list of genom's referencials supported
app.router.add_route('GET',    "/annotation/{ref_id}", annotationHandler.get)                                        # Get list of all annotation's databases and for each the list of availables versions and the list of their fields for the latest version
app.router.add_route('GET',    "/annotation/db/{db_id}", annotationHandler.get_database)                             # Get the database details and the list of all its fields
app.router.add_route('GET',    "/annotation/field/{field_id}", annotationHandler.get_field)                          # Get the database details and the list of all its fields
app.router.add_route('DELETE', "/annotation/db/{db_id}", annotationHandler.delete)                                   # Delete an annotation database with all its fields.

app.router.add_route('GET',    "/samples", sampleHandler.list)                                                       # Get list of all samples in database
app.router.add_route('GET',    "/samples/ref/{ref_id}", sampleHandler.list)                                          # Get list of samples for the requested reference
app.router.add_route('GET',    "/sample/{sample_id}", sampleHandler.get)                                             # Get specific sample's database
app.router.add_route('GET',    "/sample/import/{file_id}/{ref_id}", sampleHandler.import_from_file)                  # import sample's data from the file (vcf supported)
app.router.add_route('PUT',    "/sample/{sample_id}", sampleHandler.update)                                          # Update sample informations

app.router.add_route('GET',    "/analyses",                                      analysisHandler.list)                 # List analyses
app.router.add_route('POST',   "/analysis",                                      analysisHandler.new)                  # Create new analysis
app.router.add_route('GET',    "/analysis/{analysis_id}",                        analysisHandler.get)                  # Get analysis metadata
app.router.add_route('PUT',    "/analysis/{analysis_id}",                        analysisHandler.update)               # Save analysis metadata
app.router.add_route('DELETE', "/analysis/{analysis_id}",                        analysisHandler.delete)               # Delete analysis
app.router.add_route('GET',    "/analysis/{analysis_id}/filter",                 analysisHandler.get_filters)          # Get list of available filter for the provided analysis
app.router.add_route('POST',   "/analysis/{analysis_id}/filter",                 analysisHandler.create_update_filter) # Create a new filter for the analisis
app.router.add_route('PUT',    "/analysis/{analysis_id}/filter/{filter_id}",     analysisHandler.create_update_filter) # Update filter
app.router.add_route('DELETE', "/analysis/{analysis_id}/filter/{filter_id}",     analysisHandler.delete_filter)        # Delete a filter
app.router.add_route('POST',   "/analysis/{analysis_id}/filtering",              analysisHandler.filtering)            # Get result (variants) of the provided filter
app.router.add_route('POST',   "/analysis/{analysis_id}/filtering/{variant_id}", analysisHandler.filtering)            # Get total count of result of the provided filter
app.router.add_route('GET',    "/analysis/{analysis_id}/select/{variant_id}",    analysisHandler.select)               # Select the variant/trx with the provided id
app.router.add_route('GET',    "/analysis/{analysis_id}/unselect/{variant_id}",  analysisHandler.unselect)             # Unselect the variant/trx with the provided id
app.router.add_route('GET',    "/analysis/{analysis_id}/selection",              analysisHandler.get_selection)        # Return list of selected variant (with same columns as set for the current filter)
#app.router.add_route('POST',   "/analysis/{analysis_id}/export/{exporter_name}", analysisHandler.get_export)           # Export selection of the provided analysis into the requested format
#app.router.add_route('POST',   "/analysis/{analysis_id}/report/{report_name}",   analysisHandler.get_report)           # Generate report html for the provided analysis+report id
app.router.add_route('GET',    "/analysis/{analysis_id}/clear_temps_data",       analysisHandler.clear_temps_data)     # Clear temporary data (to save disk space by example)

app.router.add_route('GET',    "/search/{query}",                                     searchHandler.search)          # generic research
app.router.add_route('GET',    "/search/variant/{ref_id}/{variant_id}",               searchHandler.fetch_variant)   # Get all available information about the given variant
app.router.add_route('GET',    "/search/variant/{ref_id}/{variant_id}/{analysis_id}", searchHandler.fetch_variant)   # Get all available information about the given variant + data in the context of the analysis
app.router.add_route('GET',    "/search/gene/{gene_name}",                            searchHandler.fetch_gene)      # Get all available information about the given gene
app.router.add_route('GET',    "/search/phenotype/{hpo_id}",                          phenoHandler.get)              # Get all available information about the given phenotype or disease (HPO/OMIM/ORPHA)


app.router.add_route('GET',    "/panels",                     panelHandler.list)               # Get list of all panels
app.router.add_route('POST',   "/panel",                      panelHandler.create_or_update)   # Create a new panel with provided data
app.router.add_route('GET',    "/panel/{panel_id}",           panelHandler.get)                # Get information about the panel
app.router.add_route('PUT',    "/panel/{panel_id}",           panelHandler.create_or_update)   # Update the panel or panel version
app.router.add_route('DELETE', "/panel/{panel_id}",           panelHandler.delete)             # Delete panel and all its versions or just a version
app.router.add_route('GET',    "/panel/search/{query}",       panelHandler.search)             # Search gene and phenotype that match the query (used to help user to populate panel regions)
app.router.add_route('GET',    "/panel/import/{file_id}",     panelHandler.import_file)        # Import region from a bed file already in database
app.router.add_route('POST',   "/panel/import",               panelHandler.import_file)        # Import a new file store it on regovar server (as bed) and import as a panel



app.router.add_route('GET',    "/admin/stats",                               adminHandler.stats)














# Websockets / realtime notification
app.router.add_route('POST',   "/job/{job_id}/notify", jobHdl.update_status)


# Statics root for direct download
# FIXME - Routes that should be manages directly by NginX
app.router.add_static('/error', TEMPLATE_DIR + "/errors/")
app.router.add_static('/assets', TEMPLATE_DIR)
app.router.add_static('/dl/db/', DATABASES_DIR)
app.router.add_static('/dl/pipe/', PIPELINES_DIR)
app.router.add_static('/dl/file/', FILES_DIR)
app.router.add_static('/dl/job/', JOBS_DIR)



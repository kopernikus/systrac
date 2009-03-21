# -*- coding: utf-8 -*-
# Copyright (c) 2008 Paul Kölle (pkoelle@gmail.com)

import gc
import os, time, re, csv
from pkg_resources import resource_filename
from types import ListType, DictType
from xml.dom import minidom
from datetime import datetime

from genshi.builder import tag
from genshi.core import Markup



from trac.core import *
from trac.util.text import CRLF, unicode_passwd
from trac.util.translation import _
from trac.util.datefmt import to_timestamp, utc
from trac.config import BoolOption, IntOption, ListOption, Option
from trac.perm import IPermissionRequestor
from trac.timeline import ITimelineEventProvider
from trac.web import IRequestHandler, RequestDone, parse_query_string
from trac.web.chrome import Chrome, INavigationContributor, ITemplateProvider, add_ctxtnav, \
    add_link, add_script, add_stylesheet, add_warning, prevnext_nav

import db
from db import sqlite, DictConnection, db_version

try:
    import simplejson
    have_json = True
except ImportError:
    have_json = False

joinpath = os.path.join
#gc.set_debug(gc.DEBUG_LEAK)

srv_types = {
    0:'filesystem',
    1:'directory',
    2:'file',
    3:'process',
    4:'host',
    5:'system'}

class MonitCollector(Component):
    implements(IRequestHandler)

    log_dir = Option('monit', 'log_dir', 'log/monit', '')
    #connection_uri = Option('monit', 'database', 'sqlite:db/monit.db',
    #    """Database connection for monit""")

    def __init__(self, *args, **kwargs):
        conn = self.get_db_cnx()
        cur = conn.cursor()
        try:
            cur.execute("SELECT db_version FROM monit")
            res = cur.fetchone()
            self.log.debug("MonitDB version from db is '%s', current version is '%s'" % (res['db_version'], db_version))
            if res and res.get('db_version', None) != db_version:
                current = res['db_version']
                try:
                    db.upgrade(cur, current, db_version)
                    cur.execute("UPDATE monit SET db_version=?", (db_version,))
                except sqlite.OperationalError, e:
                    self.log.warning("Database upgrade from verion %s to version %s failed (%s)" % (
                                    current, db_version, e))
        except sqlite.OperationalError, e:
            self.log.debug("Error fetching db_version %s" % e)
            #the monit table does not exist, create tables from scratch
            for stmt in db.tables:
                cur.execute(stmt)
            db.upgrade(cur, 1, db_version) #run all upgrades
        conn.commit()
        conn.close()
        
    def get_db_cnx(self):
        """get a connection to the monit db"""
        path = joinpath(self.env.path, 'db/monit.db')
        return sqlite.connect(path, timeout=10000, factory=DictConnection)

    # IPermissionRequestor methods
    def get_permission_actions(self):
        """return defined permissions if any"""
        actions = ['MONIT_POST']
        return actions + [('MONIT_ADMIN', actions)]
        
    # IRequestHandler methods
    def match_request(self, req):
        self.env.log.debug("MONIT: match_request() called")
        match = re.match('/collector(.*)', req.path_info)
        if match:
            self.log.debug("MONIT collector request matched: %s" % match.group())
            return True

    def process_request(self, req):
        self.log.info("Got post request from monit instance: %s" % req.remote_addr)
        if req.method == 'POST':
            #self.log.debug("POST HANDLER dir(req) %s" % dir(req))

            ct = req.get_header('Content-Type')
            self.log.debug("content-type is: %s" % ct)
            if ct == 'application/json':
                self._handle_json(req)
            elif ct == 'text/xml':
                self._handle_xml(req)
            else:
                self_handle_text(req)
                
        return 'monit.html', {}, 'text/html'

    def _handle_xml(self, req):
        doc = minidom.parse(req) #req is file-like enough (has a .read())
        id = doc.getElementsByTagName('id')[0].childNodes[0].nodeValue

        # id is in $HOME/.monit.id and will be (re)generated if missing
        # watch out if you're syncing $HOMEs
        savepath = joinpath(self.log_dir, id)
        if not os.path.isdir(savepath):
            self.log.debug("MONIT collector: creating %s from id: %s and log: %s" % (savepath, id, self.log_dir))
            os.mkdir(savepath)
        fp = open(joinpath(savepath, str(int(time.time())) + '.xml'), 'w')
        fp.write(doc.toxml()); fp.close()

        #self.log.debug("POST HANDLER got data from %s for %s: %s" % (req.remote_addr, id, doc.toxml()))
        req.send('', content_type='text/plain', status=201)

    def _handle_json(self, req):
        # parse a JSON request

        if not have_json:
            self.log.warning("The simplejson module is missing. Cannot parse JSON")
            req.send('', content_type='text/plain', status=200)

        try:
            raw = req.read()
            raw = raw.replace('\n', '') #strip linebreaks
            data = simplejson.loads(raw)
        except ValueError, e:
            ct = req.get_header('Content-Type') or 'text/plain'
            self.log.warning("Failed to parse data from %s" % req.remote_addr)
            self._invalid_data(ct, raw)
            req.send('', content_type='text/plain', status=200)
        
        # store data
        conn = self.get_db_cnx()
        cur = conn.cursor()
        
        #sanitize the 'monit' section
        raw = data.get('monit', {}).get('server', {})
        client_info = dict([(k,v) for k,v in raw.items()
                            if type(v) not in [ListType, DictType]])
        client_info.update(dict([('platform_'+k,v) \
                            for k,v in raw.get('platform', {}).items()]))
        client_info.update(raw.get('httpd', {}))
        client_info['monitid'] = client_info['id']; del client_info['id']
        
        #get the id of the monit instance we're operating on and save it for the service processing
        self.log.debug("query DB for monit client entry with id: %s" % client_info['monitid'])
        cur.execute("SELECT id from monit WHERE monitid =?", (client_info['monitid'],))
        res = cur.fetchone()
        
        if not res:
            self.log.debug("Inserting into monit table: id %s with values %s" % (
                            client_info['monitid'], str(client_info)))
                            
            cur.dict_insert('monit', client_info)
            self.monit_id = cur.lastrowid
        else:
            self.log.debug("Updating monit entry with id %s" % client_info['monitid'])
            cur.dict_update('monit', client_info, {'monitid':client_info['monitid']})
            self.monit_id = res['id']
            
        conn.commit()
        #write data for inspection
        #fp = open('/home/pkoelle/trac012dev/tracenv/log/'+str(time.time())+'.json', 'w')
        #fp.write(simplejson.dumps(data, indent=2))
        #fp.close()
        

        #check for service reports 
        for s in data.get('servicelist', []):
            s_type =  s.get('type', None)
            if s_type != None and s_type in range(6):
                self._process_services(conn, s_type, s)
            else:
                self.log.warning("Unknown service type %s from client %s (%s)" % (
                                    str(s_type), req.remote_addr, str(s)))
        
        #events need to come after services as they are linked to a service
        evt = data.get('event', {})
        if evt:
            table = srv_types[evt['type']]+'_service'
            self.log.debug("Updating event table with %s" % str(evt))
            cur.execute("SELECT id from %s WHERE name=?" % table, (evt['service'],))
            res = cur.fetchone()
               
            if not res:
                self.log.warning("No service with name %s found during event processing (%s)"  % (
                                    evt['service'], evt['message']))
            else:
                evt['service_id'] = res.get('id'); del evt['service']
                evt['groupname'] = evt['group']; del evt['group']
                del evt['collected_usec'] #who cares
                del evt['id']
                cur.dict_insert('event', evt)
            
            conn.commit()
        conn.close()
            
        req.send('', content_type='text/plain', status=201)

    def _process_services(self, conn, service_type, service_data):
        """@param service_type, integer, lookup table is srv_types
           @param service_data, dictionary"""
           
        #don't handle unmonitored services for now
        if not service_data.get('monitor', None):
            return
            
        srv_name = srv_types[service_type]
        table = "%s_service" % srv_name
        cur = conn.cursor()
        
        values = dict([(k,v) for k,v in service_data.items()
                            if type(v) not in [ListType, DictType]])
        del values['collected_usec'] #useless...
        values['monit_id'] = self.monit_id
        values['groupname'] = values['group']; del values['group'] # group is a sql kw
        
        self.log.debug("Updating service table for service type '%s' with %s" % (srv_name, str(service_data)))
        #ugly...
        if srv_name == 'system':
            values.update(dict([('load_'+k,v) for k,v in \
                            service_data['system']['load'].items()]))
            values.update(dict([('cpu_'+k, v) for k,v in \
                            service_data['system']['cpu'].items()]))
            values.update(dict([('memory_'+k, v) for k,v in \
                            service_data['system']['memory'].items()]))
            cur.dict_insert(table, values)
            
        elif srv_name == 'host':
            portlist = service_data.get('portlist', [])
            icmplist = service_data.get('icmplist', [])

            cur.dict_insert(table, values)
            host_id = cur.lastrowid
            for e in portlist:
                e['host_id'] = host_id
                cur.dict_insert('host_port', e)
            for e in icmplist:
                e['host_id'] = host_id
                cur.dict_insert('host_icmp', e)
                
        elif srv_name == 'process':
            values.update(dict([('cpu_'+k, v) for k,v in \
                            service_data['cpu'].items()]))
            values.update(dict([('memory_'+k, v) for k,v in \
                            service_data['memory'].items()]))
            cur.dict_insert(table, values)
            
        elif srv_name == 'filesystem':
            values.update(dict([('block_'+k,v) for k,v in \
                            service_data['block'].items()]))
            if service_data.get('inode', None): # sometimes missing 
                values.update(dict([('inode_'+k,v) for k,v in \
                            service_data['inode'].items()]))
            cur.dict_insert(table, values)
            
        else: # file and directory
            cur.dict_insert(table, values)
 
        conn.commit()
        
    def _handle_text(self, req):
        """we don't parse text/plain for now"""
        req.send('', type='text/plain', status=301)

    def _invalid_data(self, contenttype, raw):
        suffix = contenttype.split('/')[-1]
        self.log.warning("The data will be saved in %s/invalid for review." % self.log_dir )
        if not os.path.isdir(joinpath(self.log_dir, 'invalid')):
            os.mkdir(joinpath(self.log_dir, 'invalid'))
        fp = open(joinpath(self.log_dir, 'invalid', str(int(time.time()))+'.'+suffix ), 'w')
        fp.write(raw); fp.close()


        
class MonitViewer(Component):
    implements(INavigationContributor, IRequestHandler,
        ITemplateProvider, ITimelineEventProvider, IPermissionRequestor)

    rc_file = Option('monit', 'rc_file', '/etc/monitrc',
        """monit configuration.""")

    def get_db_cnx(self):
        """get a connection to the monit db"""
        path = joinpath(self.env.path, 'db/monit.db')
        return sqlite.connect(path, timeout=10000, factory=DictConnection)


    # ITimelineEventProvider methods
    def get_timeline_filters(self, req):
        if 'MONIT_VIEW' in req.perm:
            yield ('monit', _('Monit events'))
           
    def get_timeline_events(self, req, start, stop, filters):
        conn = self.get_db_cnx()
        if 'monit' in filters:
            #monit_realm = Resource('monit')
            cur = conn.cursor()
            cur.execute("SELECT * FROM event WHERE collected_sec>=? AND collected_sec<=?",
                           (to_timestamp(start), to_timestamp(stop)))
            for e in cur:
                yield ('monit', datetime.fromtimestamp(e['collected_sec'], utc), 
                        'monit', e)
        conn.close()
        # FIXME there is no way to get the correspondign service entry
        # as the service table is not known (add a service_type column 
        # to the event table AND a type column to all service tables)  
                         
    def render_timeline_event(self, context, field, event):
        return tag(tag.em(event[3]['message']))
        
    # IPermissionRequestor methods
    def get_permission_actions(self):
        """return defined permissions if any"""
        actions = ['MONIT_VIEW']
        return actions + [('MONIT_ADMIN', actions)]


    # ITemplateProvider methods
    def get_htdocs_dirs(self):
        return []
        #yield 'monitoring', resource_filename(__file__, 'htdocs')

    def get_templates_dirs(self):
        return [resource_filename(__name__, 'templates')]
        
#    def get_templates_dirs(self):
#        yield resource_filename(__file__, 'templates')
        
    # INavigationContributor methods
    def get_active_navigation_item(self, req):
        if 'MONIT_VIEW' in req.perm:
            return 'monit'

    def get_navigation_items(self, req):
        if 'MONIT_VIEW' in req.perm:
            yield ('mainnav', 'monit',
                tag.a(_('Monit viewer'), href=req.href.monit(),
                        accesskey=7))

    # IRequestHandler methods
    def match_request(self, req):
        self.env.log.debug("MONIT: match_request() called")
        if 'MONIT_VIEW' in req.perm:
            match = re.match('/monit(.*)', req.path_info)
            if match:
                self.log.debug("MONIT: request matched:%s" % match.group())
                return True
        return False

    def process_request(self, req):
        self.log.debug("MONIT: process_request, args: %s, path_info: %s" % (req.args, req.path_info))
        if 'MONIT_VIEW' in req.perm:
            parts = [p for p in req.path_info.split('/') if p]
            req.send(str(parts), content_type='text/plain')
    

    

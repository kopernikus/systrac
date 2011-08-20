# -*- coding: utf-8 -*-
# Copyright (c) 2008 Paul Kölle (pkoelle@gmail.com)

import os, time, re
import csv, shutil

from datetime import datetime
from pkg_resources import resource_filename
from StringIO import StringIO
from subprocess import Popen, PIPE

from trac.core import *
from trac.timeline.api import ITimelineEventProvider
from trac.perm import IPermissionRequestor
from trac.config import BoolOption, Option, IntOption, ListOption
from trac.mimeview.api import Mimeview, IContentConverter, Context
from trac.web import parse_query_string, IRequestHandler, RequestDone
from trac.web.chrome import add_link, add_script, add_stylesheet, \
        add_warning, add_ctxtnav, prevnext_nav, Chrome, \
        INavigationContributor, ITemplateProvider
from trac.util.translation import _
from trac.util.text import CRLF
from genshi.core import Markup
from genshi.builder import tag

joinpath = os.path.join

class MuninStatsViewer(Component):
    implements(INavigationContributor, IRequestHandler,
               ITemplateProvider, IPermissionRequestor) #IContentConverter,

    rrd_path = Option('munin', 'rrd_path', '/var/lib/munin',
            """default path for rrd files.""")
    
    # IPermissionRequestor methods
    def get_permission_actions(self):
        """return defined permissions if any"""
        actions = ['MUNIN_VIEW', 'MUNIN_SAVE']
        return actions + [('MUNIN_ADMIN', actions)]

    # ITemplateProvider methods
    def get_htdocs_dirs(self):
        return []
        #yield 'monitoring', resource_filename(__file__, 'htdocs')

    def get_templates_dirs(self):
        #use global templates dir for testing
        #yield resource_filename(__file__, 'templates')
        return [resource_filename(__name__, 'templates')]
        
    # INavigationContributor methods
    def get_active_navigation_item(self, req):
        return 'munin'
            
    def get_navigation_items(self, req):
        yield ('mainnav', 'munin',
                tag.a(_('Munin Stats'), href=req.href.munin(),
                accesskey=7))

    # IRequestHandler methods
    def match_request(self, req):
        self.env.log.debug("MUNIN: match_request() called")
        match = re.match('/munin(.*)', req.path_info)
        if match:
            self.log.debug("MUNIN: request matched:%s" % match.group()) 
            parts = match.group().split('/')
            return True


    def process_request(self, req):
        self.log.debug("MUNIN: process_request, args: %s" % req.args) 
        self.log.debug("MUNIN: process_request, path_info: %s" % req.path_info)

        parts = [p for p in req.path_info.split('/') if p]
        self.log.debug("MUNIN: parts %s" % parts)

        if len(parts) > 2 and parts[1] == 'objects':
            self._send_objects(req, parts[2:])
        elif len(parts) > 2 and parts[1] == 'values':
            self._send_values(req, parts[2:])
        
        raw = self.get_available_stats()
        data = {
                'domains': [d for d in raw.keys() if d != 'version'],
                'hosts': [], 'cat': [],
                 }
        return 'munin.html', data, 'text/html'

    def _send_objects(self, req, params):
        if len(params) == 1:
            self._send_hostnames(req, params[0])
        elif len(params) == 2:
            self._send_categories(req, params[0], params[1])
        elif len(params) == 3:
            self._send_cat_details(req, params[0], params[1], params[2])
        
    def _send_hostnames(self, req, domain):
        raw = self.get_available_stats()
        d = raw.get(domain, None)
        if d:
            res = d.keys()
        else: res = []
        res.insert(0, '<host>')
        self._send_response(req, str(res), 'application/json')

    def _send_categories(self, req, domain, host):
        raw = self.get_available_stats()
        res = []
        try:
            entries = raw[domain][host]
            for e in entries:
                if 'cat' in e:
                    res.append(e['cat'])
            res = list(set(res))
            res.sort()
        except KeyError:
            pass
        res.insert(0, '<category>')
        self._send_response(req, str(res), 'application/json')
        
    def _send_cat_details(self, req, dom, node, cat):
        raw = self.get_available_stats()
        entries = raw[dom][node]
        res = []
        for e in entries:
            if 'cat' in e and e['cat'] == cat:
                res.append({e['label']:e['value']})
        self._send_response(req, str(res), 'application/json')
    
    def _send_values(self, req, params):
        """get values, for now we're just generate and load images
        through munin"""
        raw = self.get_available_stats()
        domain, host, cat = params
        srvs = ' '.join(['--service '+c for c in cat.split(',')])
        p = Popen('/usr/share/munin/munin-graph --force-root --list-images --nomonth --noyear --host '+host+' '+srvs, shell=True, close_fds=True, stdout=PIPE, stderr=PIPE)
                    
        picdir = joinpath(self.env.path, 'htdocs', 'munin')
        if not os.path.isdir(picdir):
            os.mkdir(picdir)
        pics = [pic.strip() for pic in p.stdout.readlines()]
        self.log.debug("OUTPUT from popen call to munin-graph: %s (stderr: %s" % (pics, p.stderr.read()))
        for pic in pics:
            shutil.copy(pic, picdir)
        pics = [self.env.href()+'/chrome/site/munin/'+os.path.basename(p) for p in pics]
        self._send_response(req, str(pics), 'application/json')
        
    def _send_response(self, req, data, content_type):
        self.log.debug("sending RAW response, request.path_info was: %s" % req.path_info)
        self.log.debug("sending RAW response, content-type: %s, data: %s" % (content_type, data))
        req.send_response(200)
        req.send_header('Content-Type', content_type)
        req.end_headers()
        req.write(data+CRLF)
        raise RequestDone

    def get_available_stats(self):
        try:
            last = self._lastrun
            now = time.time()
            if now - last < 15: # ten seconds
                return self._cached
        except AttributeError:
            pass
        
        data = {}
        fp = open(joinpath(self.rrd_path, 'datafile'))

        data['version'] = fp.readline().split()[1]
        for line in fp.readlines():
            try:
                dom, node = line.split(';', 1)
                node, graph = node.split(':', 1)
            except ValueError:
                self.log.warning("Failed to convert line: %s" % line)
                continue
            if not dom in data.keys():
                data.update({dom:{}})
            try:
                cat, label = graph.split('.', 1)
                label, value = label.split(' ', 1)
                value = value.strip()
            except ValueError:
                self.log.warning("Failed to convert line: %s" % line)
                continue
            if not node in data[dom].keys():
                data[dom].update({node:[]})
            else:
                data[dom][node].append({'cat':cat, 'label':label, 'value':value})

        self._lastrun = time.time()
        self._cached = data
        return data
 

        


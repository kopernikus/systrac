# -*- coding: utf-8 -*-
# 
# Copyright (C) 2006 Edgewall Software
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.org/wiki/TracLicense.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://trac.edgewall.org/log/.
import pkg_resources
import re

from genshi import HTML
from genshi.builder import tag

from trac import __version__ as TRAC_VERSION
from trac.core import *
from trac.perm import PermissionSystem, IPermissionRequestor
from trac.util import get_pkginfo, get_module_path
from trac.util.compat import partial
from trac.util.translation import _
from trac.web import HTTPNotFound, IRequestHandler
from trac.web.chrome import add_script, add_stylesheet, Chrome, \
                            INavigationContributor, ITemplateProvider


class IMonitoringPanelProvider(Interface):
    """Extension point interface for adding panels to the web-based
    administration interface.
    """

    def get_description():
        """return a description describing for the Panel"""
        
    def get_panels(req):
        """Return a list of available panels.
        
        The items returned by this function must be tuples of the form
        `(category, category_label, page, page_label)`.
        """

    def render_panel(req, category, page, path_info):
        """Process a request for a panel.
        
        This function should return a tuple of the form `(template, data)`,
        where `template` is the name of the template to use and `data` is the
        data to be passed to the template.
        """
        
class MonitoringAdminModule(Component):
    """Web administration interface for monitoring"""

    implements(INavigationContributor, IRequestHandler, ITemplateProvider)

    panel_providers = ExtensionPoint(IMonitoringPanelProvider)

    def __init__(self, *args, **kwargs):
        Component.__init__(self, *args, **kwargs)
        self.env.log.debug("MonitoringAdminModule: __init__() called")
        
    # INavigationContributor methods

    def get_active_navigation_item(self, req):
        return 'monitoring'

    def get_navigation_items(self, req):
        # The 'Admin' navigation item is only visible if at least one
        # admin panel is available
        panels, providers = self._get_panels(req)
        if panels:
            yield 'mainnav', 'monitoring', tag.a(_('Monitoring'), href=req.href.monitoring(),
                                            title=_('Monitoring'))

    # IRequestHandler methods

    def match_request(self, req):
        self.env.log.debug("MonitoringAdminModule: match_request() called")
        match = re.match('/monitoring(?:/([^/]+))?(?:/([^/]+))?(?:/(.*)$)?',
                         req.path_info)
        if match:
            req.args['cat_id'] = match.group(1)
            req.args['panel_id'] = match.group(2)
            req.args['path_info'] = match.group(3)
            return True

    def process_request(self, req):
        panels, providers = self._get_panels(req)
        if not panels:
            raise HTTPNotFound(_('No monitoring panels available'))

        panels.sort()
        cat_id = req.args.get('cat_id') or panels[0][0]
        panel_id = req.args.get('panel_id')
        path_info = req.args.get('path_info')
        if not panel_id:
            panel_id = filter(lambda panel: panel[0] == cat_id, panels)[0][2]

        provider = providers.get((cat_id, panel_id), None)
        if not provider:
            raise HTTPNotFound(_('Unknown monitoring panel'))

        if hasattr(provider, 'render_panel'):
            res  = provider.render_panel(req, cat_id, panel_id,
                                                         path_info)
            if len(res) == 2:
              template, data = res
              contenttype = None
            elif len(res) == 3:
              template, data, contenttype = res
              
        data.update({
            'active_cat': cat_id, 'active_panel': panel_id,
            'panel_href': partial(req.href, 'monitoring', cat_id, panel_id),
            'panels': [{
                'category': {'id': panel[0], 'label': panel[1]},
                'panel': {'id': panel[2], 'label': panel[3]}
            } for panel in panels]
        })

        add_stylesheet(req, 'common/css/admin.css')
        return template, data, contenttype

    # ITemplateProvider methods

    def get_htdocs_dirs(self):
        return [pkg_resources.resource_filename(__name__, 'htdocs')]

    def get_templates_dirs(self):
        #FIXME: what's the first value?
        return [pkg_resources.resource_filename(__name__, 'templates')]

    # Internal methods

    def _get_panels(self, req):
        """Return a list of available admin panels."""
        panels = []
        providers = {}

        for provider in self.panel_providers:
            p = list(provider.get_panels(req))
            for panel in p:
                providers[(panel[0], panel[2])] = provider
            panels += p

        return panels, providers


        

        

#!/usr/bin/python
# -*coding:utf-8*-

from setuptools import setup

PACKAGE = 'SystracMonitor'
VERSION = '0.2'

setup(name=PACKAGE,
      author = 'Paul Kölle',
      author_email = 'paul@subsignal.org',
      description = "Use trac as UI for integrating administration tasks",
      license='BSD',
      version=VERSION,
      packages=['monitoring'],
      entry_points={
        'trac.plugins': [
            'monitoring.api = monitoring.api',
            'monitoring.db = monitoring.db',
            'monitoring.munin = monitoring.munin',
            'monitoring.monit = monitoring.monit'
            ]},
      package_data={'monitoring': ['templates/*.html', 'htdocs/*']},
      install_requires= ['simplejson']
      )
  

#!/bin/bash

PLUGINDIR="/home/pkoelle/trac012dev/tracenv/plugins/"
OWNERGROUP="pkoelle:pkoelle"

rm -Rf dist build *.egg-info
python setup_monitoring.py bdist_egg

echo "Deleting plugins..."
rm -f ${PLUGINDIR}/*

echo "Copying plugin to ${PLUGINDIR}..."
cp dist/* ${PLUGINDIR}
chown ${OWNERGROUP} ${PLUGINDIR}/*

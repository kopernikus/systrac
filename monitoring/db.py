# -*- coding: utf-8 -*-
# Copyright (c) 2008 Paul Kölle (pkoelle@gmail.com)

try:
    import pysqlite2.dbapi2 as sqlite
    have_pysqlite = 2
except ImportError:
    try:
        import sqlite3 as sqlite
        have_pysqlite = 2
    except ImportError:
        try:
            import sqlite
            have_pysqlite = 1
        except ImportError:
            have_pysqlite = 0

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

class DictConnection(sqlite.Connection):
    def __init__(self, *args, **kwargs):
        sqlite.Connection.__init__(self, *args, **kwargs)

    def cursor(self):
        return DictCursor(self)

class DictCursor(sqlite.Cursor):
    def __init__(self, *args, **kwargs):
        sqlite.Cursor.__init__(self, *args, **kwargs)
        self.row_factory = lambda cur, row: dict_factory(self, row)
        self.ph = '?' #the placeholder

    def dict_insert(self, table, data):
        rows = data.keys()
        values = tuple(data.values())
        stmnt = "INSERT INTO %(table)s (%(rows)s) VALUES (%(values)s);" % {
                "table" : table,
                "rows"  : ",".join(rows),
                "values": ",".join([self.ph]*len(values))
            }
        self.execute(stmnt, values)

    def dict_update(self, table, data, where):
        values = tuple(data.values()+where.values())
        stmnt = "UPDATE %(table)s SET %(values)s WHERE (%(where)s);" % {
                "table" :table,
                "values":",".join(["%s="% k+self.ph for k in data.keys()]),
                "where" :" AND ".join(["%s=" % k+self.ph for k in where.keys()])
            }
        self.execute(stmnt, values)

    def dict_delete(self, table, where):
        values = tuple(where.values())
        stmnt = "DELETE FROM %(table)s WHERE (%(where)s);" % {
                "table": table,
                "where": " AND ".join(["%s=" % k+self.ph for k in where.keys()])
            }
        self.execute(stmnt, values)

class DbRowCursor(sqlite.Cursor):
    def execute(self, *args, **kwargs):
        sqlite.Cursor.execute(self, *args, **kwargs)
        if self.description:
            self.row_factory = db_row.IMetaRow(self.description)

def upgrade(cursor, from_version, to_version):
    for i in range(from_version, to_version):
        for stmt in updates[i]:
            cursor.execute(stmt)


# increment for schema changes   
db_version = 3

# populate with DDL statements for migrations between 
# versions e.g. from version 0 upwards 0: ["ALTER TABLE foo ...,]"
updates = {
 1: [
    "ALTER TABLE process_service ADD COLUMN type INTEGER", 
    "ALTER TABLE process_service ADD COLUMN status_message VARCHAR(255)",
    "ALTER TABLE system_service ADD COLUMN type INTEGER", 
    "ALTER TABLE filesystem_service ADD COLUMN type INTEGER",
    "ALTER TABLE filesystem_service ADD COLUMN status_message VARCHAR(255)",
    "ALTER TABLE directory_service ADD COLUMN type INTEGER",
    "ALTER TABLE directory_service ADD COLUMN status_message VARCHAR(255)",
    "ALTER TABLE file_service ADD COLUMN type INTEGER",
    "ALTER TABLE file_service ADD COLUMN status_message VARCHAR(255)",
    "ALTER TABLE event ADD COLUMN service_type INTEGER",
    ],
 2: [
    "ALTER TABLE host_service ADD COLUMN type INTEGER",
    "ALTER TABLE host_service ADD COLUMN status_message VARCHAR(255)",
 ],
 }
 
tables = [
"""
CREATE TABLE monit (
    id INTEGER PRIMARY KEY,
    db_version INTEGER DEFAULT 1,
    address VARCHAR(255),
    port INTEGER,
    ssl INTEGER,
    uptime INTEGER,
    incarnation INTEGER,
    version VARCHAR(255),
    localhostname VARCHAR(255) NOT NULL,
    monitid VARCHAR(255) NOT NULL,
    platform_name VARCHAR(255),
    platform_machine VARCHAR(255),
    platform_version VARCHAR(255),
    platform_memory VARCHAR(255),
    platform_release VARCHAR(255),
    platform_cpu INTEGER,
    startdelay INTEGER,
    controlfile VARCHAR(255),
    poll INTEGER );
""",

 """
CREATE TABLE system_service (
    id INTEGER PRIMARY KEY,
    monit_id INTEGER NOT NULL,
    status INTEGER NOT NULL,
    monitormode INTEGER NOT NULL,
    monitor INTEGER NOT NULL,
    collected_sec INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    groupname VARCHAR(255),
    status_message VARCHAR(255),
    pendingaction INTEGER,
    load_avg01 REAL DEFAULT 0,
    load_avg05 REAL DEFAULT 0,
    load_avg15 REAL DEFAULT 0,
    cpu_wait REAL DEFAULT 0,
    cpu_user REAL DEFAULT 0,
    cpu_system REAL DEFAULT 0,
    memory_kilobyte REAL DEFAULT 0,
    memory_percent REAL DEFAULT 0);
""",

"""
CREATE TABLE process_service (
    id INTEGER PRIMARY KEY,
    monit_id INTEGER NOT NULL,
    status INTEGER NOT NULL,
    monitormode INTEGER NOT NULL,
    monitor INTEGER NOT NULL,
    collected_sec INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    groupname VARCHAR(255),
    pendingaction INTEGER,
    uptime INTEGER,
    pid INTEGER NOT NULL,
    ppid INTEGER,
    children INTEGER,
    cpu_percent REAL,
    cpu_percenttotal REAL,
    memory_kilobyte REAL,
    memory_kilobytetotal REAL,
    memory_percent REAL,
    memory_percenttotal REAL);
""",

"""
CREATE TABLE directory_service (
    id INTEGER PRIMARY KEY,
    monit_id INTEGER NOT NULL,
    status INTEGER NOT NULL,
    monitormode INTEGER NOT NULL,
    monitor INTEGER NOT NULL,
    collected_sec INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    groupname VARCHAR(255),
    pendingaction INTEGER,
    timestamp INTEGER,
    mode INTEGER,
    gid INTEGER,
    uid INTEGER);
""",

"""
 CREATE TABLE file_service (
    id INTEGER PRIMARY KEY,
    monit_id INTEGER NOT NULL,
    status INTEGER NOT NULL,
    monitormode INTEGER NOT NULL,
    monitor INTEGER NOT NULL,
    collected_sec INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    groupname VARCHAR(255),
    pendingaction INTEGER,
    timestamp INTEGER,
    size INTEGER,
    mode INTEGER,
    gid INTEGER,
    uid INTEGER);
""",

"""
CREATE TABLE filesystem_service (
    id INTEGER PRIMARY KEY,
    monit_id INTEGER NOT NULL,
    status INTEGER NOT NULL,
    monitormode INTEGER NOT NULL,
    monitor INTEGER NOT NULL,
    collected_sec INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    groupname VARCHAR(255),
    pendingaction INTEGER,
    mode INTEGER,
    gid INTEGER,
    uid INTEGER,
    flags INTEGER,
    block_percent REAL NOT NULL,
    block_usage REAL NOT NULL,
    block_total REAL NOT NULL,
    inode_percent REAL,
    inode_usage REAL,
    inode_total REAL
);
""",

"""
CREATE TABLE host_service (
    id INTEGER PRIMARY KEY,
    monit_id INTEGER NOT NULL,
    status INTEGER NOT NULL,
    monitormode INTEGER NOT NULL,
    monitor INTEGER NOT NULL,
    collected_sec INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    groupname VARCHAR(255),
    pendingaction INTEGER
);
""",

 """
CREATE TABLE host_icmp (
    id INTEGER PRIMARY KEY,
    host_id INTEGER NOT NULL,
    type VARCHAR(255),
    responsetime REAL
);
""",

"""
CREATE TABLE host_port (
    id INTEGER PRIMARY KEY,
    host_id INTEGER NOT NULL,
    type VARCHAR(255),
    responsetime REAL,
    portnumber INTEGER,
    request VARCHAR(255),
    hostname VARCHAR(255),
    protocol VARCHAR(255)
);
""",

"""
CREATE TABLE event (
    id INTEGER PRIMARY KEY,
    service_id INTEGER NOT NULL,
    type INTEGER NOT NULL,
    collected_sec INTEGER NOT NULL,
    state INTEGER,
    action INTEGER,
    message VARCHAR(255) NOT NULL,
    groupname VARCHAR(255)
);
"""]


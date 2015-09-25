# coding: utf-8
"""
This is where the SQL Server adapter for Lightning lives.
"""

from __future__ import absolute_import

from lightning.datastore.base import DatastoreBase
from lightning.utils import get_uuid, flatten

from lightning.model.authorization import Authz
from lightning.model.granular_data import GranularData
from lightning.model.inflight_authorization import InflightAuthz
from lightning.model.stream_cache import StreamCache
from lightning.model.user_data import UserData
from lightning.model.view import View

from twisted.enterprise import adbapi
from twisted.internet import defer
from twistar.registry import Registry

import json
import logging
import pprint
import pyodbc
import time

# Note(ray): This can be used to debug twistar SQL statements
# from twistar.dbconfig.base import InteractionBase
# InteractionBase.LOG = True

class DatastoreSQL(DatastoreBase):
    """
    This is the implementation of DatastoreBase for MS SQL Server 2008.
    """
    def __init__(self, connection, *args, **kwargs):
        super(DatastoreSQL, self).__init__(*args, **kwargs)
        # Store the config for later use
        self.config = {
            'connection': connection,
        }

    @classmethod
    def connect(cls, connection, *args, **kwargs):
        "This is how we instantiate a DatastoreSQL object with connection"
        obj = cls(connection, *args, **kwargs)

        Registry.DBPOOL = adbapi.ConnectionPool(
            'pyodbc',
            obj.config['connection'],
            autocommit=True,
            cp_reconnect=True
        )
        obj.raw_db = Registry.DBPOOL  # Accessible if we need *really* low-level access to DB.
        obj.db = Registry.getConfig()

        return obj

    def disconnect(self):
        "This is how we disconnect"
        return Registry.DBPOOL.close()

    def status(self):
        "This is how we know we're still connected and good."
        def handle_response(r):
            try:
                one = r[0][0]
                if str(one) == '1':
                    return 'ok'
                return 'error'
            except:
                return 'error'

        return self.raw_db.runQuery('SELECT 1').addCallback(handle_response)

    def args_to_where(self, without=[], **kwargs):
        """Convert kwargs to where args for twistar"""
        where = list()
        where_args = list()
        for key, value in kwargs.iteritems():
            if value and key not in without:
                where.append("%s = ?" % (key))
                where_args.append(value)
        where = ' AND '.join(where)
        ret = [where]
        for arg in where_args:
            ret.append(arg)
        return ret

    @defer.inlineCallbacks
    def get_oauth_token(self, **kwargs):
        """
        Retrieve an authorization given a set of possible parameters:
        * UUID - can be a list or a single UUID

        If UUID is not passed in, then client_name and service_name must be
        provided. user_id can also be passed in. This will be used to get a list
        of UUIDs.

        Then, once a list of UUIDs is generated, then the client_name and/or
        service_name (if either is provided) will be used to winnow the list
        down.
        """
        # We might get a UUID or a client_name/service_name/user_id tuple.
        uuid = kwargs.get('uuid')
        if not uuid:
            assert kwargs.get('client_name') != None
            assert kwargs.get('service_name') != None

            authz = yield Authz.find(where=self.args_to_where(**kwargs), limit=1)
            if not authz:
                defer.returnValue(dict())
            else:
                uuid = authz.uuid

        if type(uuid) == list:
            authz = yield defer.gatherResults([
                Authz.find(where=['uuid = ?', this], limit=1) for this in uuid
            ])

            authz = [this for this in authz if this]

            if kwargs.get('client_name'):
                authz = [
                    this for this in authz
                    if this.client_name == kwargs['client_name']
                ]
            if kwargs.get('service_name'):
                if type(kwargs['service_name']) != list:
                    kwargs['service_name'] = [kwargs['service_name']]
                authz = [
                    this for this in authz
                    if this.service_name in kwargs['service_name']
                ]
        else:
            authz = yield Authz.find(where=['uuid = ?', uuid], limit=1)
            if not authz:
                defer.returnValue(None)
            if kwargs.get('client_name'):
                if kwargs['client_name'] != authz.client_name:
                    authz = None
            if kwargs.get('service_name'):
                if kwargs['service_name'] != authz.service_name:
                    authz = None

        defer.returnValue(authz)

    @defer.inlineCallbacks
    def set_oauth_token(self, **auth_args):
        """Creates or updates an authorization
        Args:
            auth_args: dict, contains the properties of the authorization to set
        Returns:
            tuple containing uuid and boolean indicating authorization newness
        """
        assert auth_args.get('client_name') is not None
        assert auth_args.get('service_name') is not None
        assert auth_args.get('user_id') is not None
        # 1) Do we have a UUID for this tuple?
        authz = yield Authz.find(
            where=self.args_to_where(
                client_name=auth_args['client_name'],
                service_name=auth_args['service_name'],
                user_id=auth_args['user_id'],
            ),
            limit=1,
        )
        # 2) If not, create a UUID and write it.
        if not authz:
            uuid = get_uuid()
            authz = yield Authz(
                client_name=auth_args.get('client_name', None),
                expired_on_timestamp=auth_args.get('expired_on_timestamp', None),
                redirect_uri=auth_args.get('redirect_uri', None),
                refresh_token=auth_args.get('refresh_token', None),
                secret=auth_args.get('secret', None),
                service_name=auth_args.get('service_name', None),
                state=auth_args.get('state', None),
                token=auth_args.get('token', None),
                user_id=auth_args.get('user_id', None),
                uuid=uuid,
            ).save()

            # Sometimes Twistar doesn't return the created row's id after a call
            # to save(). In that case, hit the DB and grab the object.
            if not authz.id:
                authz = yield Authz.find(
                    where=self.args_to_where(
                        uuid=uuid,
                    ),
                    limit=1
                )

            authz.is_new = True
        else:
            uuid = authz.uuid
            authz.is_new = False
            attrs = {}
            if auth_args.get('token') and auth_args['token'] != authz.token:
                attrs['token'] = auth_args['token']
            if auth_args.get('secret') and auth_args['secret'] != authz.secret:
                attrs['secret'] = auth_args['secret']
            if len(attrs):
                authz.updateAttrs(attrs)
                authz = yield authz.save()

        defer.returnValue(authz)

    @defer.inlineCallbacks
    def expire_oauth_token(self, **kwargs):
        "Expire the oauth token."
        assert 'uuid' in kwargs
        assert 'timestamp' in kwargs

        authz = yield Authz.find(where=['uuid = ?', kwargs['uuid']], limit=1)
        authz.expired_on_timestamp = kwargs['timestamp']
        yield authz.save()

    @defer.inlineCallbacks
    def delete_oauth_token(self, **kwargs):
        # We might get a UUID or a client_name/service_name/user_id tuple.
        # This operation never fails.

        uuid = kwargs.get('uuid')
        if uuid:
            yield Authz.deleteAll(where=['uuid = ?', uuid])
            defer.returnValue(True)
        else:
            assert kwargs.get('client_name') != None
            assert kwargs.get('service_name') != None
            assert kwargs.get('user_id') != None

            yield Authz.deleteAll(where=self.args_to_where(**kwargs))
            defer.returnValue(True)

    @defer.inlineCallbacks
    def store_inflight_authz(self, **inflight_args):
        """Store data that must be preserved between authorization calls
        that must be preserved between calls.
        Args:
            inflight_args: dict, the data to store as an InflightAuthorization
        """
        yield InflightAuthz(
            service_name=inflight_args.get('service_name', None),
            request_token=inflight_args.get('request_token', None),
            secret=inflight_args.get('secret', None),
            state=inflight_args.get('state', None),
        ).save()

        defer.returnValue(True)

    @defer.inlineCallbacks
    def retrieve_inflight_authz(self, **kwargs):
        """This is used for the OAuth v1 authorization because there is data
        that must be preserved between calls.
        """
        data = yield InflightAuthz.find(
            where=self.args_to_where(**kwargs), limit=1
        )
        yield InflightAuthz.deleteAll(where=self.args_to_where(**kwargs))
        if data:
            defer.returnValue(data)
        else:
            defer.returnValue(None)

    @defer.inlineCallbacks
    def get_views(self):
        """Return a list of all views stored in the system.
        This takes no parameters.
        """
        try:
            views = yield View.find()
            defer.returnValue([v.name for v in views])
        except pyodbc.Error:
            logging.error(pprint.pformat(Registry.DBPOOL.__dict__))
            msg = ""
            for conn in Registry.DBPOOL.connections:
                msg += "%s, " % (pprint.pformat(Registry.DBPOOL.connections[conn]))
            logging.error('Connections: [%s]' % msg)

    @defer.inlineCallbacks
    def view_exists(self, name):
        'Does a view with this name exist?'
        view = yield View.find(where=['name = ?', name])
        exists = False
        if view:
            exists = True
        defer.returnValue(exists)

    @defer.inlineCallbacks
    def get_view(self, name):
        'Retrieve a view definition given a name'
        view = yield View.find(where=['name = ?', name], limit=1)
        if not view:
            defer.returnValue([])  # XXX(ray): Emulated behavior of tornadoredis

        items = json.loads(view.definition)
        defer.returnValue(items)

    @defer.inlineCallbacks
    def set_view(self, name, values):
        'Create or update a view. This does a complete overwrite.'
        view = yield View.find(where=['name = ?', name])
        if view:
            # Do an update.
            view.definition = json.dumps(values)
            view.update()
        else:
            # Do an insert.
            definition = json.dumps(values)
            yield View(name=name, definition=definition).save()
        defer.returnValue(True)

    @defer.inlineCallbacks
    def delete_view(self, name):
        'Delete a view given a name.'
        yield View.deleteAll(where=['name = ?', name])
        defer.returnValue(True)

    @defer.inlineCallbacks
    def is_duplicate_value(self, **kwargs):
        """
        Determine if kwargs['data'] is a duplicate of the most recent value
        for kwargs['uuid']/kwargs['method'].
        """
        old_data = yield UserData.find(
            where=self.args_to_where(without=['authorization', 'feed_type', 'timestamp'], **kwargs),
            limit=1
        )
        if old_data and str(old_data.data) == str(kwargs['data']):
            defer.returnValue(True)

        defer.returnValue(False)

    @defer.inlineCallbacks
    def get_value(self, authorization=None, method=None, testcase=None):
        'Retrieve the most recent value for a given UUID'

        assert authorization != None
        assert method != None

        # Look up the index of the data in the sorted-set. This will be
        # something returned by value_name()
        data = yield UserData.find(
            where=self.args_to_where(without=['testcase'], uuid=authorization.uuid, method=method),
            limit=1,
            orderby='timestamp DESC'
        )
        if not data:
            defer.returnValue([])
        try:
            val = int(data.data)
        except:
            val = json.loads(data.data)

        if authorization.expired_on_timestamp and authorization.expired_on_timestamp > data.timestamp:
            ret = [val, authorization.expired_on_timestamp]
        else:
            ret = [val]
        defer.returnValue(ret)

    @defer.inlineCallbacks
    def get_value_range(self, **kwargs):
        """Retrieve the list of values between 'start' and 'end' for an 'authorization'"""
        assert kwargs.get('authorization') != None
        assert kwargs.get('method') != None

        direction = 'ASC'
        if kwargs.get('reverse'):
            direction = 'DESC'

        start_time = int(kwargs.get('start', 1))
        end_time = int(kwargs.get('end', int(time.time())))
        authorization = kwargs['authorization']

        data = yield UserData.find(
            where=[
                'uuid = ? and method = ? and timestamp between ? and ?',
                authorization.uuid,
                kwargs['method'],
                start_time,
                end_time,
            ],
            orderby='timestamp %s' % direction
        )

        extended_start_time = start_time
        if start_time > 1 and start_time not in [x.timestamp for x in data]:
            addl_row = yield UserData.find(
                where=[
                    'uuid = ? and method = ? and timestamp < ?',
                    authorization.uuid,
                    kwargs['method'],
                    start_time,
                ],
                orderby='timestamp DESC',
                limit=1,
            )
            if addl_row:
                extended_start_time = addl_row.timestamp
                if direction == 'DESC':
                    data.append(addl_row)
                else:
                    data.insert(0, addl_row)

        ret = []
        for d in data:
            try:
                val = int(d.data)
            except:
                val = json.loads(d.data)
            ret.append(['%s' % d.timestamp, val])

        if kwargs.get('num'):
            ret = ret[0:kwargs['num']]

        ret_idx = len(ret) - 1
        is_expired_in_range = extended_start_time <= authorization.expired_on_timestamp <= end_time

        while ret_idx >= 0:
            if authorization.expired_on_timestamp >= int(ret[ret_idx][0]) and is_expired_in_range:
                ret[ret_idx].append(authorization.expired_on_timestamp)
                break
            ret_idx = ret_idx - 1

        for item in ret:
            if int(item[0]) < start_time:
                item[0] = str(start_time)

        defer.returnValue(ret)

    @defer.inlineCallbacks
    def write_value(self, **kwargs):
        """Set a value for 'uuid'/'method' at 'timestamp'"""

        assert kwargs.get('uuid') != None
        assert kwargs.get('method') != None
        assert kwargs.get('timestamp') != None

        data = kwargs['data']
        try:
            if "." in str(data):
                data = float(data)
            else:
                data = int(data)
        except:
            data = json.dumps(kwargs['data'])
        kwargs['data'] = data
        is_duplicate = yield self.is_duplicate_value(**kwargs)
        if is_duplicate:
            defer.returnValue(True)

        yield UserData(
            uuid=kwargs['uuid'],
            method=kwargs['method'],
            data=kwargs['data'],
            timestamp=int(kwargs['timestamp']),
        ).save()

        defer.returnValue(True)

    @defer.inlineCallbacks
    def delete_user_data(self, **kwargs):
        "Delete all the user-data"
        # We might get a UUID or a client_name/service_name/user_id tuple.
        uuid = kwargs.get('uuid')
        if not uuid:
            assert kwargs.get('client_name') != None
            assert kwargs.get('service_name') != None
            assert kwargs.get('user_id') != None

            authz = yield Authz.find(where=self.args_to_where(**kwargs), limit=1)
            if authz:
                uuid = authz.uuid
            else:
                defer.returnValue(False)

        yield UserData.deleteAll(where=['uuid = ?', uuid])
        yield GranularData.deleteAll(where=['uuid = ?', uuid])
        yield StreamCache.deleteAll(where=['uuid = ?', uuid])
        defer.returnValue(True)

    def get_last_granular_timestamp(self, **kwargs):
        def get_timestamp(row):
            if row:
                return row.timestamp
            return None

        return GranularData.find(
            where=['uuid=? AND method=?',
                kwargs['authorization'].uuid,
                kwargs['method'],
            ],
            limit=1,
            orderby='timestamp DESC',
        ).addCallback(get_timestamp)

    def write_granular_datum(self, **kwargs):
        return GranularData(
            uuid=kwargs['authorization'].uuid,
            method=kwargs['method'],
            item_id=kwargs['item_id'],
            actor_id=kwargs['actor_id'],
            timestamp=kwargs['timestamp'],
        ).save()

    def find_unwritten_granular_data(self, data, **kwargs):
        def filterme(db_data):
            ret = []
            for datum, exists in zip(data, db_data):
                if not exists:
                    ret.append(datum)
            return ret

        uuid = kwargs['authorization'].uuid
        return defer.gatherResults([
            GranularData.exists(
                where=['uuid=? AND method=? AND item_id=?',
                    uuid,
                    kwargs['method'],
                    datum['id'],
                ],
            ) for datum in data
        ]).addCallback(filterme)

    def retrieve_granular_data(self, **kwargs):
        return self.db.select(
            tablename='GranularData',
            select='actor_id, COUNT(*) AS num, MAX(timestamp) AS latest',
            where=['uuid=? AND method=? AND timestamp BETWEEN ? AND ? AND actor_id != ?',
                kwargs['uuid'],
                kwargs['method'],
                kwargs['start'], kwargs['end'],
                kwargs['user_id'],
            ],
            group='actor_id',
            orderby='num DESC, latest DESC',
            limit=1,
        )

    def update_stream_cache(self, data, authorization):
        records_to_process = {
            'add': [], # should contain dicts
            'remove': [], # should contain db records
            'update': [], # should contain dicts
        }

        def categorize(db_data):
            db_data = list(flatten(db_data))
            db_ids = [record.item_id for record in db_data]
            new_ids = [datum['item_id'] for datum in data]

            # find records to add
            for new_datum in data:
                if not new_datum['item_id'] in db_ids:
                    records_to_process['add'].append(new_datum)

            # find records to delete
            for db_datum in db_data:
                if not db_datum.item_id in new_ids:
                    records_to_process['remove'].append(db_datum)

            # find records to update
            for db_datum in db_data:
                for new_datum in data:
                    new_json = new_datum['data']
                    old_json = json.loads(db_datum.data)

                    if db_datum.item_id == new_datum['item_id'] and new_json != old_json:

                        change = {
                            'old': db_datum,
                            'new': new_datum
                        }
                        records_to_process['update'].append(change)
            return

        def add(_):
            return defer.gatherResults([
                StreamCache(
                    uuid=authorization.uuid,
                    item_id=datum['item_id'],
                    timestamp=datum['timestamp'],
                    data=json.dumps(datum['data']),
                ).save()
            for datum in records_to_process['add']
         ])


        def update_single(change):
            # change is a dictionary that contains two keys, `new` and `old`.
            # `new` contains the dictionary with new data from the 3rd party api that we need to update *to*
            # `old` containst the database record that needs to be updated with new data

            new_data = change['new']
            db_record = change['old']

            db_record.data = json.dumps(new_data['data'])
            return db_record.save()

        def update(_):
            return defer.gatherResults([
                update_single(change)
                    for change in records_to_process['update']])


        def remove(_):
            return defer.gatherResults([
                record.delete()
                    for record in records_to_process['remove']])

        uuid = authorization.uuid
        return StreamCache.find(
            where=['uuid=?', uuid]
        ).addCallback(categorize).addCallback(add).addCallback(remove).addCallback(update)

    def retrieve_stream_cache(self, **kwargs):
        where_clause = ['uuid=?',
            kwargs['uuid'],
        ]

        if not kwargs.get('order_by'):
            kwargs['order_by'] = 'timestamp DESC'

        if kwargs.get('start') or kwargs.get('end'):
            if kwargs.get('start') and kwargs.get('end'):
                where_clause[0] += ' AND timestamp BETWEEN ? AND ?'
                where_clause.append(kwargs.get('start'), kwargs['end'])
            elif kwargs.get('start'):
                where_clause[0] += ' AND timestamp >= ?'
                where_clause.append(kwargs['start'])
            else:
                where_clause[0] += ' AND timestamp <= ?'
                where_clause.append(kwargs['end'])

        if 'stream_type' in kwargs and kwargs['stream_type']:
            # Remove trailing 's' pluralization
            stream_type = kwargs['stream_type'][:-1]
            where_clause[0] += (" AND item_id LIKE '%s:%%'" % stream_type)

        def inflate_data(rows):
            # If no rows are returned, then don't inflate anything. This is a
            # normal use-case, if rare.
            if not rows:
                return

            # If only one row is returned, we'll get the row, not a list of rows
            if not isinstance(rows, list):
                rows = [rows]

            for row in rows:
                row['data'] = json.loads(row['data'])

            return rows

        return self.db.select(
            tablename='StreamCache',
            select='data',
            where=where_clause,
            orderby=kwargs['order_by'],
            limit=kwargs['limit'],
        ).addCallback(inflate_data)


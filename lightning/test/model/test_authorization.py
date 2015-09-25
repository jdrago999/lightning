from __future__ import absolute_import

from .base import TestBase, TestWithSQL

from twisted.internet import defer

from lightning.model.authorization import Authz
from lightning.datastore.sql import DatastoreSQL

class TestAuthz(TestBase, TestWithSQL):
    @defer.inlineCallbacks
    def setUp(self):
        # Ensure Redis is started first, then do our connection
        yield super(TestAuthz,self).setUp()
        self.db = yield DatastoreSQL.connect("dsn=SQLServer;uid=fakeuser;pwd=fakepassword;database=LIGHTNING_TEST;driver={SQL Server Native Client 10.0}")
        yield self.reset_db(self.db)
    @defer.inlineCallbacks
    def tearDown(self):
        yield self.reset_db(self.db)
        self.db.disconnect()
        super(TestAuthz,self).tearDown()

    @defer.inlineCallbacks
    def test_load_oauth2(self):
        authorization = dict(
            client_name='testing',
            service_name='loopback',
            user_id='a1234',
            token='b2345',
        )
        db_auth = yield self.db.set_oauth_token(
            **authorization
        )
        uuid = db_auth.uuid
        auth = yield Authz(
            uuid=uuid,
        ).get_token(self.db)
        self.assertEqual(auth.uuid, uuid)
        self.assertEqual(auth.client_name, authorization['client_name'])
        self.assertEqual(auth.service_name, authorization['service_name'])
        self.assertEqual(auth.user_id, authorization['user_id'])
        self.assertEqual(auth.token, authorization['token'])

    @defer.inlineCallbacks
    def test_load_oauth1(self):
        authorization = dict(
            client_name='testing',
            service_name='loopback',
            user_id='a1234',
            token='b2345',
            secret='c3456',
        )
        db_auth = yield self.db.set_oauth_token(
            **authorization
        )
        uuid = db_auth.uuid
        auth = yield Authz(
            uuid=uuid,
        ).get_token(self.db)
        self.assertEqual(auth.uuid, uuid)
        self.assertEqual(auth.client_name, authorization['client_name'])
        self.assertEqual(auth.service_name, authorization['service_name'])
        self.assertEqual(auth.user_id, authorization['user_id'])
        self.assertEqual(auth.token, authorization['token'])
        self.assertEqual(auth.secret, authorization['secret'])

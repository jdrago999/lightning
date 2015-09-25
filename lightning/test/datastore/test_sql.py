from __future__ import absolute_import


from ..base import TestBase, TestWithSQL
from twisted.internet import defer
from lightning.datastore.sql import DatastoreSQL
from lightning.model.authorization import Authz
from lightning.error import SQLError
import pprint


class TestDatastoreSQL(TestBase, TestWithSQL):

    @defer.inlineCallbacks
    def setUp(self):
        # Ensure SQL is started first, then do our connection
        yield super(TestDatastoreSQL, self).setUp()
        self.db = yield DatastoreSQL.connect("dsn=SQLServer;uid=fakeuser;pwd=fakepassword;database=LIGHTNING_TEST;driver={SQL Server Native Client 10.0}")
        yield self.reset_db(self.db)

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.reset_db(self.db)
        self.db.disconnect()
        super(TestDatastoreSQL, self).tearDown()

    def test_insert_null(self):
        self.failUnlessFailure(
            Authz(
                uuid=None,
                token=None
            ).save(),
            SQLError,
            'Inserting Authorization fails with non-null columns set to null'
        )

    @defer.inlineCallbacks
    def test_get_set_oauth_token_and_friends(self):
        client_name = 'testing'
        service_name = 'loopback'
        user_id = 'a1234'
        token = 'abcd'

        # First, test a retrieve with nothing there
        oauth_token = yield self.db.get_oauth_token(
            client_name=client_name,
            service_name=service_name,
            user_id=user_id,
        )
        self.assertEqual(len(oauth_token), 0, 'No oauth token yet')

        oauth_token = yield self.db.get_oauth_token(
            client_name=client_name,
            service_name=service_name,
        )
        self.assertEqual(len(oauth_token), 0, 'No oauth token yet (no user_id)')

        rv = yield self.db.delete_oauth_token(
            client_name=client_name,
            service_name=service_name,
            user_id=user_id,
        )
        self.assertTrue(rv, "Delete always succeeds")

        # Then, set something
        authz = yield self.db.set_oauth_token(
            client_name=client_name,
            service_name=service_name,
            user_id=user_id,
            token=token,
        )
        uuid = authz.uuid
        self.assertTrue(uuid)

        expected_token = Authz(
            client_name=client_name,
            service_name=service_name,
            user_id=user_id,
            token=token,
            uuid=uuid,
            redirect_uri=None,
            refresh_token=None,
            secret=None,
            expired_on_timestamp=None,
            id=1,
            is_new=True,
        )

        # We should now have the token
        oauth_token = yield self.db.get_oauth_token(
            client_name=client_name,
            service_name=service_name,
            user_id=user_id,
        )
        self.assertEqual(oauth_token, expected_token)

        # Get the same thing without the user_id
        oauth_token = yield self.db.get_oauth_token(
            client_name=client_name,
            service_name=service_name,
        )

        self.assertTrue(oauth_token)
        self.assertEqual(oauth_token, expected_token)

        # And we can retrieve it in different ways
        oauth_token = yield self.db.get_oauth_token(
            uuid=uuid,
        )
        self.assertEqual(oauth_token, expected_token)

        # Now, expire it and verify the expiration is there.
        #yield TestTask(
        #    self.db.expire_oauth_token,
        #    uuid=uuid,
        #    timestamp=expected_token['expired_on'],
        #)
        #self.assertEqual(oauth_token, expected_token)

        # Now, reauthorize it and verify the expiration is gone.
        #(uuid, is_new) = yield TestTask(
        #    self.db.set_oauth_token,
        #    client_name=client_name, service_name=service_name, user_id=user_id,
        #    token=token,
        #)
        #self.assertTrue(uuid)
        #self.assertFalse(is_new)

        #oauth_token = yield TestTask(
        #    self.db.get_oauth_token,
        #    client_name=client_name, service_name=service_name, user_id=user_id,
        #)
        #self.assertEqual(oauth_token, expected_token)

        # Then, delete it
        rv = yield self.db.delete_oauth_token(
            client_name=client_name,
            service_name=service_name,
            user_id=user_id,
        )
        pprint.pprint(rv)
        self.assertTrue(rv)

        # And we should now have nothing
        oauth_token = yield self.db.get_oauth_token(
            client_name=client_name,
            service_name=service_name,
            user_id=user_id,
        )
        self.assertEqual(len(oauth_token), 0, 'No oauth token anymore')

    # Need to add:
    # 1) What happens when we pass set_view() an empty list for values?
    # 2) Add the assert() calls to X_view()
    @defer.inlineCallbacks
    def test_get_set_view_and_friends(self):
        # First, test get_all, get_single, and exists with nothing.
        views = yield self.db.get_views()
        self.assertEqual(set(views), set())
        view_foo = yield self.db.get_view(
            name='foo',
        )
        self.assertEqual(view_foo, [])
        view_foo_exists = yield self.db.get_view(
            name='foo',
        )
        self.assertFalse(view_foo_exists)

        # Set something else.
        rv = yield self.db.set_view(
            name='bar',
            values=[
                dict(service='a', method='a1'),
                dict(service='b', method='b2'),
            ],
        )
        self.assertTrue(rv)

        # Re-do the retrieves
        views = yield self.db.get_views()
        self.assertEqual(set(views), set(['bar']))
        view_foo = yield self.db.get_view(
            name='foo',
        )
        self.assertEqual(view_foo, [])
        view_foo_exists = yield self.db.get_view(
            name='foo',
        )
        self.assertFalse(view_foo_exists)

        # Set what we want
        rv = yield self.db.set_view(
            name='foo',
            values=[
                dict(service='a', method='a1'),
                dict(service='b', method='b2'),
            ],
        )
        self.assertTrue(rv)

        # Re-do the retrieves
        views = yield self.db.get_views()
        self.assertEqual(set(views), set(['bar', 'foo']))
        view_foo = yield self.db.get_view(
            name='foo',
        )
        self.assertEqual(
            view_foo,
            [{'method':'a1', 'service':'a'}, {'service':'b', 'method':'b2'}]
        )
        view_foo_exists = yield self.db.get_view(
            name='foo',
        )
        self.assertTrue(view_foo_exists)

        # Delete the first
        rv = yield self.db.delete_view(
            name='bar',
        )
        self.assertTrue(rv)

        # Re-do the retrieves to see the second only
        views = yield self.db.get_views()
        self.assertEqual(set(views), set(['foo']))
        view_foo = yield self.db.get_view(
            name='foo',
        )
        self.assertEqual(
            view_foo,
            [{'method':'a1', 'service':'a'}, {'service':'b', 'method':'b2'}]
        )
        view_foo_exists = yield self.db.get_view(
            name='foo',
        )
        self.assertTrue(view_foo_exists)

        # Delete the first again (idempotency)
        rv = yield self.db.delete_view(
            name='bar',
        )
        self.assertTrue(rv)

        # Re-do the retrieves to see the second only
        views = yield self.db.get_views()
        self.assertEqual(set(views), set(['foo']))
        view_foo = yield self.db.get_view(
            name='foo',
        )
        self.assertEqual(
            view_foo,
            [{'method':'a1', 'service':'a'}, {'service':'b', 'method':'b2'}])
        view_foo_exists = yield self.db.get_view(
            name='foo',
        )
        self.assertTrue(view_foo_exists)

        # Delete the second
        rv = yield self.db.delete_view(
            name='foo',
        )
        self.assertTrue(rv)

        # Finally, test get_all, get_single, and exists with nothing.
        views = yield self.db.get_views()
        self.assertEqual(set(views), set())
        view_foo = yield self.db.get_view(
            name='foo',
        )
        self.assertEqual(view_foo, [])
        view_foo_exists = yield self.db.get_view(
            name='foo',
        )
        self.assertFalse(view_foo_exists)

    def _get(self, authorization=None, method='foo'):
        if not authorization:
            if hasattr(self, 'authorization'):
                authorization = self.authorization
            else:
                authorization = self._create_auth('abcd')
        return self.db.get_value(
            authorization=authorization,
            method=method,
        )

    def _create_auth(self, uuid):
        authorization = Authz(
            uuid=uuid,
            user_id='a1234',
            client_name='testing',
            service_name='loopback',
            token='abcd',
            expired_on_timestamp=None,
            refresh_token=None,
        )

        return authorization


    def _get_range(
        self,
        authorization=None,
        start=0,
        end=0,
        num=None,
        method='foo',
        reverse=False
    ):
        if not authorization:
            if hasattr(self, 'authorization'):
                authorization = self.authorization
            else:
                authorization = self._create_auth('abcd')
        return self.db.get_value_range(
            authorization=authorization,
            start=start,
            end=end,
            num=num,
            reverse=reverse,
            method=method,
        )

    @defer.inlineCallbacks
    def ensure_range(
        self,
        authorization=None,
        start=0,
        end=0,
        method='foo',
        num=None,
        expected=[],
        reverse=False
    ):
        if not authorization:
            if hasattr(self, 'authorization'):
                authorization = self.authorization
            else:
                authorization = self._create_auth('abcd')
        ret = yield self._get_range(authorization, start, end, num, method, reverse)
        self.assertEqual(ret, expected)

    @defer.inlineCallbacks
    def _write(self, uuid=None, timestamp=0, method='foo', data=None):
        if not uuid:
            if hasattr(self, 'uuid'):
                uuid = self.uuid
            else:
                uuid = 'abcd'

        found = yield Authz.find(
            where=[
                'uuid = ?',
                uuid
            ]
        )

        if not found:
            # Set up a test authorization.
            auth = yield Authz(
                uuid=uuid,
                user_id='a1234',
                client_name='testing',
                service_name='loopback',
                token='abcd',
            ).save()

        result = yield self.db.write_value(uuid=uuid, timestamp=timestamp, method=method, data=data)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def test_get_set_value_and_friends(self):
        # get_value and set_value are the (really bad) names for the functions
        # that are used to manage the bagpipe.
        # Invariants:
        # 1) get_value() should return the latest value
        # 2) set_value() should die if the same uuid/timestamp is provided
        # 3) get_value_range() should return the set of values within the start
        #    and end timestamps provided.

        secondary_auth = self._create_auth('efgh')


        rv = yield self._get(method='foo')
        self.assertEqual(rv, [])
        rv = yield self._get(authorization=secondary_auth, method='foo')
        self.assertEqual(rv, [])
        rv = yield self._get_range(method='foo')
        self.assertEqual(rv, [])

        rv = yield self._write(
            timestamp=10, method='foo', data='bar',
        )
        self.assertEqual(rv, True)

        rv = yield self._get(method='foo')
        self.assertEqual(rv, ['bar'])
        rv = yield self._get(authorization=secondary_auth, method='foo')
        self.assertEqual(rv, [])
        rv = yield self._get_range(start=8, end=9, method='foo')
        self.assertEqual(rv, [])
        rv = yield self._get_range(start=8, end=108, method='foo')
        self.assertEqual(rv, [
            ['10', 'bar'],
        ])

        rv = yield self._write(
            timestamp=1, method='foo', data='before',
        )
        self.assertEqual(rv, True)

        rv = yield self._get(method='foo')
        self.assertEqual(rv, ['bar'])
        rv = yield self._get_range(start=10, end=108, method='foo')
        self.assertEqual(rv, [
            ['10', 'bar'],
        ])

        rv = yield self._write(
            timestamp=100, method='foo', data='after',
        )
        self.assertEqual(rv, True)

        rv = yield self._get(method='foo')
        self.assertEqual(rv, ['after'])
        rv = yield self._get_range(start=10, end=108, method='foo')
        self.assertEqual(rv, [
            ['10', 'bar'],
            ['100', 'after'],
        ])

    @defer.inlineCallbacks
    def test_write_value_duplicates(self):
        rv = yield self._write(
            timestamp=10, method='foo', data='bar',
        )
        rv = yield self._get_range(start=8, end=108, method='foo')
        self.assertEqual(rv, [
            ['10', 'bar'],
        ])
        rv = yield self._write(
            timestamp=20, method='foo', data='bar',
        )
        rv = yield self._get_range(start=8, end=108, method='foo')
        self.assertEqual(rv, [
            ['10', 'bar'],
        ])
        rv = yield self._write(
            timestamp=30, method='foo', data='baz',
        )
        rv = yield self._get_range(start=8, end=108, method='foo')
        self.assertEqual(rv, [
            ['10', 'bar'],
            ['30', 'baz'],
        ])

    @defer.inlineCallbacks
    def test_range_gets(self):
        yield self._write(timestamp=10, data=20)

        yield self.ensure_range(start=1, end=9, expected=[])
        yield self.ensure_range(start=1, end=20, expected=[['10', 20]])
        yield self.ensure_range(start=11, end=20, expected=[['11', 20]])
        yield self.ensure_range(start=9, end=20, expected=[['10', 20]])

        yield self.ensure_range(start=1, end=9, reverse=True, expected=[])
        yield self.ensure_range(start=1, end=20, reverse=True, expected=[['10', 20]])
        yield self.ensure_range(start=11, end=20, reverse=True, expected=[['11', 20]])
        yield self.ensure_range(start=9, end=20, reverse=True, expected=[['10', 20]])

        yield self._write(timestamp=20, data=200)

        yield self.ensure_range(start=21, end=30, expected=[['21', 200]])
        yield self.ensure_range(start=15, end=30, expected=[['15',20],['20',200]])
        yield self.ensure_range(start=5, end=30, expected=[['10',20],['20',200]])
        yield self.ensure_range(start=10, end=30, expected=[['10',20],['20',200]])
        yield self.ensure_range(start=19, end=30, expected=[['19',20],['20',200]])
        yield self.ensure_range(start=20, end=30, expected=[['20',200]])

        yield self.ensure_range(start=21, end=30, reverse=True, expected=[['21',200]])
        yield self.ensure_range(start=15, end=30, reverse=True, expected=[['20',200],['15',20]])
        yield self.ensure_range(start=5, end=30, reverse=True, expected=[['20',200],['10',20]])
        yield self.ensure_range(start=10, end=30, reverse=True, expected=[['20',200],['10',20]])
        yield self.ensure_range(start=19, end=30, reverse=True, expected=[['20',200],['19',20]])
        yield self.ensure_range(start=20, end=30, reverse=True, expected=[['20',200]])

        yield self.ensure_range(start=21, end=30, num=1,expected=[['21',200]])
        yield self.ensure_range(start=21, end=30, num=2,expected=[['21',200]])
        yield self.ensure_range(start=15, end=30, num=1,expected=[['15',20]])

        yield self.ensure_range(start=21, end=30, num=1,reverse=True, expected=[['21',200]])
        yield self.ensure_range(start=21, end=30, num=2,reverse=True, expected=[['21',200]])
        yield self.ensure_range(start=15, end=30, num=1,reverse=True, expected=[['20',200]])

        yield self.ensure_range(start=15, end=30, num=2,expected=[['15',20], ['20',200]])
        yield self.ensure_range(start=15, end=30, num=3,expected=[['15',20], ['20',200]])
        yield self.ensure_range(start=5, end=30, num=1,expected=[['10',20]])

        yield self.ensure_range(start=15, end=30, num=2,reverse=True, expected=[['20',200],['15',20]])
        yield self.ensure_range(start=15, end=30, num=3,reverse=True, expected=[['20',200],['15',20]])
        yield self.ensure_range(start=5, end=30, num=1,reverse=True, expected=[['20',200]])

        yield self.ensure_range(start=5, end=30, num=2, expected=[['10',20],['20',200]])
        yield self.ensure_range(start=5, end=30, num=3, expected=[['10',20],['20',200]])
        yield self.ensure_range(start=10, end=30, num=1, expected=[['10',20]])

        yield self.ensure_range(start=5, end=30, num=2, reverse=True, expected=[['20',200],['10',20]])
        yield self.ensure_range(start=5, end=30, num=3, reverse=True, expected=[['20',200],['10',20]])
        yield self.ensure_range(start=10, end=30, num=1, reverse=True,expected=[['20',200]])

        yield self.ensure_range(start=10, end=30, num=2,expected=[['10',20],['20',200]])
        yield self.ensure_range(start=10, end=30, num=3,expected=[['10',20],['20',200]])
        yield self.ensure_range(start=19, end=30, num=1,expected=[['19',20]])

        yield self.ensure_range(start=10, end=30, num=2,reverse=True,expected=[['20',200],['10',20]])
        yield self.ensure_range(start=10, end=30, num=3,reverse=True,expected=[['20',200],['10',20]])
        yield self.ensure_range(start=19, end=30, num=1,reverse=True,expected=[['20',200]])

        yield self.ensure_range(start=19, end=30, num=2,expected=[['19',20],['20',200]])
        yield self.ensure_range(start=19, end=30, num=3,expected=[['19',20],['20',200]])
        yield self.ensure_range(start=20, end=30, num=1,expected=[['20',200]])
        yield self.ensure_range(start=20, end=30, num=2,expected=[['20',200]])

        yield self.ensure_range(start=19, end=30, num=2,reverse=True, expected=[['20',200],['19',20]])
        yield self.ensure_range(start=19, end=30, num=3,reverse=True, expected=[['20',200],['19',20]])
        yield self.ensure_range(start=20, end=30, num=1,reverse=True, expected=[['20',200]])
        yield self.ensure_range(start=20, end=30, num=2,reverse=True, expected=[['20',200]])

    @defer.inlineCallbacks
    def notest_range_gets_with_expiration(self):
        yield self.set_authorization()

        yield self._write(timestamp=10, data='20')
        yield self._write(timestamp=20, data='200')

        yield self.expire_authorization(timestamp=15)
        yield self.ensure_range(start=5,end=25,num=2,expected=[['10','20','15'],['20','200']])
        yield self.ensure_range(start=5,end=25,num=2,reverse=True,expected=[['20','200'],['10','20','15']])

        yield self.ensure_range(start=15,end=25,num=2,expected=[['15','20','15'],['20','200']])
        yield self.ensure_range(start=15,end=25,num=2,reverse=True,expected=[['20','200'],['15','20','15']])

        yield self.ensure_range(start=20,end=25,num=2,expected=[['20','200']])
        yield self.ensure_range(start=20,end=25,num=2,reverse=True,expected=[['20','200']])

        yield self.ensure_range(start=21,end=25,num=2,expected=[['21','200']])
        yield self.ensure_range(start=21,end=25,num=2,reverse=True,expected=[['21','200']])

        yield self.ensure_range(start=11,end=19,num=1,expected=[['11','20','15']])
        yield self.ensure_range(start=11,end=19,num=1,reverse=True,expected=[['11','20','15']])

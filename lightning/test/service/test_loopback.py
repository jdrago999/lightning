"Generic docstring A"
from __future__ import absolute_import

from .base import TestService, TestDaemon

from twisted.internet import defer
from twisted.web.error import Error

from lightning.error import MissingArgumentError
from lightning.service.loopback import LoopbackWeb, LoopbackDaemon, Loopback2Web

import logging
from pprint import pformat, pprint
import time
from urllib import urlencode
from mock import MagicMock
import twisted

class TestLoopback(TestService):
    def set_authorization(self, **kwargs):
        return super(TestLoopback, self).set_authorization(
            user_id='joe',
            token=self.service.oauth_token,
            **kwargs
        )

class TestLoopbackDaemon(TestLoopback, TestDaemon):
    """
    Something pithy.
    """
    def setUp(self):
        twisted.internet.base.DelayedCall.debug = True
        d = super(TestLoopbackDaemon, self).setUp()
        def on_setup(_):
            self.service = LoopbackDaemon(
                datastore=self.app.db,
            )

            return self.start_pyres()
        d.addCallback(on_setup)

        return d

    @defer.inlineCallbacks
    def tearDown(self):
        pyres = yield self.stop_pyres()
        super(TestLoopbackDaemon, self).tearDown()

    def test_recurring_methods(self):
        self.assertEqual( self.service.recurring(), {
            'fortytwo': 'Returns the string "fortytwo"',
            'ten': 'Returns the number 10',
            'time': 'Returns the current time in seconds since epoch',
            'random': 'Returns a random number between 1 and 999,999',
            'other_profile': 'Returns a random profile',
        })
    test_recurring_methods.timeout=20

    @defer.inlineCallbacks
    def test_run(self):
        self.skip_me('This intermittently fails on Jenkins')
        methods = [ 'ten', 'fortytwo', 'time', 'random', 'other_profile' ]
        yield self.set_authorization()

        time1 = int(time.time())

        yield self.resq.enqueue(
            LoopbackDaemon, {
                'sql': self.service.datastore.config,
                'environment': 'local',
            }, self.uuid,
        )

        # Wait for the worker
        time.sleep(1)

        first_data = {}
        for method in methods:
            first_data[method] = yield self.get_value(
                uuid=self.uuid,
                method=method,
            )

        self.assertEqual(first_data['ten'], 10)
        self.assertEqual(first_data['fortytwo'], 'fortytwo')
        self.assertRegexpMatches(str(first_data['random']), r'^\d{1,6}$')
        self.assertTrue(
            first_data['time'] == time1
            or first_data['time'] == time1+1
        )

        # Ensure the test that the times from the two runs will be different.
        time.sleep(1.5)

        time2 = int(time.time())
        yield self.resq.enqueue(
            LoopbackDaemon, {
                'sql': self.service.datastore.config,
                'environment': 'local',
            }, self.uuid,
        )

        # Wait for the worker
        time.sleep(1)

        second_data = {}
        for method in ['fortytwo', 'random', 'time', 'ten']:
            datum = yield self.get_value(
                uuid=self.uuid,
                method=method,
            )
            second_data[method] = datum
        self.assertEqual(second_data['fortytwo'], 'fortytwo')
        self.assertEqual(second_data['ten'], 10)
        self.assertRegexpMatches(str(second_data['random']), r'^\d{1,6}$')
        self.assertTrue(
            second_data['time'] == time2
            or second_data['time'] == time2+1
        )

        self.assertEqual(first_data['fortytwo'], second_data['fortytwo'])
        self.assertNotEqual(first_data['time'], second_data['time'])

        for method in ['fortytwo', 'time', 'ten']:
            second_range = yield self.get_value_range(
                start=time1-1000, end=time1+100, method=method,
            )
            if method == 'fortytwo':
                self.assertEqual(len(second_range), 1)
                self.assertLessEqual(str(time1), second_range[0][0])
                self.assertEqual(second_range[0][1], 'fortytwo')
            elif method == 'ten':
                self.assertEqual(len(second_range), 1)
                self.assertLessEqual(time1, second_range[0][0])
                self.assertEqual(second_range[0][1], 10)
            elif method == 'time':
                self.assertEqual(len(second_range), 2)
                self.assertLessEqual(time1, second_range[0][0])
                self.assertLessEqual(time2, second_range[1][0])
                self.assertTrue(
                    second_range[0][1] == time1
                    or second_range[0][1] == time1+1
                )
                self.assertTrue(
                    second_range[1][1] == time2
                    or second_range[1][1] == time2+1
                )

# These are tests for loopback authorization. LoopbackWeb and Loopback2Web
# inherit from Loopback which defines the authz methods. This allows the test
# classes to share the same tests to force the same interface (which is
# desirable). This class must not have 'test' anywhere in the name and it must
# not inherit from TestLightning in any way. This is a 'mixin'.
class LoopbackAuth():
    def test_start_authorization_missing_redirect_uri(self):
        self.assertRaises( MissingArgumentError,
            self.service.start_authorization,
            client_name='testing',
        )
    def test_start_authorization_missing_username(self):
        self.assertRaises( MissingArgumentError,
            self.service.start_authorization,
            client_name='testing',
            args={'redirect_uri': 'http://abcd.com/'},
        )
    @defer.inlineCallbacks
    def test_start_authorization(self):
        redir_uri = 'http://abcd.com/'
        rv = yield self.service.start_authorization(
            client_name='testing',
            args={'redirect_uri': redir_uri, 'username': 'joe'},
        )

        redir_uri = 'http://abcd.com/foo/bar'
        rv = yield self.service.start_authorization(
            client_name='testing',
            args={'redirect_uri': redir_uri, 'username': 'joe'},
        )
        self.assertURIEqual( rv, 'http://abcd.com/foo/bar?username=joe&'+urlencode({'redirect_uri': redir_uri}) )

        redir_uri = 'http://abcd.com/foo/bar?a=b&c=d'
        rv = yield self.service.start_authorization(
            client_name='testing',
            args={
                'redirect_uri': redir_uri,
                'username': 'joe',
            },
        )
        self.assertURIEqual( rv, 'http://abcd.com/foo/bar?a=b&c=d&username=joe&'+urlencode({'redirect_uri': redir_uri}) )

    def test_finish_authorization_missing_redirect_uri(self):
        # Can I test the error message?
        self.assertRaises( MissingArgumentError,
            self.service.finish_authorization,
            client_name='testing',
        )
    def test_finish_authorization_missing_username(self):
        self.assertRaises( MissingArgumentError,
            self.service.finish_authorization,
            client_name='testing',
            args=dict(
                redirect_uri='asdf',
            ),
        )
    @defer.inlineCallbacks
    def test_finish_authorization(self):
        username = 'joe'

        user_auth = yield self.service.finish_authorization(
            client_name='testing',
            args=dict(
                redirect_uri='asdf',
                username=username,
            ),
        )
        token = user_auth.token
        user_id = user_auth.user_id
        self.assertEqual(token, self.service.oauth_token)
        self.assertEqual(user_id, username)

class TestLoopbackWeb(TestLoopback, LoopbackAuth):
    @defer.inlineCallbacks
    def setUp(self):
        yield super(TestLoopbackWeb, self).setUp()
        self.service = LoopbackWeb(
            datastore=self.app.db,
        )

    @defer.inlineCallbacks
    def test_start_authorization_with_permissions(self):
        rv = yield self.service.start_authorization(
            client_name='testing2',
            args={'redirect_uri': 'http://abcd.com/', 'username': 'joe'},
        )
        self.assertURIEqual( rv, 'http://abcd.com/?scope=email,name&username=joe&redirect_uri=http://abcd.com/' )

        rv = yield self.service.start_authorization(
            client_name='testing2',
            args={'redirect_uri': 'http://abcd.com/foo/bar?a=b', 'username': 'joe'},
        )
        self.assertURIEqual( rv, 'http://abcd.com/foo/bar?a=b&scope=email,name&username=joe&redirect_uri=http://abcd.com/foo/bar?a=b' )

    @defer.inlineCallbacks
    def test_revoke(self):
        yield self.set_authorization()
        rv = yield self.service.revoke_authorization(
            authorization=self.authorization,
        )
        self.assertEqual(rv, True)

    def test_methods(self):
        self.maxDiff = 100000
        self.assertEqual( self.service.methods(), {
            'GET': {
                'most_recent_activity': "The most recent activity on this service's feed",
                'fortytwo': 'Returns the string "fortytwo"',
                'fortytwo_interval': 'Returns the string "fortytwo" over time',
                'ten': 'Returns the string "10"',
                'ten_interval': 'Returns the string "10" over time',
                'time': 'Returns the current time in seconds since epoch',
                'time_interval': 'Returns the current time in seconds since epoch over time',
                'random': 'Returns a random number between 1 and 999,999',
                'random_interval': 'Returns a series of random numbers between 1 and 999,999',
                'broken': 'Returns a 500 error',
                'sleep': 'Sleeps for the time in the "data" string (default 0.1s)',
                'whoami': 'Returns the client name in the "data" string',
                'profile': 'Returns a random profile',
                'other_profile': 'Returns a random profile',
                'num_foo': 'Number of foos',
                'num_foo_interval': 'Number of foos over time',
            },
            'POST': {
                'sleep_post': 'Sleeps for the time in the "data" string (default 0.1s)',
            },
        })

    @defer.inlineCallbacks
    def test_broken(self):
        yield self.set_authorization()
        self.assertRaises( Error,
            self.call_method, 'broken'
        )

    @defer.inlineCallbacks
    def test_broken_sends_error_email(self):
        yield self.set_authorization()

        # email
        self.app.email.send = MagicMock()

        result = yield self.get_and_verify(
            path='/api/loopback/broken',
            response_code=500,
            args=dict(guid=self.uuid),
        )

        # verify that send was called once
        self.assertTrue(self.app.email.send.called)

    @defer.inlineCallbacks
    def test_sleep(self):
        yield self.set_authorization()
        rv = yield self.call_method('sleep')
        self.assertEqual(rv, { 'data': '0.1' })

        rv = yield self.call_method('sleep', arguments=dict(data='0.3'))
        self.assertEqual(rv, { 'data': '0.3' })

    @defer.inlineCallbacks
    def test_whoami(self):
        yield self.set_authorization()
        rv = yield self.call_method('whoami')
        self.assertEqual(rv, { 'data': 'testing' })

        yield self.set_authorization(client_name='testing2')
        rv = yield self.call_method('whoami')
        self.assertEqual(rv, { 'data': 'testing2' })

    @defer.inlineCallbacks
    def test_profile(self):
        yield self.set_authorization()
        profile = yield self.call_method('profile')

        # profile calls should be consistent across calls
        expected_profile = dict(
            name=profile['name'],
            email=profile['email'],
        )

        self._test_method_result_keys('profile', profile, expected_profile)

    # Use loopback.fortytwo() for this
    # Tests (present-value):
    # 1) No data gathered
    @defer.inlineCallbacks
    def test_req_present_no_data(self):
        yield self.set_authorization()
        rv = yield self.call_method('fortytwo')
        self.assertEqual(rv, {'data': None})
    # 2) One datum gathered
    @defer.inlineCallbacks
    def test_req_present_one_datum(self):
        yield self.set_authorization()
        yield self.write_value(method='fortytwo', data='fortytwo')
        rv = yield self.call_method('fortytwo')
        self.assertEqual(rv, {'data': 'fortytwo'})
    # 3) Two data gathered, last returned
    @defer.inlineCallbacks
    def test_req_present_two_data(self):
        yield self.set_authorization()

        # Write one thing, get it back
        yield self.write_value(
            timestamp=int(time.time())-100,
            method='fortytwo',
            data='fortyone',
        )
        rv = yield self.call_method('fortytwo')
        self.assertEqual(rv, {'data': 'fortyone'})

        # Write one thing that's later, get the new one back
        yield self.write_value(
            method='fortytwo',
            data='fortytwo',
        )
        rv = yield self.call_method('fortytwo')
        self.assertEqual(rv, {'data': 'fortytwo'})
    # 4) One datum, then "noauth"
    @defer.inlineCallbacks
    def test_req_present_one_datum_then_noauth(self):
        yield self.set_authorization()
        this_time = 100
        yield self.write_value(method='fortytwo', data='fortytwo',timestamp=this_time)
        yield self.expire_authorization(timestamp=this_time+10)
        # refresh the auth after expiring it
        yield self.set_authorization()


        rv = yield self.call_method('fortytwo')
        self.assertEqual(rv, {
            'data': 'fortytwo', 'expired_on': this_time+10,
        })


    # Tests (interval-value):
    #  1) No data gathered
    @defer.inlineCallbacks
    def test_req_interval_no_data(self):
        yield self.set_authorization()
        rv = yield self.call_method('random_interval',
            arguments=dict( start=100, end=200 ),
        )
        self.assertEqual(rv, {'data': []})
    #  2) One datum gathered: in-band
    @defer.inlineCallbacks
    def test_req_interval_one_datum_inband(self):
        yield self.set_authorization()

        t = int(time.time())

        yield self.write_value(
            timestamp=t-10, method='random', data='20',
        )
        rv = yield self.call_method('random_interval',
            arguments=dict( start=t-100, end=t ),
        )
        self.assertEqual(rv, {'data': [
            { 'timestamp': str(t-10), 'num': 20 },
        ]})
    #  3) One datum gathered: out-of-band before the interval (carried over)
    @defer.inlineCallbacks
    def test_req_interval_one_datum_outband_before(self):
        yield self.set_authorization()

        t = int(time.time())

        yield self.write_value(
            timestamp=t-100, method='random', data='20',
        )
        rv = yield self.call_method('random_interval',
            arguments=dict( start=t-10, end=t ),
        )
        self.assertEqual(rv, {'data': [
            { 'timestamp': str(t-10), 'num': 20 },
        ]})

    #  3) One datum gathered: out-of-band after the interval
    @defer.inlineCallbacks
    def test_req_interval_one_datum_outband_after(self):
        yield self.set_authorization()

        t = int(time.time())

        yield self.write_value(
            timestamp=t-10, method='random', data='20',
        )
        rv = yield self.call_method('random_interval',
            arguments=dict( start=t-100, end=t-50 ),
        )
        self.assertEqual(rv, {'data': [
        ]})

    #  4) One datum gathered: noauth after (inband)
    @defer.inlineCallbacks
    def test_req_interval_one_datum_noauth_inband(self):
        t = 100

        yield self.set_authorization()
        yield self.write_value(
            timestamp=t, method='random', data='20',
        )

        yield self.expire_authorization(timestamp=t+50)

        rv = yield self.call_method('random_interval',
            arguments=dict( start=t, end=t+100 ),
        )
        self.assertEqual(rv, {
            'data': [
                { 'timestamp': str(t), 'num': 20, 'expired_on': t+50 },
            ],
        })

    # TODO: Need a test that has multiple expirations
    # TODO: Need to reverse every one of the interval tests

    #  5) One datum gathered: noauth after (outband)
    @defer.inlineCallbacks
    def test_req_interval_one_datum_outband_noauth(self):
        t = 100

        yield self.set_authorization()
        yield self.write_value(
            timestamp=t, method='random', data='20',
        )

        yield self.expire_authorization(timestamp=t+50)

        rv = yield self.call_method('random_interval',
            arguments=dict( start=t+20, end=t+100 ),
        )
        self.assertEqual(rv, {
            'data': [
                {'timestamp': str(t+20), 'num': 20, 'expired_on': t+50},
            ],
        })
    #  6) Two data gathered: in-band, out-band
    @defer.inlineCallbacks
    def test_req_interval_inband_outband(self):
        yield self.set_authorization()

        t = int(time.time())

        yield self.write_value(
            timestamp=t-100, method='random', data='10',
        )
        yield self.write_value(
            timestamp=t-10, method='random', data='20',
        )
        rv = yield self.call_method('random_interval',
            arguments=dict( start=t-120, end=t-80 ),
        )
        self.assertEqual(rv, {'data': [
            { 'timestamp': str(t-100), 'num': 10 },
        ]})
    #  7) Two data gathered: out-band, in-band
    @defer.inlineCallbacks
    def test_req_interval_outband_inband(self):
        yield self.set_authorization()

        t = 100

        yield self.write_value(
            timestamp=t, method='random', data='10',
        )
        yield self.write_value(
            timestamp=t+100, method='random', data='20',
        )
        rv = yield self.call_method('random_interval',
            arguments=dict( start=t+50, end=t+200 ),
        )
        logging.debug(pformat(rv))
        self.assertEqual(rv, {'data': [
            { 'timestamp': str(t+50), 'num': 10 },
            { 'timestamp': str(t+100), 'num': 20 },
        ]})
    #  8) Two data gathered: two in-band
    @defer.inlineCallbacks
    def test_req_interval_inband_inband(self):
        yield self.set_authorization()

        t = int(time.time())

        yield self.write_value(
            timestamp=t-100, method='random', data='10',
        )
        yield self.write_value(
            timestamp=t-10, method='random', data='20',
        )
        rv = yield self.call_method('random_interval',
            arguments=dict( start=t-120, end=t ),
        )
        self.assertEqual(rv, {'data': [
            { 'timestamp': str(t-100), 'num': 10 },
            { 'timestamp': str(t-10), 'num': 20 },
        ]})
    #  9) Two data gathered: two out-band
    @defer.inlineCallbacks
    def test_req_interval_outband_before_outband_after(self):
        yield self.set_authorization()

        t = int(time.time())

        yield self.write_value(
            timestamp=t-100, method='random', data='10',
        )
        yield self.write_value(
            timestamp=t-10, method='random', data='20',
        )
        rv = yield self.call_method('random_interval',
            arguments=dict( start=t-90, end=t-80 ),
        )
        self.assertEqual(rv, {'data': [
            { 'timestamp': str(t-90), 'num': 10 },
        ]})
    # 10) Three data gathered: in-band, noauth(in), in-band
    @defer.inlineCallbacks
    def test_req_interval_inband_noauth_inband(self):
        yield self.set_authorization()

        yield self.write_value(
            timestamp=900, method='random', data='10',
        )
        yield self.expire_authorization(timestamp=950)
        yield self.write_value(
            timestamp=990, method='random', data='20',
        )
        ret = yield self.call_method('random_interval',
            arguments=dict( start=800, end=1000 ),
        )
        self.assertEqual(ret, {'data': [
            { 'timestamp': '900', 'num': 10, 'expired_on': 950 },
            { 'timestamp': '990', 'num': 20 },
        ]})
    # 11) Three data gathered: out-band, noauth(in), in-band
    @defer.inlineCallbacks
    def test_req_interval_outband_noauth_inband(self):
        yield self.set_authorization()

        t = 1000

        yield self.write_value(
            timestamp=t-100, method='random', data='10',
        )
        yield self.expire_authorization(timestamp=t-50)
        yield self.write_value(
            timestamp=t-10, method='random', data='20',
        )
        rv = yield self.call_method('random_interval',
            arguments=dict( start=t-60, end=t ),
        )
        self.assertEqual(rv, {'data': [
            { 'timestamp': str(t-60), 'num': 10, 'expired_on': t-50 },
            { 'timestamp': str(t-10), 'num': 20 },
        ]})
    # 12) Three data gathered: out-band, noauth(out), in-band
    @defer.inlineCallbacks
    def test_req_interval_outband_noauthoutband_inband(self):
        yield self.set_authorization()

        t = 1000

        yield self.write_value(
            timestamp=t-100, method='random', data='10',
        )
        yield self.expire_authorization(timestamp=t-50)
        yield self.write_value(
            timestamp=t-10, method='random', data='20',
        )
        rv = yield self.call_method('random_interval',
            arguments=dict( start=t-40, end=t ),
        )
        self.assertEqual(rv, {'data': [
            { 'timestamp': str(t-40), 'num': 10, 'expired_on': t-50 },
            { 'timestamp': str(t-10), 'num': 20 },
        ]})
    # 13) Three data gathered: in-band, noauth(in), out-band
    @defer.inlineCallbacks
    def test_req_interval_outband_noauthinband_outband(self):
        yield self.set_authorization()

        t = 1000

        yield self.write_value(
            timestamp=t-100, method='random', data='10',
        )
        yield self.expire_authorization(timestamp=t-50)
        yield self.write_value(
            timestamp=t-10, method='random', data='20',
        )
        rv = yield self.call_method('random_interval',
            arguments=dict( start=t-60, end=t-20 ),
        )
        self.assertEqual(rv, {'data': [
            { 'timestamp': str(t-60), 'num': 10, 'expired_on': t-50 },
        ]})
    # 14) Three data gathered: in-band, noauth(out), out-band
    @defer.inlineCallbacks
    def test_req_interval_outband_noauthoutband_outband(self):
        yield self.set_authorization()

        t = 1000

        yield self.write_value(
            timestamp=t-100, method='random', data='10',
        )
        yield self.expire_authorization(timestamp=t-50)

        yield self.write_value(
            timestamp=t-10, method='random', data='20',
        )
        rv = yield self.call_method('random_interval',
            arguments=dict( start=t-40, end=t-20 ),
        )
        self.assertEqual(rv, {'data': [
            { 'timestamp': str(t-40), 'num': 10, 'expired_on': t-50 },
        ]})
    # 15) Three data gathered: in-band, in-band, noauth(in)
    @defer.inlineCallbacks
    def test_req_interval_inband_inband_noauthinband(self):
        yield self.set_authorization()

        t = 1000

        yield self.write_value(
            timestamp=t-100, method='random', data='10',
        )
        yield self.write_value(
            timestamp=t-60, method='random', data='20',
        )
        yield self.expire_authorization(timestamp=t-50)
        rv = yield self.call_method('random_interval',
            arguments=dict( start=t-120, end=t-20 ),
        )
        self.assertEqual(rv, {'data': [
            { 'timestamp': str(t-100), 'num': 10 },
            { 'timestamp': str(t-60), 'num': 20, 'expired_on': t-50 },
        ]})
    # 16) Three data gathered: in-band, in-band, noauth(out)
    @defer.inlineCallbacks
    def test_req_interval_inband_inband_noauthoutband(self):
        yield self.set_authorization()

        t = 1000

        yield self.write_value(
            timestamp=t-100, method='random', data='10',
        )
        yield self.write_value(
            timestamp=t-60, method='random', data='20',
        )
        yield self.expire_authorization(timestamp=t)
        rv = yield self.call_method('random_interval',
            arguments=dict( start=t-120, end=t-20 ),
        )
        self.assertEqual(rv, {'data': [
            { 'timestamp': str(t-100), 'num': 10 },
            { 'timestamp': str(t-60), 'num': 20 },
        ]})
    # 17) Three data gathered: out-band, in-band, noauth(in)
    @defer.inlineCallbacks
    def test_req_interval_outband_inband_noauthinband(self):
        yield self.set_authorization()

        t = 1000

        yield self.write_value(
            timestamp=t-100, method='random', data='10',
        )
        yield self.write_value(
            timestamp=t-60, method='random', data='20',
        )
        yield self.expire_authorization(timestamp=t)

        rv = yield self.call_method('random_interval',
            arguments=dict( start=t-80, end=t ),
        )
        self.assertEqual(rv, {'data': [
            { 'timestamp': str(t-80), 'num': 10 },
            { 'timestamp': str(t-60), 'num': 20, 'expired_on': t },
        ]})
    # 18) Three data gathered: out-band, in-band, noauth(out)
    @defer.inlineCallbacks
    def test_req_interval_outband_inband_noauthoutband(self):
        yield self.set_authorization()

        t = 1000

        yield self.write_value(
            timestamp=t-100, method='random', data='10',
        )
        yield self.write_value(
            timestamp=t-60, method='random', data='20',
        )
        yield self.expire_authorization(timestamp=t)
        rv = yield self.call_method('random_interval',
            arguments=dict( start=t-80, end=t-10 ),
        )
        self.assertEqual(rv, {'data': [
            { 'timestamp': str(t-80), 'num': 10 },
            { 'timestamp': str(t-60), 'num': 20 },
        ]})
    # 19) Three data gathered: in-band, out-band, noauth(out)
    @defer.inlineCallbacks
    def test_req_interval_outband_outband_noauthoutband(self):
        yield self.set_authorization()

        t = 1000

        yield self.write_value(
            timestamp=t-100, method='random', data='10',
        )
        yield self.write_value(
            timestamp=t-60, method='random', data='20',
        )
        yield self.expire_authorization(timestamp=t)
        rv = yield self.call_method('random_interval',
            arguments=dict( start=t-80, end=t-70 ),
        )
        self.assertEqual(rv, {'data': [
            { 'timestamp': str(t-80), 'num': 10 },
        ]})

    # noauth == noauth(401), fail(500)

class TestLoopback2Web(TestLoopback, LoopbackAuth):
    @defer.inlineCallbacks
    def setUp(self):
        yield super(TestLoopback2Web, self).setUp()
        self.service = Loopback2Web(
            datastore=self.app.db,
        )

    def test_methods(self):
        self.assertEqual( self.service.methods(), {
            'GET': {
                'most_recent_activity': "The most recent activity on this service's feed",
                'time': 'Returns the current time in seconds since epoch',
                'num_foo': 'Number of foos',
                'num_foo_interval': 'Number of foos over time',
            },
            'POST': {},
        })

    @defer.inlineCallbacks
    def test_time(self):
        yield self.set_authorization()
        thistime = int(time.time())
        rv = yield self.call_method('time')
        # We *might* have hit the time ticking over.
        self.assertTrue(
            rv['data'] == str(thistime)
            or rv['data'] == str(thistime+1)
        )

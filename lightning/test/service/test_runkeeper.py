from __future__ import absolute_import

from .base import TestService

from lightning.recorder import recorder
from lightning.service.runkeeper import RunKeeperWeb, RunKeeperDaemon
from lightning.utils import compose_url, get_arguments_from_redirect

from twisted.internet import defer

from bs4 import BeautifulSoup
import requests
import time

# This is a 'real user' for use with authorization tests
AUTHN_TEST_USER = {
    'user_id': '11245',
    'gender': 'M',
    'email': 'test@example.com',
    'password': 'testpassword',
    'name': 'Example User',
    'picture': 'http://s3.amazonaws.com/profilepic.runkeeper.com/AAAA_norm.jpg',
    'profile_link': 'http://runkeeper.com/user/1234455',
    'num_activities': 2,
    'num_calories': 986,
    'num_comments': 4,
    'num_friends': 1,
    'total_distance': 4.12,
    'total_duration': 14400,
}


class RunKeeperWebMock(RunKeeperWeb):
    # Override the current time so that it is consistent between test runs
    def current_timestamp(self):
        return 1378294500


class TestRunKeeper(TestService):
    def set_authorization(self, **kwargs):
        # If we don't care about these values, then just hack something in.
        #for key in ['token', 'user_id']:
        #    if not kwargs.get(key):
        #        kwargs[key] = 'asdf'

        kwargs['service_name'] = 'runkeeper'
        return super(TestRunKeeper, self).set_authorization(**kwargs)


class TestRunKeeperWeb(TestRunKeeper):
    @defer.inlineCallbacks
    def setUp(self):
        yield super(TestRunKeeperWeb, self).setUp()
        self.service = RunKeeperWebMock(
            datastore=self.app.db,
        )
        self.daemon = self.service.daemon_object()

        recorder.wrap(self.service.actually_request)
        recorder.wrap(self.daemon.actually_request)
        recorder.wrap(requests.request)
        recorder.play()

    def tearDown(self):
        recorder.save()
        super(TestRunKeeperWeb, self).tearDown()

    @defer.inlineCallbacks
    def test_recorded_authorize(self):
        # Note: This test requires recorded responses from Lightning Console.
        redir_uri = 'https://lg-local.example.com/id/auth/callback/runkeeper'

        expected_redirect = compose_url(
            'https://runkeeper.com/apps/authorize',
            query={
                'redirect_uri': redir_uri,
                'client_id': self.service.app_info[self.service.environment]['app_id'],
                'response_type': 'code',
            },
        )
        rv = yield self.service.start_authorization(
            client_name='testing',
            args={'redirect_uri': redir_uri},
        )
        self.assertURIEqual(rv, expected_redirect)

        auth = yield self.service.finish_authorization(
            client_name='testing',
            args={
                'code': 'foo',
                'redirect_uri': redir_uri,
            },
        )

        oauth_token = auth.token
        user_id = auth.user_id
        oauth_secret = auth.secret

        self.assertTrue(oauth_token)
        self.assertEqual(AUTHN_TEST_USER['user_id'], user_id)

        # Verify this authorization is any good.
        yield self.set_authorization(
            user_id=user_id, token=oauth_token,
        )

        for method in self.service.daemon_object()._recurring:
            yield self.service.daemon_object().run(
                authorization=self.authorization,
                timestamp=int(time.time()),
                daemon_method=method,
            )

        profile = yield self.call_method('profile')
        expected_profile = dict(
            name=AUTHN_TEST_USER['name'],
            gender=AUTHN_TEST_USER['gender'],
            profile_picture_link=AUTHN_TEST_USER['picture'],
            profile_link=AUTHN_TEST_USER['profile_link'],
        )

        self._test_method_result_keys('profile', profile, expected_profile)

        num_activities = yield self.call_method('num_activities')
        self.assertEqual(
            num_activities, {'num': AUTHN_TEST_USER['num_activities']}
        )
        num_calories = yield self.call_method('num_calories')
        self.assertEqual(
            num_calories, {'num': AUTHN_TEST_USER['num_calories']}
        )
        num_comments = yield self.call_method('num_comments')
        self.assertEqual(
            num_comments, {'num': AUTHN_TEST_USER['num_comments']}
        )
        num_friends = yield self.call_method('num_friends')
        self.assertEqual(
            num_friends, {'num': AUTHN_TEST_USER['num_friends']}
        )
        total_distance_result = yield self.call_method('total_distance')
        total_distance = total_distance_result['num']

        self.assertAlmostEqual(
            total_distance, AUTHN_TEST_USER['total_distance'], 3
        )
        total_duration = yield self.call_method('total_duration')
        self.assertEqual(
            total_duration, {'num': AUTHN_TEST_USER['total_duration']}
        )

        # Verify that we get the fist activity time correct
        result = yield self.call_method('account_created_timestamp')
        got_timestamp = result['timestamp']
        expected_timestamp = 1363028119
        month_in_seconds = 31 * 24 * 60 * 60

        # make sure the timestamp we got is within 31 days of the one we expect
        self.assertLess(abs(got_timestamp - expected_timestamp), month_in_seconds)


    def test_methods(self):
        self.assertEqual(self.service.methods(), {
            'GET': {
                'account_created_timestamp': 'Returns the approximate (to within a month) time at which the user first posted to this service',
                'most_recent_activity': "The most recent activity on this service's feed",
                'num_activities': "Returns this user's number of activities.",
                'num_activities_interval': "Returns this user's number of activities over time.",
                'num_calories': "Returns this user's number of calories.",
                'num_calories_interval': "Returns this user's number of calories over time.",
                'num_comments': "Returns the number of comments on the user's activities.",
                'num_comments_interval': "Returns the number of comments on the user's activities over time.",
                'num_friends': "Returns this user's number of friends.",
                'num_friends_interval': "Returns this user's number of friends over time.",
                'total_distance': "Returns this user's total distance traveled (in meters).",
                'total_distance_interval': "Returns this user's total distance traveled (in meters) over time.",
                'total_duration': "Returns this user's total time spent on fitness activities (in seconds).",
                'total_duration_interval': "Returns this user's total time spent on fitness activities (in seconds) over time.",
                'profile': "Returns this user's profile."},
            'POST': {},
        })

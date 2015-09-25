from __future__ import absolute_import

from .base import TestService

from lightning.recorder import recorder
from lightning.service.foursquare import FoursquareWeb, FoursquareDaemon
from lightning.utils import compose_url, get_arguments_from_redirect

from twisted.internet import defer

from bs4 import BeautifulSoup
import re
import requests
import time


# This is a 'real user' for use with authorization tests
AUTHN_TEST_USER = {
    'user_id': '1234',
    'email': 'test@example.com',
    'password': 'testpassword',
    'name': 'Example User',
    'username': None,
    'gender': 'none',
    'bio': 'Something intelligent here.',
    'picture': 'https://irs2.4sqi.net/img/user/100x100/BAILZENK3KPEAAAAAAAAAAAS.jpg',
    'link': 'https://foursquare.com/user/1234',
    'num_friends': 0,
    'num_checkins': 1,
    'num_mayorships': 0,
    'num_photos': 0,
    'num_lists': 1,
}


class TestFoursquare(TestService):
    def set_authorization(self, **kwargs):
        # If we don't care about these values, then just hack something in.
        for key in ['token', 'user_id']:
            if not kwargs.get(key):
                kwargs[key] = 'asdf'

        kwargs['service_name'] = 'foursquare'
        return super(TestFoursquare, self).set_authorization(**kwargs)


class TestFoursquareWeb(TestFoursquare):
    @defer.inlineCallbacks
    def setUp(self, *args, **kwargs):
        yield super(TestFoursquareWeb, self).setUp(*args, **kwargs)
        self.service = FoursquareWeb(
            datastore=self.app.db,
        )
        self.daemon = self.service.daemon_object()

        recorder.wrap(self.service.actually_request)
        recorder.wrap(self.daemon.actually_request)
        recorder.play()

    def tearDown(self):
        recorder.save()
        super(TestFoursquareWeb, self).tearDown()

    @defer.inlineCallbacks
    def test_recorded_authorize(self):
        # Note: This test requires recorded responses from Lightning Console.
        redir_uri = 'https://lg-local.example.com/id/auth/callback/foursquare'

        expected_redirect = compose_url(
            'https://foursquare.com/oauth2/authenticate',
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

        user_auth = yield self.service.finish_authorization(
            client_name='testing',
            args={
                'redirect_uri': redir_uri,
                'code': 'foo',
            }
        )

        self.assertTrue(user_auth.token)
        self.assertEqual(AUTHN_TEST_USER['user_id'], user_auth.user_id)

        # Verify this authorization is any good.
        yield self.set_authorization(
            user_id=user_auth.user_id, token=user_auth.token,
        )

        for method in self.service.daemon_object()._recurring:
            yield self.service.daemon_object().run(
                authorization=self.authorization,
                timestamp=int(time.time()),
                daemon_method=method,
            )
        profile = yield self.call_method('profile')

        # profile calls should be consistent across calls
        expected_profile = dict(
            name=AUTHN_TEST_USER['name'],
            username=AUTHN_TEST_USER['username'],
            bio=AUTHN_TEST_USER['bio'],
            profile_picture_link=AUTHN_TEST_USER['picture'],
            profile_link=AUTHN_TEST_USER['link'],
            gender=AUTHN_TEST_USER['gender'],
            email=AUTHN_TEST_USER['email'],
        )
        self._test_method_result_keys('profile', profile, expected_profile)

        num_friends = yield self.call_method('num_friends')
        self.assertEqual(num_friends, {'num': AUTHN_TEST_USER['num_friends']})
        num_mayorships = yield self.call_method('num_mayorships')
        self.assertEqual(num_mayorships, {'num': AUTHN_TEST_USER['num_mayorships']})
        num_photos = yield self.call_method('num_photos')
        self.assertEqual(num_photos, {'num': AUTHN_TEST_USER['num_photos']})
        num_lists = yield self.call_method('num_lists')
        self.assertEqual(num_lists, {'num': AUTHN_TEST_USER['num_lists']})
        num_checkins = yield self.call_method('num_checkins')
        self.assertEqual(num_checkins, {'num': AUTHN_TEST_USER['num_checkins']})

    def test_methods(self):
        self.assertEqual(self.service.methods(), {
            'GET': {
                'account_created_timestamp': 'Returns the approximate (to within a month) time at which the user first posted to this service',
                'most_recent_activity': "The most recent activity on this service's feed",
                'recent_content_authored': "The recent content authored by this user",
                'profile': "Returns this user's profile.",
                'num_friends': "Number of friends",
                'num_friends_interval': "Number of friends over time",
                'num_mayorships': "Number of mayorships",
                'num_mayorships_interval': "Number of mayorships over time",
                'num_photos': "Number of photos",
                'num_photos_interval': "Number of photos over time",
                'num_lists': "Number of lists",
                'num_lists_interval': "Number of lists over time",
                'num_checkins': "Number of check-ins",
                'num_checkins_interval': "Number of check-ins over time",
            },
            'POST': {},
        })


# There is no test users through the Foursquare API, therefore there is no clear
# way to test the pyres implementation outside of using it within the authorize
# test. There needs to be a better way to do this.
class TestFoursquareDaemon(TestFoursquare):
    @defer.inlineCallbacks
    def setUp(self, *args, **kwargs):
        yield super(TestFoursquareDaemon, self).setUp(*args, **kwargs)
        self.service = FoursquareDaemon(
            datastore=self.app.db,
        )

    def test_recurring_methods(self):
        self.assertEqual(self.service.recurring(), {
            'values_from_profile': "Values from profile",
            'profile': "Returns this user's profile.",
        })

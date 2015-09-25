"Generic docstring A"
from __future__ import absolute_import

from lightning.test.service.base import TestService
from twisted.internet import defer

from lightning.recorder import recorder
from lightning.service.googleplus import GooglePlusWeb
from lightning.utils import compose_url, get_arguments_from_redirect

from bs4 import BeautifulSoup
import re
import requests
import time

# This is a 'real user' for use with authorization tests
AUTHN_TEST_USER = {
    'user_id': '1234',
    'email': 'test@example.com',
    'password': 'testpassword',
    'name': 'Larry Example User',
    'id': '12345',
    'gender': 'male',
    'profile_picture_link': 'https://lh5.googleusercontent.com/-aaaaa_o/AAAAAAAAAAI/AAAAAAAAABk/bbbbbb/photo.jpg?sz=50',
    'profile_link': 'https://plus.google.com/1234',
    'num_following': 1,
    'num_comments_recent_10_activities': 0,
    'num_activities': 0,
}


class TestGooglePlus(TestService):
    def set_authorization(self, **kwargs):
        # If we don't care about these values, then just hack something in.
        for key in ['token', 'user_id']:
            if not kwargs.get(key):
                kwargs[key] = 'asdf'

        kwargs['service_name'] = 'googleplus'
        return super(TestGooglePlus, self).set_authorization(**kwargs)

class TestGooglePlusWeb(TestGooglePlus):
    @defer.inlineCallbacks
    def setUp(self, *args, **kwargs):
        yield super(TestGooglePlusWeb, self).setUp(*args, **kwargs)
        self.service = GooglePlusWeb(
            datastore=self.app.db,
        )
        self.daemon = self.service.daemon_object()

        recorder.wrap(self.service.actually_request)
        recorder.wrap(self.daemon.actually_request)
        recorder.wrap(requests.request)
        recorder.play()
        # recorder.record()

    def tearDown(self):
        recorder.save()
        super(TestGooglePlusWeb, self).tearDown()

    @defer.inlineCallbacks
    def test_recorded_authorize(self):
        # Note: This test requires recorded responses from Lightning Console.
        redir_uri = 'https://lg-local.example.com/id/auth/callback/googleplus'

        expected_redirect = compose_url(
            'https://accounts.google.com/o/oauth2/auth',
            query={
                'access_type': 'offline',
                'approval_prompt': 'force',
                'redirect_uri': redir_uri,
                'client_id': self.service.app_info[self.service.environment]['app_id'],
                'scope': 'https://www.googleapis.com/auth/plus.login',
                'response_type': 'code',
            },
        )
        redirect_uri = yield self.service.start_authorization(
            client_name='testing',
            args={'redirect_uri': redir_uri},
        )
        self.assertURIEqual(redirect_uri, expected_redirect)
        auth = yield self.service.finish_authorization(
            client_name='testing',
            args={
                'redirect_uri': redir_uri,
                'code': 'foo',
            },
        )

        self.assertIsNotNone(auth.token)
        self.assertIsNotNone(auth.refresh_token)
        self.assertEqual(AUTHN_TEST_USER['id'], auth.user_id)

        yield self.set_authorization(
            user_id=auth.user_id,
            token=auth.token,
            refresh_token=auth.refresh_token
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
            profile_picture_link=AUTHN_TEST_USER['profile_picture_link'],
            profile_link=AUTHN_TEST_USER['profile_link'],
        )
        self._test_method_result_keys('profile', profile, expected_profile)


    def test_methods(self):
        self.assertEqual(self.service.methods(), {
            'GET': {
                 'account_created_timestamp': 'Returns the time at which the user first posted to to this serivice',    'most_recent_activity': "The most recent activity on this service's feed",
                 'profile': "Returns this user's profile."},
            'POST': {},
        })

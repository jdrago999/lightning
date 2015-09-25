"Generic docstring A"
from __future__ import absolute_import

from .base import TestService

from twisted.internet import defer

from lightning.recorder import recorder
from lightning.service.youtube import YoutubeWeb
from lightning.utils import compose_url, get_arguments_from_redirect

from bs4 import BeautifulSoup
import re
import requests
import time

# This is a 'real user' for use with authorization tests
AUTHN_TEST_USER = {
    #'user_id': '123',
    'email': 'test@example.com',
    'password': 'testpass',
    'name': 'Larry Example User',
    'username': '',
    'gender': 'male',
    'num_videos': 0,
    'num_likes': 0,
    'num_favorites': 0,
    'num_views': 0,
    'id': 'bbbbb_AAAAAA',
    'username': 'bbbb_CCCCC',
    'profile_link': 'http://www.youtube.com/user/bbbb_CCCCC',
    'profile_picture_link': 'https://lh5.googleusercontent.com/-BBBBB_o/AAAAAAAAAAI/AAAAAAAAAAA/7dGRX-Z1t6g/s88-c-k/photo.jpg',
}


class TestYoutube(TestService):
    def set_authorization(self, **kwargs):
        # If we don't care about these values, then just hack something in.
        for key in ['token', 'user_id']:
            if not kwargs.get(key):
                kwargs[key] = 'asdf'

        kwargs['service_name'] = 'youtube'
        return super(TestYoutube, self).set_authorization(**kwargs)


class TestYoutubeWeb(TestYoutube):
    @defer.inlineCallbacks
    def setUp(self, *args, **kwargs):
        yield super(TestYoutubeWeb, self).setUp(*args, **kwargs)
        self.service = YoutubeWeb(
            datastore=self.app.db,
        )
        self.daemon = self.service.daemon_object()

        recorder.wrap(self.service.actually_request)
        recorder.wrap(self.daemon.actually_request)
        recorder.wrap(requests.request)
        recorder.play()
        # recorder.record()

    @defer.inlineCallbacks
    def test_recorded_authorize(self):
        # Note: This test requires recorded responses from Lightning Console.
        redir_uri = 'https://lg-local.example.com/id/auth/callback/youtube'

        expected_redirect = compose_url(
            'https://accounts.google.com/o/oauth2/auth',
            query={
                'access_type': 'offline',
                'approval_prompt': 'force',
                'redirect_uri': redir_uri,
                'client_id': self.service.app_info[self.service.environment]['app_id'],
                'scope': 'https://gdata.youtube.com',
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
                'redirect_uri': redirect_uri,
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
            username=AUTHN_TEST_USER['username'],
            profile_link=AUTHN_TEST_USER['profile_link'],
            profile_picture_link=AUTHN_TEST_USER['profile_picture_link'],
        )
        self._test_method_result_keys('profile', profile, expected_profile)

    def test_methods(self):
        self.assertEqual(self.service.methods(), {
            'GET': {
                'account_created_timestamp': 'Returns the time at which the user first posted to to this serivice',
                'most_recent_activity': "The most recent activity on this service's feed",
                'recent_content_authored': "The recent content authored by this user",
                'profile': "Returns this user's profile.",
            },
            'POST': {},
        })

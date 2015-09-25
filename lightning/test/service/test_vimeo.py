from __future__ import absolute_import

from .base import TestService, TestDaemon
from twisted.internet import defer

from lightning.recorder import recorder
from lightning.service.vimeo import VimeoWeb, VimeoDaemon
from lightning.utils import get_arguments_from_redirect

from bs4 import BeautifulSoup
import requests
import time

# This is a 'real user' for use with authorization tests
AUTHN_TEST_USER = {
    'user_id': '1234444',
    'email': 'test@example.com',
    'profile_link': 'http://vimeo.com/user1234444',
    'username': 'user1234444',
    'password': 'testpassword',
    'name': 'Example User',
    'bio': "Filming and Uploading all your Example User, all the time",
    'profile_picture_link': 'https://secure-b.vimeocdn.com/ps/123/1234/1322444_300.jpg',
    'num_albums': 0,
    'num_channels': 0,
    'num_contacts': 0,
    'num_groups': 0,
    'num_likes': 1,
    'num_uploads': 1,
    'num_videos_appears_in': 0,
    'num_videos': 1,
}


class TestVimeo(TestService):
    def set_authorization(self, **kwargs):
        # If we don't care about these values, then just hack something in.
        for key in ['token', 'user_id', 'secret']:
            if not kwargs.get(key):
                kwargs[key] = 'asdf'

        kwargs['service_name'] = 'vimeo'

        return super(TestVimeo, self).set_authorization(**kwargs)


class TestVimeoWeb(TestVimeo):
    @defer.inlineCallbacks
    def setUp(self, *args, **kwargs):
        yield super(TestVimeoWeb, self).setUp(*args, **kwargs)
        self.service = VimeoWeb(
            datastore=self.app.db,
        )
        self.daemon = self.service.daemon_object()

        recorder.wrap(self.service.actually_request)
        recorder.wrap(self.daemon.actually_request)
        recorder.wrap(requests.request)
        # This is a console test, we will never record from here.

    @defer.inlineCallbacks
    def test_recorded_authorize(self):
        # Note: This test requires recorded responses from Lightning Console.
        redir_uri = 'https://lg-local.example.com/id/auth/callback/vimeo'

        # Just match a regex since we'll also get back a requestToken from
        # this since it's an OAuth 1.0 Service.

        expected_redirect = r'https://vimeo.com/oauth/authorize\?oauth_token='

        redirect_uri = yield self.service.start_authorization(
            client_name='testing',
            args={'redirect_uri': redir_uri},
        )
        self.assertRegexpMatches(redirect_uri, expected_redirect)
        auth = yield self.service.finish_authorization(
            client_name='testing',
            # Args are from https://vimeo.com/oauth/request_token response.
            args={
                'redirect_uri': redir_uri,
                'oauth_token': 'e8ace7df95ac81b6a54411185890a3b3',
                'oauth_verifier': '72d28602472e4268345f3f5a0b2125d7d2a5a380',
            },
        )
        oauth_token = auth.token
        user_id = auth.user_id
        oauth_secret = auth.secret

        self.assertEqual(AUTHN_TEST_USER['user_id'], user_id)
        yield self.set_authorization(
            user_id=user_id,
            token=oauth_token,
            secret=oauth_secret
        )

        for method in self.service.daemon_object()._recurring:
            yield self.service.daemon_object().run(
                authorization=self.authorization,
                timestamp=int(time.time()),
                daemon_method=method,
            )

        # Method tests against our actual user.
        profile = yield self.call_method('profile')

        expected_profile = dict(
            name=AUTHN_TEST_USER['name'],
            profile_link=AUTHN_TEST_USER['profile_link'],
            profile_picture_link=AUTHN_TEST_USER['profile_picture_link'],
            bio=AUTHN_TEST_USER['bio'],
            username=AUTHN_TEST_USER['username'],
        )

        self._test_method_result_keys('profile', profile, expected_profile)

        num_albums = yield self.call_method('num_albums')
        self.assertEqual(
            num_albums, {'num': AUTHN_TEST_USER['num_albums']}
        )
        num_channels = yield self.call_method('num_channels')
        self.assertEqual(
            num_channels, {'num': AUTHN_TEST_USER['num_channels']}
        )
        num_contacts = yield self.call_method('num_contacts')
        self.assertEqual(
            num_contacts, {'num': AUTHN_TEST_USER['num_contacts']}
        )
        num_groups = yield self.call_method('num_groups')
        self.assertEqual(
            num_groups, {'num': AUTHN_TEST_USER['num_groups']}
        )
        num_likes = yield self.call_method('num_likes')
        self.assertEqual(
            num_likes, {'num': AUTHN_TEST_USER['num_likes']}
        )
        num_uploads = yield self.call_method('num_uploads')
        self.assertEqual(
            num_uploads, {'num': AUTHN_TEST_USER['num_uploads']}
        )
        num_videos_appears_in = yield self.call_method('num_videos_appears_in')
        self.assertEqual(
            num_videos_appears_in, {'num': AUTHN_TEST_USER['num_videos_appears_in']}
        )
        num_videos = yield self.call_method('num_videos')
        self.assertEqual(
            num_videos, {'num': AUTHN_TEST_USER['num_videos']}
        )


    def test_methods(self):
        self.assertEqual(self.service.methods(), {
            'GET': {
                'account_created_timestamp': 'Returns the time at which the user first posted to to this serivice',
                'most_recent_activity': "The most recent activity on this service's feed",
                'recent_content_authored': "The recent content authored by this user",
                'num_albums': 'Number of albums.',
                'num_albums_interval': 'Number of albums over time.',
                'num_channels': 'Number of channels.',
                'num_channels_interval': 'Number of channels over time.',
                'num_contacts': 'Number of contacts.',
                'num_contacts_interval': 'Number of contacts over time.',
                'num_groups': 'Number of groups.',
                'num_groups_interval': 'Number of groups over time.',
                'num_likes': 'Number of likes.',
                'num_likes_interval': 'Number of likes over time.',
                'num_uploads': 'Number of uploads.',
                'num_uploads_interval': 'Number of uploads over time.',
                'num_videos_appears_in': 'Number of videos appears in.',
                'num_videos_appears_in_interval': 'Number of videos appears in over time.',
                'num_videos': 'Number of videos.',
                'num_videos_interval': 'Number of videos over time.',
                'profile': "Returns this user's profile."
            },
            'POST': {}
        })

    @defer.inlineCallbacks
    def test_num_likes_and_interval(self, **kwargs):
        yield self.set_authorization()

        yield self.write_value(method='num_likes', data='10', timestamp=100)
        rv = yield self.call_method('num_likes')
        self.assertEqual(rv, {'num': 10})
        rv = yield self.call_method('num_likes_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
        ]})

        yield self.write_value(method='num_likes', data='12', timestamp=105)
        rv = yield self.call_method('num_likes')
        self.assertEqual(rv, {'num': 12})
        rv = yield self.call_method('num_likes_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
            {'timestamp': '105', 'num': 12},
        ]})

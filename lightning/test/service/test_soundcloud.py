"Generic docstring A"
from __future__ import absolute_import

from .base import TestService, TestDaemon

from twisted.internet import defer

from lightning.recorder import recorder
from lightning.service.soundcloud import SoundCloudWeb, SoundCloudDaemon
from lightning.utils import compose_url, get_arguments_from_redirect

from bs4 import BeautifulSoup
import json
import re
import requests
import time

# This is a 'real user' for use with authorization tests
AUTHN_TEST_USER = {
    'user_id': '39603642',
    'bio': 'Would be a great singing group, if any of us could sing',
    'email': 'test@example.com',
    'password': 'testpassword',
    'name': 'Example User',
    'username': 'example',
    'profile_link': 'http://soundcloud.com/example',
    'profile_picture_link': 'https://i1.sndcdn.com/avatars-000036944960-sy21ni-large.jpg?9d68d37',
    'num_followers': 1,
    'num_following': 33,
    'num_public_tracks': 7,
    'num_public_playlists': 1,
}


class TestSoundCloud(TestService):
    def set_authorization(self, **kwargs):
        # If we don't care about these values, then just hack something in.
        for key in ['token', 'user_id']:
            if not kwargs.get(key):
                kwargs[key] = 'asdf'

        kwargs['service_name'] = 'soundcloud'
        return super(TestSoundCloud, self).set_authorization(**kwargs)


class TestSoundCloudWeb(TestSoundCloud):
    @defer.inlineCallbacks
    def setUp(self, *args, **kwargs):
        yield super(TestSoundCloudWeb, self).setUp(*args, **kwargs)
        self.service = SoundCloudWeb(
            datastore=self.app.db,
        )
        self.daemon = self.service.daemon_object()

        recorder.wrap(self.service.actually_request)
        recorder.wrap(self.daemon.actually_request)
        recorder.wrap(requests.request)
        recorder.play()

    def tearDown(self):
        super(TestSoundCloudWeb, self).tearDown()

    @defer.inlineCallbacks
    def test_recorded_authorize(self):
        # Note: This test requires recorded responses from Lightning Console.
        redir_uri = 'https://lg-local.example.com/id/auth/callback/soundcloud'

        expected_redirect = compose_url(
            'https://api.soundcloud.com/connect',
            query={
                'redirect_uri': redir_uri,
                'client_id': self.service.app_info[self.service.environment]['app_id'],
                'response_type': 'code',
                'access_type': 'offline',
                'approval_prompt': 'auto',
                'scope': 'non-expiring',
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
            }
        )

        oauth_token = auth.token
        user_id = auth.user_id
        oauth_secret = auth.secret

        self.assertTrue(oauth_token)
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

        profile = yield self.call_method('profile')

        expected_profile = dict(
            name=AUTHN_TEST_USER['name'],
            username=AUTHN_TEST_USER['username'],
            bio=AUTHN_TEST_USER['bio'],
            profile_link=AUTHN_TEST_USER['profile_link'],
            profile_picture_link=AUTHN_TEST_USER['profile_picture_link'],
        )
        self._test_method_result_keys('profile', profile, expected_profile)

        num_followers = yield self.call_method('num_followers')
        self.assertEqual(
            num_followers, {'num': AUTHN_TEST_USER['num_followers']}
        )
        num_following = yield self.call_method('num_following')
        self.assertEqual(
            num_following, {'num': AUTHN_TEST_USER['num_following']}
        )
        num_public_playlists = yield self.call_method('num_public_playlists')
        self.assertEqual(
            num_public_playlists, {'num': AUTHN_TEST_USER['num_public_playlists']}
        )
        num_public_tracks = yield self.call_method('num_public_tracks')
        self.assertEqual(
            num_public_tracks, {'num': AUTHN_TEST_USER['num_public_tracks']}
        )

    def test_methods(self):
        self.assertEqual(self.service.methods(), {
            'GET': {
                'account_created_timestamp': 'Returns the time at which the user first posted to to this serivice',
                'most_recent_activity': "The most recent activity on this service's feed",
                'num_followers': "Returns this user's number of followers.",
                'num_followers_interval': "Returns this user's number of followers over time.",
                'num_following': 'Returns the number of people this user is following.',
                'num_following_interval': 'Returns the number of people this user is following over time.',
                'num_public_playlists': "Returns this user's number of public playlists.",
                'num_public_playlists_interval': "Returns this user's number of public playlists over time.",
                'num_public_tracks': "Returns this user's number of public tracks.",
                'num_public_tracks_interval': "Returns this user's number of public tracks over time.",
                'profile': "Returns this user's profile."},
            'POST': {},
        })

    @defer.inlineCallbacks
    def test_num_followers_and_interval(self, **kwargs):
        yield self.set_authorization()

        yield self.write_value(method='num_followers', data='10', timestamp=100)
        rv = yield self.call_method('num_followers')
        self.assertEqual(rv, {'num': 10})
        rv = yield self.call_method('num_followers_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
        ]})

        yield self.write_value(method='num_followers', data='12', timestamp=105)
        rv = yield self.call_method('num_followers')
        self.assertEqual(rv, {'num': 12})
        rv = yield self.call_method('num_followers_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
            {'timestamp': '105', 'num': 12},
        ]})

    @defer.inlineCallbacks
    def test_num_following_and_interval(self, **kwargs):
        yield self.set_authorization()

        yield self.write_value(method='num_following', data='10', timestamp=100)
        rv = yield self.call_method('num_following')
        self.assertEqual(rv, {'num': 10})
        rv = yield self.call_method('num_following_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
        ]})

        yield self.write_value(method='num_following', data='12', timestamp=105)
        rv = yield self.call_method('num_following')
        self.assertEqual(rv, {'num': 12})
        rv = yield self.call_method('num_following_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
            {'timestamp': '105', 'num': 12},
        ]})

    @defer.inlineCallbacks
    def test_num_public_playlists_and_interval(self, **kwargs):
        yield self.set_authorization()

        yield self.write_value(method='num_public_playlists', data='10', timestamp=100)
        rv = yield self.call_method('num_public_playlists')
        self.assertEqual(rv, {'num': 10})
        rv = yield self.call_method('num_public_playlists_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
        ]})

        yield self.write_value(method='num_public_playlists', data='12', timestamp=105)
        rv = yield self.call_method('num_public_playlists')
        self.assertEqual(rv, {'num': 12})
        rv = yield self.call_method('num_public_playlists_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
            {'timestamp': '105', 'num': 12},
        ]})

    @defer.inlineCallbacks
    def test_num_public_tracks_and_interval(self, **kwargs):
        yield self.set_authorization()

        yield self.write_value(method='num_public_tracks', data='10', timestamp=100)
        rv = yield self.call_method('num_public_tracks')
        self.assertEqual(rv, {'num': 10})
        rv = yield self.call_method('num_public_tracks_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
        ]})

        yield self.write_value(method='num_public_tracks', data='12', timestamp=105)
        rv = yield self.call_method('num_public_tracks')
        self.assertEqual(rv, {'num': 12})
        rv = yield self.call_method('num_public_tracks_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
            {'timestamp': '105', 'num': 12},
        ]})

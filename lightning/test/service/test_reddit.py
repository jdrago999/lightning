from __future__ import absolute_import

from .base import TestService

from lightning.recorder import recorder
from lightning.service.reddit import RedditWeb, RedditDaemon
from lightning.utils import compose_url, get_arguments_from_redirect

from twisted.internet import defer

from bs4 import BeautifulSoup
import requests
import time

# This is a 'real user' for use with authorization tests
AUTHN_TEST_USER = {
    'user_id': 'bbbbb',
    'username': 'example',
    'email': 'test@example.com',
    'password': 'testpassword',
    'name': '',
    'picture': '',
    'profile_link': 'http://www.reddit.com/user/example',
}


class TestReddit(TestService):
    def set_authorization(self, **kwargs):
        # If we don't care about these values, then just hack something in.
        #for key in ['token', 'user_id']:
        #    if not kwargs.get(key):
        #        kwargs[key] = 'asdf'

        kwargs['service_name'] = 'reddit'
        return super(TestReddit, self).set_authorization(**kwargs)


class RedditWebMock(RedditWeb):
    def generate_random_string(self):
        return "foo"


class TestRedditWeb(TestReddit):
    @defer.inlineCallbacks
    def setUp(self):
        yield super(TestRedditWeb, self).setUp()
        self.service = RedditWebMock(
            datastore=self.app.db,
        )
        self.daemon = self.service.daemon_object()

        recorder.wrap(self.service.actually_request)
        recorder.wrap(self.daemon.actually_request)
        recorder.wrap(requests.request)
        # This is a console test, we will never record from here.

    def tearDown(self):
        recorder.save()
        super(TestRedditWeb, self).tearDown()

    @defer.inlineCallbacks
    def test_recorded_authorize(self):
        # Note: This test requires recorded responses from Lightning Console.
        redir_uri = 'https://lg-local.example.com/id/auth/callback/reddit'
        expected_redirect = compose_url(
            'https://ssl.reddit.com/api/v1/authorize',
            query={
                'redirect_uri': redir_uri,
                'client_id': self.service.app_info[self.service.environment]['app_id'],
                'response_type': 'code',
                'scope': 'identity',
                'duration': 'permanent',
                'state': 'foo'
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
                'code': '9cH1ZoHamQ6Zj0AnprFxEbuH2Xc',
                'state': 'foo',
            },
        )
        # XXX Add in check for CommandContext instead of Authorization
        # Do we have a better test for the oauth_token?
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
        expected_profile = dict(
            username=AUTHN_TEST_USER['username'],
            profile_link=AUTHN_TEST_USER['profile_link'],
        )
        self._test_method_result_keys('profile', profile, expected_profile)

    def test_methods(self):
        self.assertEqual(self.service.methods(), {
            'GET': {
                'account_created_timestamp': 'Returns the time at which the user first posted to to this serivice',
                'most_recent_activity': "The most recent activity on this service's feed",
                'recent_content_authored': "The recent content authored by this user",
                'num_comment_karma': "Returns this user's comment karma.",
                'num_comment_karma_interval': "Returns this user's comment karma over time.",
                'num_comments': 'Returns the number of comments this user has submitted.',
                'num_comments_interval': 'Returns the number of comments this user has submitted over time.',
                'num_link_karma': "Returns this user's link karma.",
                'num_link_karma_interval': "Returns this user's link karma over time.",
                'num_links': 'Returns the number of links this user has submitted.',
                'num_links_interval': 'Returns the number of links this user has submitted over time.',
                'profile': "Returns this user's profile."},
            'POST': {},
        })

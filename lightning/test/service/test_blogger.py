"Generic docstring A"
from __future__ import absolute_import

from .base import TestService, TestDaemon

from twisted.internet import defer

from lightning.recorder import recorder
from lightning.service.blogger import BloggerWeb, BloggerDaemon
from lightning.utils import compose_url, get_arguments_from_redirect

import requests
import time

# This is a 'real user' for use with authorization tests
AUTHN_TEST_USER = {
    #'user_id': '37548594',
    'email': 'test@example.com',
    'password': 'testpass',
    'name': 'Larry Test User',
    'username': '',
    'gender': 'male',
    'num_posts': 0,
}


class TestBlogger(TestService):
    def set_authorization(self, **kwargs):
        # If we don't care about these values, then just hack something in.
        for key in ['token', 'user_id']:
            if not kwargs.get(key):
                kwargs[key] = 'asdf'

        kwargs['service_name'] = 'blogger'
        return super(TestBlogger, self).set_authorization(**kwargs)


class TestBloggerWeb(TestBlogger):
    @defer.inlineCallbacks
    def setUp(self, *args, **kwargs):
        yield super(TestBloggerWeb, self).setUp(*args, **kwargs)
        self.service = BloggerWeb(
            datastore=self.app.db,
        )
        self.daemon = self.service.daemon_object()

        recorder.wrap(self.service.actually_request)
        recorder.wrap(self.daemon.actually_request)
        recorder.wrap(requests.request)
        recorder.play()

    def tearDown(self):
        recorder.save()
        super(TestBloggerWeb, self).tearDown()

    @defer.inlineCallbacks
    def test_recorded_authorize(self):
        # Note: This test requires recorded responses from Lightning Console.
        self.skip_me('Needs recorded authorize test')
        redir_uri = 'https://lg-local.example.com/id/auth/callback/blogger'

        expected_redirect = compose_url(
            'https://accounts.google.com/o/oauth2/auth',
            query={
                'access_type': 'offline',
                'approval_prompt': 'force',
                'redirect_uri': redir_uri,
                'client_id': self.service.app_info[self.service.environment]['app_id'],
                'scope': 'https://www.googleapis.com/auth/blogger',
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
            name=AUTHN_TEST_USER['username'],
            username=AUTHN_TEST_USER['username'],
        )
        self._test_method_result_keys('profile', profile, expected_profile)

        num_posts = yield self.call_method('num_posts')
        self.assertEqual(
            num_posts, {'num': AUTHN_TEST_USER['num_posts']}
        )

    def test_methods(self):
        self.assertEqual(self.service.methods(), {
            'GET': {
                'account_created_timestamp': "Returns the approximate (to within a month) time at which the user first posted to this service",
                'most_recent_activity': "The most recent activity on this service's feed",
                'recent_content_authored': "The recent content authored by this user",
                'num_blogs': "Returns this user's number of blogs.",
                'num_blogs_interval': "Returns this user's number of blogs over time.",
                'num_comments_recent_10_posts': 'Returns the total number of comments on the persons 10 most recent posts from each blog.',
                'num_comments_recent_10_posts_interval': 'Returns the total number of comments on the persons 10 most recent posts from each blog over time.',
                'num_pages': "Returns the number of pages on this user's blogs.",
                'num_pages_interval': "Returns the number of pages on this user's blogs over time.",
                'num_posts': "Returns this user's number of posts.",
                'num_posts_interval': "Returns this user's number of posts over time.",
                'profile': "Returns this user's profile."
            },
            'POST': {},
        })

    @defer.inlineCallbacks
    def test_num_posts_and_interval(self, **kwargs):
        yield self.set_authorization()

        yield self.write_value(method='num_posts', data='10', timestamp=100)
        rv = yield self.call_method('num_posts')
        self.assertEqual(rv, {'num': 10})
        rv = yield self.call_method('num_posts_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
        ]})

        yield self.write_value(method='num_posts', data='12', timestamp=105)
        rv = yield self.call_method('num_posts')
        self.assertEqual(rv, {'num': 12})
        rv = yield self.call_method('num_posts_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
            {'timestamp': '105', 'num': 12},
        ]})

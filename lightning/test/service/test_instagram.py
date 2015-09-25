from __future__ import absolute_import

from .base import TestService

from lightning.recorder import recorder
from lightning.service.instagram import InstagramWeb, InstagramDaemon
from lightning.utils import compose_url

from twisted.internet import defer

import requests
import time

# This is a 'real user' for use with authorization tests
AUTHN_TEST_USER = {
    'user_id': '195656741',
    'email': 'example@inflection.com',
    'password': 'testpassword',
    'name': 'Example User',
    'username': 'example',
    'bio': 'Something intelligent here.',
    'picture': 'http://images.ak.instagram.com/profiles/profile_ASSRTR23423324.jpg',
    'profile_link': 'https://instagram.com/example',
}


class InstagramWebMock(InstagramWeb):
    # Override the current time so that it is consistent between test runs
    def current_timestamp(self):
        return 1377637717


class TestInstagram(TestService):
    def set_authorization(self, **kwargs):
        # If we don't care about these values, then just hack something in.
        #for key in ['token', 'user_id']:
        #    if not kwargs.get(key):
        #        kwargs[key] = 'asdf'

        kwargs['service_name'] = 'instagram'
        return super(TestInstagram, self).set_authorization(**kwargs)


class TestInstagramWeb(TestInstagram):
    @defer.inlineCallbacks
    def setUp(self):
        yield super(TestInstagramWeb, self).setUp()
        self.service = InstagramWebMock(
            datastore=self.app.db,
        )
        self.daemon = self.service.daemon_object()
        recorder.wrap(self.service.actually_request)
        recorder.wrap(self.daemon.actually_request)
        recorder.wrap(requests.request)
        recorder.play()

    def tearDown(self):
        #recorder.save()
        super(TestInstagramWeb, self).tearDown()

    @defer.inlineCallbacks
    def test_recorded_authorize(self):
        # Note: This test requires recorded responses from Lightning Console.
        redir_uri = 'https://lg-local.example.com/id/auth/callback/instagram'

        expected_redirect = compose_url(
            'https://api.instagram.com/oauth/authorize',
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
                'code': 'foo'
            },
        )

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
            name=AUTHN_TEST_USER['name'],
            username=AUTHN_TEST_USER['username'],
            bio=AUTHN_TEST_USER['bio'],
            profile_picture_link=AUTHN_TEST_USER['picture'],
            profile_link=AUTHN_TEST_USER['profile_link'],
        )
        self._test_method_result_keys('profile', profile, expected_profile)

        followers = yield self.call_method('num_followers')
        self.assertEqual(followers, {'num': 0}, 'num_followers')

        followed = yield self.call_method('num_followed')
        self.assertEqual(followed, {'num': 4}, 'num_followed')

        media = yield self.call_method('num_media')
        self.assertEqual(media, {'num': 1}, 'num_media')

        comments = yield self.call_method('num_comments')
        self.assertEqual(comments, {'num': 1}, 'num_comments')

        likes = yield self.call_method('num_likes')
        self.assertEqual(likes, {'num': 0}, 'num_likes')


        # Verify that we get the account creation time correct
        result = yield self.call_method('account_created_timestamp')
        got_timestamp = result['timestamp']
        expected_timestamp = 1342548276
        month_in_seconds = 31 * 24 * 60 * 60

        # make sure the timestamp we got is within 31 days of the one we expect
        self.assertLess(abs(got_timestamp - expected_timestamp), month_in_seconds)



# There is no test users through the Instagram API, therefore there is no clear
# way to test the pyres implementation outside of using it within the authorize
# test. There needs to be a better way to do this.
class TestInstagramDaemon(TestInstagram):
    @defer.inlineCallbacks
    def setUp(self):
        yield super(TestInstagramDaemon, self).setUp()
        self.service = InstagramDaemon(
            datastore=self.app.db,
        )

    def test_recurring_methods(self):
        self.assertEqual(self.service.recurring(), {
            'values_from_profile': "Values from profile.",
            'media_counts': "Collects data for num_likes and num_comments.",
            'profile': "Returns this user's profile.",
        })

from __future__ import absolute_import

from .base import TestService, TestDaemon
from twisted.internet import defer

from lightning.recorder import recorder
from lightning.service.etsy import EtsyWeb, EtsyDaemon
from lightning.utils import get_arguments_from_redirect

from bs4 import BeautifulSoup
import requests


# This is a 'real user' for use with authorization tests
AUTHN_TEST_USER = {
    'id': 1234,
    'email': 'test@example.com',
    'profile_link': 'http://etsy.com/people/example',
    'password': 'testpassword',
    'name': 'Example User',
    'username': 'example',
    'bio': "Didn't know Example User is crafty, did you?",
    'profile_picture_url': '',
    'num_favorites': 2,
}


class TestEtsy(TestService):
    def set_authorization(self, **kwargs):
        # If we don't care about these values, then just hack something in.
        for key in ['token', 'user_id', 'secret']:
            if not kwargs.get(key):
                kwargs[key] = 'asdf'

        kwargs['service_name'] = 'etsy'

        return super(TestEtsy, self).set_authorization(**kwargs)


class TestEtsyWeb(TestEtsy):
    @defer.inlineCallbacks
    def setUp(self, *args, **kwargs):
        yield super(TestEtsyWeb, self).setUp(*args, **kwargs)
        self.service = EtsyWeb(
            datastore=self.app.db,
        )
        self.daemon = self.service.daemon_object()
        # TODO: Fix record wrapper around decorated function.
        # recorder.wrap(self.service.actually_request)
        # recorder.wrap(self.daemon.actually_request)
        # recorder.wrap(requests.request)
        # recorder.record()

    def tearDown(self):
        # recorder.save()
        super(TestEtsyWeb, self).tearDown()

    def submit_login_form(self, uri, args):
        login_form = requests.get(
            uri,
            headers=self.headers(),
        )
        self.assertNotEqual(login_form.status_code, 404)

        # Get the request to be the actual request we need for the CSRF bypass
        # in the post() below.
        login_form = self.follow_redirect_until_not(
            login_form,
            r'etsy.com/',
        )
        soup = BeautifulSoup(login_form.content)

        arguments = self.extract_form_fields(soup.form)
        arguments['username'] = args['username']
        arguments['password'] = args['password']

        return requests.post(
            soup.form['action'],
            headers=self.headers(),
            data=arguments,
            cookies=login_form.cookies,
            # We need to trap the redirect back to localhost:5000
            allow_redirects=False,
        )

    @defer.inlineCallbacks
    def test_authorize(self):
        self.skip_me("this test doesn't work yet, although the thing it tests works")
        redir_uri = 'https://lg-local.example.com/id/auth/callback/etsy'

        # Just match a regex since we'll also get back a requestToken from
        # this since it's an OAuth 1.0 Service.

        expected_redirect = r'https://etsy.com/oauth/signin\?oauth_token='

        redirect_uri = yield self.service.start_authorization(
            client_name='testing',
            args={'redirect_uri': redir_uri},
        )
        self.assertRegexpMatches(redirect_uri, expected_redirect)
        response = self.submit_login_form(
            uri=redirect_uri,
            args=dict(
                username=AUTHN_TEST_USER['email'],
                password=AUTHN_TEST_USER['password'],
            ),
        )

        self.assertNotEqual(response.status_code, 404)
        response = self.follow_redirect_until_not(response, r'etsy.com')
        print response.content

        if not self.is_redirect(response.status_code):
            self.display_error(response, "Error Condition")
            return

        args = get_arguments_from_redirect(response)
        auth = yield self.service.finish_authorization(
            client_name='testing',
            args=args,
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

        # Method tests against our actual user.
        profile = yield self.call_method('profile')

        expected_profile = dict(
            name='%s %s' % (AUTHN_TEST_USER['firstName'], AUTHN_TEST_USER['lastName']),
            profile_link=AUTHN_TEST_USER['profile_link'],
            profile_picture_link=AUTHN_TEST_USER['profile_picture_link'],
            headline=AUTHN_TEST_USER['headline'],
            bio='',
            username='',
            email='example@inflection.com',
        )
        self._test_method_result_keys('profile', profile, expected_profile)

        num_favorites = yield self.call_method('num_favorites')
        self.assertEqual(
            num_favorites, {'num': AUTHN_TEST_USER['num_favorites']}
        )

    def test_methods(self):
        self.assertEqual(self.service.methods(), {
            'GET': {
                'account_created_timestamp': 'Returns the time at which the user first posted to to this serivice',
                'most_recent_activity': "The most recent activity on this service's feed",
                'recent_reviews': "The recent reviews of this user",
                'num_active_listings': 'Number of active listings.',
                'num_active_listings_interval': 'Number of active listings over time.',
                'num_favorites': 'Number of favorites.',
                'num_favorites_interval': 'Number of favorites over time.',
                'num_feedback': 'Number of feedback.',
                'num_feedback_interval': 'Number of feedback over time.',
                'num_feedback_written': 'Number of feedback written.',
                'num_feedback_written_interval': 'Number of feedback written over time.',
                'num_sales': 'Number of sales.',
                'num_sales_interval': 'Number of sales over time.',
                'positive_feedback_percentage': 'Pecentage of positive feedback.',
                'positive_feedback_percentage_interval': 'Percentage of positive feedback over time.',
                'profile': "Returns this user's profile."
            },
            'POST': {}
        })

    @defer.inlineCallbacks
    def test_num_favorites_and_interval(self, **kwargs):
        yield self.set_authorization()

        yield self.write_value(method='num_favorites', data='10', timestamp=100)
        rv = yield self.call_method('num_favorites')
        self.assertEqual(rv, {'num': 10})
        rv = yield self.call_method('num_favorites_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
        ]})

        yield self.write_value(method='num_favorites', data='12', timestamp=105)
        rv = yield self.call_method('num_favorites')
        self.assertEqual(rv, {'num': 12})
        rv = yield self.call_method('num_favorites_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
            {'timestamp': '105', 'num': 12},
        ]})


class TestEtsyDaemon(TestDaemon, TestEtsy):
    @defer.inlineCallbacks
    def setUp(self, *args, **kwargs):
        yield super(TestEtsy, self).setUp(*args, **kwargs)
        self.service = EtsyDaemon(
            datastore=self.app.db,
        )

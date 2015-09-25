from __future__ import absolute_import

from .base import TestService

from lightning.recorder import recorder
from lightning.service.wordpress import WordPressWeb, WordPressDaemon
from lightning.utils import compose_url, get_arguments_from_redirect

from twisted.internet import defer

from bs4 import BeautifulSoup
import requests
import time

# This is a 'real user' for use with authorization tests
AUTHN_TEST_USER = {
    'username': 'example',
    'user_id': 1234,
    'email': 'test@example.com',
    'password': 'testpassword',
    'name': 'example',
    'picture': 'http://1.gravatar.com/avatar/160e540d87ea42dab318b7c9e89f5839?s=96&d=identicon&r=G',
    'profile_link': 'http://en.gravatar.com/example',
}


class TestWordPress(TestService):
    def set_authorization(self, **kwargs):
        # If we don't care about these values, then just hack something in.
        #for key in ['token', 'user_id']:
        #    if not kwargs.get(key):
        #        kwargs[key] = 'asdf'

        kwargs['service_name'] = 'wordpress'
        return super(TestWordPress, self).set_authorization(**kwargs)


class TestWordPressWeb(TestWordPress):
    @defer.inlineCallbacks
    def setUp(self):
        yield super(TestWordPressWeb, self).setUp()
        self.service = WordPressWeb(
            datastore=self.app.db,
        )
        self.daemon = self.service.daemon_object()
        # TODO: Fix bug with playback
        # recorder.wrap(self.service.actually_request)
        # recorder.wrap(self.daemon.actually_request)
        # recorder.wrap(requests.request)
        # recorder.record()

    def tearDown(self):
        # recorder.save()
        super(TestWordPressWeb, self).tearDown()

    def submit_login_form(self, uri, args):
        login_form = requests.get(
            uri,
            headers=self.headers(),
            allow_redirects=False,
        )

      # Get the request to be the actual request we need for the CSRF bypass
        # in the post() below.
        login_form = self.follow_redirect_until_not(login_form, r'wordpress.com/')
        #print "login_form: %s" % login_form.content
        soup = BeautifulSoup(login_form.content)
        arguments = self.extract_form_fields(soup.form)

        arguments['log'] = args['username']
        arguments['pwd'] = args['password']

        return requests.post(
            soup.form['action'],
            headers=self.headers(referer=login_form.request.url),
            data=arguments,
            cookies=login_form.cookies,
            # We need to trap the redirect back to localhost:5000
            allow_redirects=False,
        )

    def test_methods(self):
        self.assertEqual(self.service.methods(), {
            'GET': {
                'account_created_timestamp': "Returns the approximate (to within a month) time at which the user first posted to this service",
                'most_recent_activity': "The most recent activity on this service's feed",
                'recent_content_authored': "The recent content authored by this user",
                'num_comments_recent_10_posts': 'Returns the total number of comments on the persons 10 most recent posts.',
                'num_comments_recent_10_posts_interval': 'Returns the total number of comments on the persons 10 most recent posts over time.',
                'num_likes': 'Returns the number of posts this person likes.',
                'num_likes_interval': 'Returns the number of posts this person likes over time.',
                'num_posts': 'Returns the number of blog posts this person has made.',
                'num_posts_interval': 'Returns the number of blog posts this person has made over time.',
                'profile': "Returns this user's profile."
            },
            'POST': {}
        })

    @defer.inlineCallbacks
    def test_authorize(self):
        self.skip_me('Need to fix bug with playback of responses')
        redir_uri = 'https://lg-local.example.com/id/auth/callback/wordpress'

        expected_redirect = compose_url(
            'https://public-api.wordpress.com/oauth2/authorize',
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

        response = self.submit_login_form(
            uri=expected_redirect,
            args=dict(
                username=AUTHN_TEST_USER['username'],
                password=AUTHN_TEST_USER['password'],
            ),
        )

        login_cookies = response.cookies
        response = self.follow_redirect_until_not(response, r'wordpress.com/')

        # Now, submit the authorize the authorize page
        soup = BeautifulSoup(response.content)
        arguments = self.extract_form_fields(soup.form)
        url = compose_url(soup.form['action'], query=arguments)

        response = requests.get(
            url,
            headers=self.headers(referer=response.request.url),
            cookies=login_cookies,
            # We need to trap the redirect back to localhost:5000
            allow_redirects=False,
        )

        response = self.follow_redirect_until_not(response, r'wordpress.com/')

        if not self.is_redirect(response.status_code):
            self.display_error(response, 'Error Condition')
            return

        args = get_arguments_from_redirect(response)
        args['redirect_uri'] = redir_uri

        user_auth = yield self.service.finish_authorization(
            client_name='testing',
            args=args,
        )
        # XXX Add in check for CommandContext instead of Authorization
        # Do we have a better test for the oauth_token?
        self.assertTrue(user_auth.token)
        self.assertEqual(AUTHN_TEST_USER['user_id'], user_auth.user_id)

        # Verify this authorization is any good.
        yield self.set_authorization(
            user_id=user_auth.user_id, token=user_auth.token,
        )

        yield self.daemon.run(
            authorization=self.authorization,
            timestamp=int(time.time()),
        )

        profile = yield self.call_method('profile')
        expected_profile = dict(
            name=AUTHN_TEST_USER['name'],
            username=AUTHN_TEST_USER['username'],
            email=AUTHN_TEST_USER['email'],
            profile_picture_link=AUTHN_TEST_USER['picture'],
            profile_link=AUTHN_TEST_USER['profile_link'],
        )
        self._test_method_result_keys('profile', profile, expected_profile)

        # followers = yield self.call_method('num_followers')
        # self.assertEqual(followers, {'num': 0}, 'num_followers')


# There is no test users through the WordPress API, therefore there is no clear
# way to test the pyres implementation outside of using it within the authorize
# test. There needs to be a better way to do this.
class TestWordPressDaemon(TestWordPress):
    @defer.inlineCallbacks
    def setUp(self):
        yield super(TestWordPressDaemon, self).setUp()
        self.service = WordPressDaemon(
            datastore=self.app.db,
        )

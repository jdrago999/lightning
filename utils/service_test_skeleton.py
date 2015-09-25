"Generic docstring A"
from __future__ import absolute_import

from .base import TestService, TestDaemon

from cyclone.web import HTTPError
from twisted.internet import defer

from lightning.command import Command, CommandContext, RetryCommand, EnqueueCommand, CommandContextException
from lightning.error import RequestError
from lightning.service.SERVICENAME import SERVICEWeb, SERVICEDaemon
from lightning.utils import compose_url, get_arguments_from_redirect

from bs4 import BeautifulSoup
import json
import re
import requests
import time

# This is a 'real user' for use with authorization tests
AUTHN_TEST_USER = {
    'email': 'example@example.com',
    'password': 'example1234',
    'username': 'example.lightning',
    'name': 'Example User Lightning',
    'user_id': '1234',
    'link': 'http://www.facebook.com/example.lightning',
    'gender': 'male',
}

class TestSERVICE(TestService):
    def set_authorization(self, **kwargs):
        # If we don't care about these values, then just hack something in.
        for key in ['token', 'user_id']:
            if not kwargs.get(key):
                kwargs[key] = 'asdf'

        kwargs['service_name'] = 'SERVICENAME'
        return super(TestSERVICE, self).set_authorization(**kwargs)

class TestSERVICEWeb(TestSERVICE):
    @defer.inlineCallbacks
    def setUp(self, *args, **kwargs):
        yield super(TestSERVICEWeb, self).setUp(*args, **kwargs)
        self.service = SERVICEWeb(
            datastore=self.app.db,
        )

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
            r'twitter.com/',
        )
        soup = BeautifulSoup(login_form.content)

        arguments = self.extract_form_fields(soup.form)
        arguments['session[username_or_email]'] = args['username']
        arguments['session[password]'] = args['password']
        del arguments['cancel']

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
        redir_uri = 'https://lg-local.example.com/id/auth/callback/SERVICENAME'

        # Just match a regex since we'll also get back a requestToken from
        # this since it's an OAuth 1.0 Service.
        expected_redirect = r'https://api.twitter.com/oauth/authorize\?oauth_token='

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
        response = self.follow_redirect_until_not(response, r'twitter.com')

        # So, Twitter's super cool and doesn't 302 us.
        # Instead, we get back a 200 page with a meta http-equiv refresh set
        # to our callback page. Here, we parse this page and grab the args.
        # This is pretty brittle.
        self.assertEqual(response.status_code, 200)
        soup = BeautifulSoup(response.content)
        meta_redir = soup.findAll('meta', {'http-equiv': 'refresh'})[0]
        # Strip off the URL and get the QS
        meta_qs = meta_redir['content'][6:].split('?')[1]
        args = dict(parse_qsl(meta_qs))

        try:
            auth = yield self.service.finish_authorization(
                client_name='testing',
                args=args,
            )
        except CommandContextException as exc:
            print exc.context().next_command.context['msg']
            raise

        oauth_token = auth.token()
        user_id = auth.user_id()
        oauth_secret = auth.secret()

        self.assertEqual(AUTHN_TEST_USER['id'], user_id)
        yield self.set_authorization(
            user_id=user_id,
            token=oauth_token,
            secret=oauth_secret
        )

        yield self.service.daemon_object().run(
            authorization=self.authorization,
            timestamp=int(time.time()),
        )

        profile = yield self.call_method('profile')

        expected_profile = dict(
            name=AUTHN_TEST_USER['name'],
            username=AUTHN_TEST_USER['username'],
            bio=AUTHN_TEST_USER['bio'],
            profile_link=AUTHN_TEST_USER['profile_link'],
            profile_picture_link=AUTHN_TEST_USER['profile_picture_url'],
        )
        self._test_method_result_keys('profile', profile, expected_profile)

        num_friends = yield self.call_method('num_friends')
        self.assertEqual(
            num_friends, {'num': AUTHN_TEST_USER['num_friends']}
        )

    def test_methods(self):
        self.assertEqual(self.service.methods(), {
            'most_recent_activity': "The most recent activity on this service's feed",
            'profile': "Returns this user's profile.",
            'num_friends': 'Number of friends',
            'num_friends_interval': 'Number of friends over time',
        })

    @defer.inlineCallbacks
    def test_num_friends_and_interval(self, **kwargs):
        yield self.set_authorization()

        yield self.write_value(method='num_friends', data='10', timestamp=100)
        rv = yield self.call_method('num_friends')
        self.assertEqual(rv, {'num': 10})
        rv = yield self.call_method('num_friends_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
        ]})

        yield self.write_value(method='num_friends', data='12', timestamp=105)
        rv = yield self.call_method('num_friends')
        self.assertEqual(rv, {'num': 12})
        rv = yield self.call_method('num_friends_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
            {'timestamp': '105', 'num': 12},
        ]})

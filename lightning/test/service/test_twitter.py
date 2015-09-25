from __future__ import absolute_import

from .base import TestService, TestDaemon
from twisted.internet import defer

from lightning.service.twitter import TwitterWeb, TwitterDaemon
from lightning.recorder import recorder

from bs4 import BeautifulSoup
import requests
import time
from urlparse import parse_qsl

# This is a 'real user' for use with authorization tests
AUTHN_TEST_USER = {
    'id': '12344',
    'email': 'test@example.com',
    'profile_link': 'http://twitter.com/Example1',
    'password': 'testpassword',
    'name': 'Example',
    'username': 'example',
    'bio': 'An elite engineering team.',
    'profile_picture_link': ('http://a0.twimg.com/profile_images/12344/'
        'com_BusinessCat____12244_normal.png'),
    'num_following': 2,
    'num_followers': 1,
    'num_tweets': 3,
    'num_favorites': 1,
    'num_listed': 0,
    'num_follow_requests': 0,
    'num_retweets': 1,
    'num_mentions': 1,
    'num_direct_messages': 0,
    'account_created_timestamp': 1346866244,
}


class TestTwitter(TestService):
    def set_authorization(self, **kwargs):
        # If we don't care about these values, then just hack something in.
        for key in ['token', 'user_id', 'secret']:
            if not kwargs.get(key):
                kwargs[key] = 'asdf'

        kwargs['service_name'] = 'twitter'

        return super(TestTwitter, self).set_authorization(**kwargs)


class TestTwitterWeb(TestTwitter):
    @defer.inlineCallbacks
    def setUp(self, *args, **kwargs):
        yield super(TestTwitterWeb, self).setUp(*args, **kwargs)
        self.service = TwitterWeb(
            datastore=self.app.db,
        )
        self.daemon = self.service.daemon_object()

        recorder.wrap(self.service.actually_request)
        recorder.wrap(self.daemon.actually_request)
        recorder.wrap(requests.request)
        # recorder.record()

    def tearDown(self):
        recorder.save()
        super(TestTwitterWeb, self).tearDown()

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
        redir_uri = 'https://lg-local.example.com/id/auth/callback/twitter'

        # Just match a regex since we'll also get back a requestToken from
        # this since it's an OAuth 1.0 Service.

        expected_redirect = r'https://api.twitter.com/oauth/authorize\?oauth_token='

        # resp = self.get_and_verify(
        #     path='/auth',
        #     args=dict(service='twitter', redirect_uri=redir_uri),
        #     response_code=200,
        # )
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

        auth = yield self.service.finish_authorization(
            client_name='testing',
            args=args,
        )

        oauth_token = auth.token
        user_id = auth.user_id
        oauth_secret = auth.secret

        self.assertEqual(AUTHN_TEST_USER['id'], user_id)
        yield self.set_authorization(
            user_id=user_id,
            token=oauth_token,
            secret=oauth_secret
        )

        yield self.run_daemon()
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
        num_tweets = yield self.call_method('num_tweets')
        self.assertEqual(
            num_tweets, {'num': AUTHN_TEST_USER['num_tweets']}
        )
        num_favorites = yield self.call_method('num_favorites')
        self.assertEqual(
            num_favorites, {'num': AUTHN_TEST_USER['num_favorites']}
        )
        num_listed = yield self.call_method('num_listed')
        self.assertEqual(
            num_listed, {'num': AUTHN_TEST_USER['num_listed']}
        )
        num_follow_requests = yield self.call_method('num_follow_requests')
        self.assertEqual(
            num_follow_requests, {'num': AUTHN_TEST_USER['num_follow_requests']}
        )
        num_retweets = yield self.call_method('num_retweets')
        self.assertEqual(
            num_retweets, {'num': AUTHN_TEST_USER['num_retweets']}
        )
        num_mentions = yield self.call_method('num_mentions')
        self.assertEqual(
            num_mentions, {'num': AUTHN_TEST_USER['num_mentions']}
        )
        num_direct_messages = yield self.call_method('num_direct_messages')
        self.assertEqual(
            num_direct_messages, {'num': AUTHN_TEST_USER['num_direct_messages']}
        )
        account_created_timestamp = yield self.call_method('account_created_timestamp')
        self.assertEqual(
            account_created_timestamp, {'timestamp': AUTHN_TEST_USER['account_created_timestamp']}
        )

    def test_methods(self):
        self.assertEqual(self.service.methods(), {
            'GET': {
                'most_recent_activity': "The most recent activity on this service's feed",
                'profile': "Returns this user's profile.",
                'person_mentioned': 'Retrieve data for all mentions, storing the results granularly.',
                'num_followers': 'Number of followers',
                'num_followers_interval': 'Number of followers over time',
                'num_following': 'Number of users followed',
                'num_following_interval': 'Number of users followed over time',
                'num_tweets': 'Number of tweets',
                'num_tweets_interval': 'Number of tweets over time',
                'num_favorites': 'Number of favorites',
                'num_favorites_interval': 'Number of favorites over time',
                'num_listed': 'Number of times listed',
                'num_listed_interval': 'Number of times listed over time',
                'num_follow_requests': 'Number of follow requests',
                'num_follow_requests_interval': 'Number of follow requests over time',
                'num_retweets': 'Number of retweets',
                'num_retweets_interval': 'Number of retweets over time',
                'num_mentions': 'Number of mentions',
                'num_mentions_interval': 'Number of mentions over time',
                'num_direct_messages': 'Number of direct_messages',
                'num_direct_messages_interval': 'Number of direct_messages over time',
                'account_created_timestamp': 'Returns the timestamp this user account was created on',
            },
            'POST': {
                'create_tweet': 'Create a tweet on behalf of a user',
                'favorite_tweet': 'Favorite a tweet on behalf of a user',
                'unfavorite_tweet': 'Unfavorite a tweet on behalf of a user',
                'retweet_tweet': 'Retweet a tweet on behalf of a user',
                'reply_to_tweet': 'Reply to a tweet on behalf of a user',
            },
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
    def test_num_tweets_and_interval(self, **kwargs):
        yield self.set_authorization()

        yield self.write_value(method='num_tweets', data='10', timestamp=100)
        rv = yield self.call_method('num_tweets')
        self.assertEqual(rv, {'num': 10})
        rv = yield self.call_method('num_tweets_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
        ]})

        yield self.write_value(method='num_tweets', data='12', timestamp=105)
        rv = yield self.call_method('num_tweets')
        self.assertEqual(rv, {'num': 12})
        rv = yield self.call_method('num_tweets_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
            {'timestamp': '105', 'num': 12},
        ]})

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

    @defer.inlineCallbacks
    def test_num_listed_and_interval(self, **kwargs):
        yield self.set_authorization()

        yield self.write_value(method='num_listed', data='10', timestamp=100)
        rv = yield self.call_method('num_listed')
        self.assertEqual(rv, {'num': 10})
        rv = yield self.call_method('num_listed_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
        ]})

        yield self.write_value(method='num_listed', data='12', timestamp=105)
        rv = yield self.call_method('num_listed')
        self.assertEqual(rv, {'num': 12})
        rv = yield self.call_method('num_listed_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
            {'timestamp': '105', 'num': 12},
        ]})

    @defer.inlineCallbacks
    def test_num_follow_requests_and_interval(self, **kwargs):
        yield self.set_authorization()

        yield self.write_value(method='num_follow_requests', data='10', timestamp=100)
        rv = yield self.call_method('num_follow_requests')
        self.assertEqual(rv, {'num': 10})
        rv = yield self.call_method('num_follow_requests_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
        ]})

        yield self.write_value(method='num_follow_requests', data='12', timestamp=105)
        rv = yield self.call_method('num_follow_requests')
        self.assertEqual(rv, {'num': 12})
        rv = yield self.call_method('num_follow_requests_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
            {'timestamp': '105', 'num': 12},
        ]})

    @defer.inlineCallbacks
    def test_num_retweets_and_interval(self, **kwargs):
        yield self.set_authorization()

        yield self.write_value(method='num_retweets', data='10', timestamp=100)
        rv = yield self.call_method('num_retweets')
        self.assertEqual(rv, {'num': 10})
        rv = yield self.call_method('num_retweets_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
        ]})

        yield self.write_value(method='num_retweets', data='12', timestamp=105)
        rv = yield self.call_method('num_retweets')
        self.assertEqual(rv, {'num': 12})
        rv = yield self.call_method('num_retweets_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
            {'timestamp': '105', 'num': 12},
        ]})

    @defer.inlineCallbacks
    def test_num_mentions_and_interval(self, **kwargs):
        yield self.set_authorization()

        yield self.write_value(method='num_mentions', data='10', timestamp=100)
        rv = yield self.call_method('num_mentions')
        self.assertEqual(rv, {'num': 10})
        rv = yield self.call_method('num_mentions_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
        ]})

        yield self.write_value(method='num_mentions', data='12', timestamp=105)
        rv = yield self.call_method('num_mentions')
        self.assertEqual(rv, {'num': 12})
        rv = yield self.call_method('num_mentions_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
            {'timestamp': '105', 'num': 12},
        ]})

    @defer.inlineCallbacks
    def test_num_direct_messages_and_interval(self, **kwargs):
        yield self.set_authorization()

        yield self.write_value(method='num_direct_messages', data='10', timestamp=100)
        rv = yield self.call_method('num_direct_messages')
        self.assertEqual(rv, {'num': 10})
        rv = yield self.call_method('num_direct_messages_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
        ]})

        yield self.write_value(method='num_direct_messages', data='12', timestamp=105)
        rv = yield self.call_method('num_direct_messages')
        self.assertEqual(rv, {'num': 12})
        rv = yield self.call_method('num_direct_messages_interval',
            arguments=dict(start=90, end=110),
        )
        self.assertEqual(rv, {'data': [
            {'timestamp': '100', 'num': 10},
            {'timestamp': '105', 'num': 12},
        ]})


class TestTwitterDaemon(TestDaemon, TestTwitter):
    @defer.inlineCallbacks
    def setUp(self, *args, **kwargs):
        yield super(TestTwitter, self).setUp(*args, **kwargs)
        self.service = TwitterDaemon(
            datastore=self.app.db,
        )

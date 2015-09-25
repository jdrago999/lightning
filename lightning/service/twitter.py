"Generic docstring A"
from __future__ import absolute_import

from lightning.service.base import (
    ServiceOAuth1, Daemon, Web, service_class, recurring, daemon_class,
    api_method, enqueue_delta, check_account_created_timestamp, Profile
)

from lightning.model.authorization import Authz
from lightning.model.stream_event import StreamEvent
from lightning.error import Error, AuthError, LightningError

from twisted.internet import defer

import calendar
import rfc822
import sys
from time import time
import urllib
import urlparse


class Twitter(ServiceOAuth1):
    """Twitter OAuth1.0a API for Lightning.
    Lightning's implementation of Twitter's REST API.
    API:
        https://developer.twitter.com/rest
    """
    name = 'twitter'

    def __init__(self, *args, **kwargs):
        """Create a new Twitter service object.
        Attributes:
            app_info: dict, API keys and secrets per environment.
            domain: string, Domain the service hits.
            base_url: string, URL of domain with correct protocol.
            auth_url: string, URL used to build authorization URL.
            access_token_url: string, URL used to obtain an access_token.
            endpoint_url: string, URL used to call service methods.
        """
        super(Twitter, self).__init__(*args, **kwargs)

        self.app_info = {
            'local': {
                'app_id': 'fake',
                'app_secret': 'fake',
            },
            'beta': {
                'app_id': 'fake',
                'app_secret': 'fake',
            },
            'preprod': {
                'app_id': 'fake',
                'app_secret': 'fake',
            },
            'prod': {
                'app_id': 'fake',
                'app_secret': 'fake',
            },
        }
        self.app_info['dev'] = self.app_info['local']

        self.domain = 'api.twitter.com'
        self.base_url = 'https://' + self.domain
        self.auth_url = self.base_url + '/oauth/request_token'
        self.access_token_url = self.base_url + '/oauth/access_token'
        self.endpoint_url = self.base_url + '/1.1'

        self.oauth_version = '1.0'
        self.oauth_signature_method = 'HMAC-SHA1'

        self.status_errors.update({
            403: Error.DUPLICATE_POST,
            429: Error.RATE_LIMITED,
        })

    def request_with_paging(self, path, callback, args, **kwargs):
        """
        This returns a Deferred that knows how to page through results.

        The assumption is that the callback is doing some sort of useful work,
        likely with an accumulator of some sort.

        Note: This request_with_paging is different from the other services
        because Twitter doesn't provide pagination URLs in its responses. So,
        we must provide our own pagination using max_id and since_id. (No limit
        or offset, for good reason. For a detailed explanation with pictures,
        q.v. https://dev.twitter.com/docs/working-with-timelines).
        """

        stopback = kwargs.get('stopback', lambda: True)

        max_id = [sys.maxint]

        def collect_data(resp):
            "call the callback, in a deferred safe way, and return the original reposne for the pager to pick up"
            return defer.maybeDeferred(callback, resp).addCallback(lambda ign: resp)

        def pager(response):
            """process this page of results and if needed, get the next page and fire off a callback and pager
            to process it"""

            if stopback() or not response:
                return

            # XXX Add directionality here
            for item in response:
                item_id = int(item.get('id_str', sys.maxint))
                if item_id < max_id[0]:
                    max_id[0] = item_id

            args['max_id'] = max_id[0] - 1
            return self.request(path=path, args=args, **kwargs).addCallback(collect_data).addCallback(pager)

        return self.request(path=path, args=args, **kwargs).addCallback(collect_data).addCallback(pager)

    def profile_link(self, username):
        if username:
            return 'http://twitter.com/%s' % username
        return None

    ############################################
    # Below is the list of functions required to support reading the feed
    ############################################

    def get_feed_url(self, **kwargs):
        'The feed URL'
        # Be careful, extra slash here would give same results, but _different_
        # rate limit.
        return 'statuses/user_timeline.json'

    def get_feed_args(self, **kwargs):
        'The feed args'
        return {'include_rts': 0}  # Disable retweets for now.

    def get_feed_limit(self, limit):
        'Return the limit in the right format'
        return {'count': limit}

    def get_feed_timestamp(self, **kwargs):
        'Return the timestamp in the right format'
        timestamp = kwargs.get('timestamp', int(time()))
        if kwargs.get('forward', False):
            return {'since': timestamp}
        else:
            return {'until': timestamp}

    def parse_post(self, post, **kwargs):
        "Parse a feed post"
        # Build author
        user = post.get('user', {})
        username = user.get('screen_name')

        author = {
            'user_id': user.get('id_str', str(user.get('id', ''))),
            'name': user.get('name'),
            'username': username,
            'profile_link': self.profile_link(username),
            'profile_picture_link': user.get('profile_image_url_https')
        }

        # Build activity
        from xml.sax.saxutils import unescape
        activity = {
            'story': unescape(post.get('text', ''))
        }

        if post.get('entities'):
            additional_users = []
            for mention in post['entities'].get('user_mentions', []):
                mention_username = mention.get('screen_name')
                additional_users.append({
                    'user_id': str(mention.get('id')),
                    'name': mention.get('name'),
                    'username': mention_username,
                    'profile_link': self.profile_link(mention_username)
                })
            if additional_users:
                activity['additional_users'] = additional_users

        # Build metadata
        if author['user_id'] == kwargs['authorization'].user_id:
            is_echo = 0
        else:
            is_echo = 1

        metadata = {
            'post_id': post.get('id_str', str(post.get('id'))),
            'timestamp': calendar.timegm(rfc822.parsedate(post['created_at'])),
            'service': self.name,
            'is_private': 0,
            'is_echo': is_echo,
        }

        return StreamEvent(
            metadata=metadata,
            author=author,
            activity=activity,
        )

    # TO HERE
    ############################################

@daemon_class
class TwitterDaemon(Twitter, Daemon):
    """Twitter Daemon OAuth1 API for Lightning"""

    @recurring
    def values_from_profile(self, **kwargs):
        """User's Profile
        Returns:
            Profile of currently authenticated user.
        """
        def write_additional_values(response):
            return defer.gatherResults([
                self.write_datum(method=method, data=datum, **kwargs)
                for method, datum in {
                    'num_followers': response['followers_count'],
                    'num_following': response['friends_count'],
                    'num_tweets': response['statuses_count'],
                    # British spelling is correct in what we receive.
                    'num_favorites': response['favourites_count'],
                    'num_listed': response['listed_count'],
                }.iteritems()
            ]).addCallback(lambda ign: None)

        return self.request(
            path='account/verify_credentials.json',
            **kwargs
        ).addCallback(write_additional_values)

    @recurring
    def num_follow_requests(self, **kwargs):
        """Number of follow requests
        Returns:
            Number of follow requests for this user.
        """
        return self.request(
            path='friendships/incoming.json',
            with_sum='ids',
            **kwargs
        )

    @recurring
    def num_retweets(self, **kwargs):
        """Number of retweets"""
        total = [0]

        def summate(tweets):
            for tweet in tweets:
                other_users_tweet = tweet.get('retweeted_status', False)
                if not other_users_tweet:
                    total[0] += tweet.get('retweet_count', 0)
        args = dict(
            count=200,
            trim_user='true',
            include_entities='false',
            contributor_details='false',
        )

        return self.request_with_paging(
            path='statuses/user_timeline.json',
            callback=summate,
            stopback=lambda: False,
            args=args,
            **kwargs
        ).addCallback(lambda _: {'num': total[0]})

    @recurring
    def num_mentions(self, **kwargs):
        """Number of mentions"""
        total = [0]

        def summate(mentions):
            total[0] += len(mentions)

        args = dict(
            count=200,
            trim_user='true',
            include_entities='false',
            contributor_details='false',
        )
        return self.request_with_paging(
            path='statuses/mentions_timeline.json',
            callback=summate,
            stopback=lambda: False,
            args=args,
            **kwargs
        ).addCallback(lambda _: {'num': total[0]})

    @recurring
    def person_metioned(self, **kwargs):
        "Retrieve data for all mentions, storing the results granularly."
        def write_granular_data(data):
            if not len(data):
                return

            return defer.gatherResults([
                # id, fromid, time, text
                self.datastore.write_granular_datum(
                    method='mention',
                    item_id=datum['id'],
                    actor_id=datum['user']['id'],
                    timestamp=calendar.timegm(
                        rfc822.parsedate(datum['created_at'])
                    ),
                    authorization=kwargs['authorization'],
                ) for datum in data
            ])

        def handle_results(data):
            if not len(data):
                return

            return self.datastore.find_unwritten_granular_data(
                method='mention', data=data, **kwargs
            ).addCallback(
                write_granular_data
            )

        # TODO: Add support for min_id
        args = dict(
            count=200,
            trim_user='true',
            include_entities='false',
            contributor_details='false',
        )
        return self.request_with_paging(
            path='statuses/mentions_timeline.json',
            callback=handle_results,
            args=args,
            **kwargs
        )

    @recurring
    def num_direct_messages(self, **kwargs):
        """Number of direct_messages"""
        total = [0]

        def summate(messages):
            total[0] += len(messages)

        args = dict(
            count=200,
            include_entities='false',
            skip_status='true',
        )
        return self.request_with_paging(
            path='direct_messages.json',
            callback=summate,
            args=args,
            **kwargs
        ).addCallback(lambda _: {'num': total[0]})

    @recurring
    @enqueue_delta(days=30)
    def profile(self, **kwargs):
        "Returns this user's profile."
        def build_profile(response):
            response = response[0]
            return Profile(
                name=response.get('name'),
                profile_picture_link=response.get('profile_image_url'),
                profile_link='http://twitter.com/%s' % response['screen_name'],
                bio=response.get('description'),
                username=response.get('screen_name'),
            )

        args = {
            'user_id': kwargs.get('path', kwargs['authorization'].user_id),
        }

        # Needed for person_mentioned to work properly.
        if kwargs.get('path'):
            del(kwargs['path'])

        return self.request(
            path='users/lookup.json',
            args=args,
            **kwargs
        ).addCallback(build_profile)


@service_class
class TwitterWeb(Twitter, Web):
    """Twitter Web OAuth1 API for Lightning"""
    daemon_class = TwitterDaemon

    @defer.inlineCallbacks
    def start_authorization(self, client_name, args):
        """Start the authorization process.
        Get authorization URL.
        Args:
            redirect_uri: string, URL to redirect to after request.
        """
        try:
            self.ensure_arguments(['redirect_uri'], args)

            resp = yield self.request(
                full_url=self.auth_url,
                args={
                    'oauth_callback': args['redirect_uri'],
                },
                no_parse=True,
            )

            result = urlparse.parse_qs(resp.body)
            request_token = result['oauth_token'][0]
            oauth_token_secret = result['oauth_token_secret'][0]
            yield self.datastore.store_inflight_authz(
                service_name=self.name,
                request_token=request_token,
                secret=oauth_token_secret,
            )
        except (ValueError, LightningError) as exc:
            raise AuthError(exc.message)

        defer.returnValue(
            self.base_url +
            '/oauth/authorize?oauth_token=' +
            request_token
        )

    @defer.inlineCallbacks
    def finish_authorization(self, client_name, args):
        """Complete last step to get an oauth_token.
        Args:
            oauth_verifier: string, verifier received from service after
                start_authorization step.
        """
        try:
            self.ensure_arguments(['oauth_token', 'oauth_verifier'], args)

            inflight_authz = yield self.datastore.retrieve_inflight_authz(
                service_name=self.name,
                request_token=args['oauth_token'],
            )
            if not inflight_authz:
                raise AuthError('No inflight_authz for %s: %s' % (self.name, args['oauth_token']))

            resp = yield self.request(
                method='POST',
                full_url=self.access_token_url,
                body=urllib.urlencode({
                    'oauth_verifier': args['oauth_verifier'],
                }),
                token=inflight_authz.request_token,
                secret=inflight_authz.secret,
                no_parse=True,
            )

            response = urlparse.parse_qs(resp.body, strict_parsing=True)
            token = response['oauth_token'][0]
            secret = response['oauth_token_secret'][0]
            resp = yield self.request(
                path='account/verify_credentials.json',
                token=token,
                secret=secret,
            )

            authorization = yield Authz(
                client_name=client_name,
                service_name=self.name,
                token=token,
                user_id=resp['id'],
                secret=secret,
            ).set_token(self.datastore)

        except (ValueError, LightningError) as exc:
            raise AuthError(exc.message)

        defer.returnValue(authorization)

    @defer.inlineCallbacks
    @api_method('POST')
    def create_tweet(self, **kwargs):
        "Create a tweet on behalf of a user"
        self.ensure_arguments(['tweet'], kwargs['arguments'])

        kwargs['user_id'] = kwargs['authorization'].user_id
        kwargs['uuid'] = kwargs['authorization'].uuid

        kwargs['body'] = urllib.urlencode({
            'status': kwargs['arguments']['tweet'],
        })

        kwargs['method'] = 'POST'

        yield self.request(path='statuses/update.json', **kwargs)

        defer.returnValue({'success': 'Posted tweet'})

    @defer.inlineCallbacks
    @api_method('POST')
    def favorite_tweet(self, **kwargs):
        "Favorite a tweet on behalf of a user"
        self.ensure_arguments(['tweet_id'], kwargs['arguments'])

        kwargs['user_id'] = kwargs['authorization'].user_id
        kwargs['uuid'] = kwargs['authorization'].uuid

        kwargs['body'] = urllib.urlencode({
            'id': kwargs['arguments']['tweet_id'],
        })

        kwargs['method'] = 'POST'

        yield self.request(path='favorites/create.json', **kwargs)
        defer.returnValue({'success': 'Favorited tweet'})

    @defer.inlineCallbacks
    @api_method('POST')
    def unfavorite_tweet(self, **kwargs):
        "Unfavorite a tweet on behalf of a user"
        self.ensure_arguments(['tweet_id'], kwargs['arguments'])

        kwargs['user_id'] = kwargs['authorization'].user_id
        kwargs['uuid'] = kwargs['authorization'].uuid

        kwargs['body'] = urllib.urlencode({
            'id': kwargs['arguments']['tweet_id'],
        })

        kwargs['method'] = 'POST'

        yield self.request(path='favorites/destroy.json', **kwargs)

        defer.returnValue({'success': 'Unfavorited tweet'})

    @defer.inlineCallbacks
    @api_method('POST')
    def retweet_tweet(self, **kwargs):
        "Retweet a tweet on behalf of a user"
        self.ensure_arguments(['tweet_id'], kwargs['arguments'])

        kwargs['user_id'] = kwargs['authorization'].user_id
        kwargs['uuid'] = kwargs['authorization'].uuid

        kwargs['method'] = 'POST'

        yield self.request(
            path='statuses/retweet/%s.json' % kwargs['arguments']['tweet_id'],
            **kwargs
        )

        defer.returnValue({'success': 'Retweeted tweet'})

    @api_method('GET')
    @check_account_created_timestamp
    def account_created_timestamp(self, **kwargs):
        """Returns the timestamp this user account was created on"""

        def parse_timestamp(resp):
            t = calendar.timegm(rfc822.parsedate(resp['created_at']))

            return {
                'timestamp': t,
            }

        return self.request(
            path='account/verify_credentials.json',
            **kwargs
        ).addCallback(parse_timestamp)

    @defer.inlineCallbacks
    @api_method('POST')
    def reply_to_tweet(self, **kwargs):
        "Reply to a tweet on behalf of a user"
        self.ensure_arguments(['tweet', 'tweet_id'], kwargs['arguments'])

        kwargs['user_id'] = kwargs['authorization'].user_id
        kwargs['uuid'] = kwargs['authorization'].uuid

        kwargs['body'] = urllib.urlencode({
            'status': kwargs['arguments']['tweet'],
            'in_reply_to_status_id': kwargs['arguments']['tweet_id'],
        })

        kwargs['method'] = 'POST'

        yield self.request(
            path='statuses/update.json', **kwargs
        )

        defer.returnValue({'success': 'Replied to tweet'})

TwitterWeb.api_method(
    'num_followers',
    key_name='num',
    present='Number of followers',
    interval='Number of followers over time',
)
TwitterWeb.api_method(
    'num_following',
    key_name='num',
    present='Number of users followed',
    interval='Number of users followed over time',
)
TwitterWeb.api_method(
    'num_tweets',
    key_name='num',
    present='Number of tweets',
    interval='Number of tweets over time',
)
TwitterWeb.api_method(
    'num_favorites',
    key_name='num',
    present='Number of favorites',
    interval='Number of favorites over time',
)
TwitterWeb.api_method(
    'num_listed',
    key_name='num',
    present='Number of times listed',
    interval='Number of times listed over time',
)
TwitterWeb.api_method(
    'num_follow_requests',
    key_name='num',
    present='Number of follow requests',
    interval='Number of follow requests over time',
)
TwitterWeb.api_method(
    'num_retweets',
    key_name='num',
    present='Number of retweets',
    interval='Number of retweets over time',
)
TwitterWeb.api_method(
    'num_mentions',
    key_name='num',
    present='Number of mentions',
    interval='Number of mentions over time',
)
TwitterWeb.api_method(
    'num_direct_messages',
    key_name='num',
    present='Number of direct_messages',
    interval='Number of direct_messages over time',
)

TwitterWeb.granular_method(
    'person_mentioned', key_name='mention',
    docstring="Retrieve data for all mentions, storing the results granularly.",
)

TwitterWeb.api_method(
    'profile',
    present="Returns this user's profile.",
)

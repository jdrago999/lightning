"Generic docstring A"
from __future__ import absolute_import

from lightning.service.base import (
    ServiceOAuth2, Web, Daemon, OAuth2CSRFChecker, StreamCachedService,
    ContentAuthoredService, service_class, recurring, daemon_class,
    enqueue_delta, api_method, check_account_created_timestamp, Profile
)


from lightning.error import Error, AuthError, LightningError
from lightning.model.authorization import Authz
from lightning.model.stream_event import StreamEvent, StreamType

from twisted.internet import defer
from urllib import urlencode

import json
import urllib
import base64


class Reddit(ServiceOAuth2):
    """Reddit OAuth2.0 API for Lightning.
    Lightning's implementation of the Reddit REST API.
    API:
        http://reddit.com/developer/
    """
    name = 'reddit'

    def __init__(self, *args, **kwargs):
        """Create a new Reddit service object.
        Attributes:
            app_info: dict, API keys and secrets per environment.
            domain: string, Domain the service hits.
            base_url: string, URL of domain with correct protocol.
            auth_url: string, URL used to build authorization URL.
            access_token_url: string, URL used to obtain an access_token.
            endpoint_url: string, URL used to call service methods.
        """
        super(Reddit, self).__init__(*args, **kwargs)
        self.app_info = {
            'local': {
                'app_id': 'fake',
                'app_secret': 'fake',
            },
            'beta': {
                'app_id': 'fake',
                'app_secret': 'fake'
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

        self.domain = 'ssl.reddit.com'
        self.base_url = 'https://' + self.domain
        self.auth_url = self.base_url + '/api/v1/authorize?'
        self.access_token_url = self.base_url + '/api/v1/access_token?'
        self.endpoint_url = 'https://oauth.reddit.com'
        self.status_errors.update({
            401: Error.REFRESH_TOKEN,
            429: Error.RATE_LIMITED,
        })

    def basic_authentication_header(self):
        """Reddit needs the access_token url to use HTTP basic authentication
        with the username and password set to the consumer key and secret"""
        user_and_pass = "%s:%s" % (self.app_info[self.environment]['app_id'],
                                   self.app_info[self.environment]['app_secret'])
        encoded = base64.b64encode(user_and_pass)
        return "Basic %s" % encoded

    def request(self, use_ssl=True, **kwargs):
        if kwargs.get('authorization'):
            token = kwargs['authorization'].token
        # This path can happen if we call a method from finish_authorization()
        elif kwargs.get('token'):
            token = kwargs['token']
        else:
            assert False, 'No authorzation.token provided'

        # We don't need the auth token if we're requesting a public, non-ssl
        # url
        if token and use_ssl:
            # Only set the bearer token for Reddit
            if kwargs.get('headers'):
                kwargs['headers']['Authorization'] = ['Bearer %s' % token]
            else:
                kwargs['headers'] = {'Authorization': ['Bearer %s' % token]}
        else:
            if not kwargs.get('headers'):
                kwargs['headers'] = {}

        kwargs['headers']['User-Agent'] = [
            "Inflection Super Amazing Reddit Data Retriever v1.0"]

        if not use_ssl:
            kwargs['base_url'] = "http://www.reddit.com"

        url = self.full_url(**kwargs)
        return super(ServiceOAuth2, self).request(url=url, **kwargs)

    @defer.inlineCallbacks
    def refresh_token(self, **kwargs):
        headers = {
            'Authorization': [self.basic_authentication_header()]
        }
        arguments = {
            'client_id': self.app_info[self.environment]['app_id'],
            'client_secret': self.app_info[self.environment]['app_secret'],
            'duration': 'permanent',
            'grant_type': 'refresh_token',
            'refresh_token': kwargs['authorization'].refresh_token,
            'redirect_uri': kwargs['authorization'].redirect_uri,
            'scope': 'identity',
            'state': 'reddit_lightning_reauth',
        }
        resp = yield self.actually_request(
            url=self.access_token_url,
            postdata=urlencode(arguments),
            headers=headers,
            method='POST',
        )

        response = json.loads(resp.body)
        token = kwargs['authorization'].token = response['access_token']
        yield kwargs['authorization'].save()

        kwargs['headers']['Authorization'] = ['Bearer %s' % token]
        del kwargs['url']

        defer.returnValue(kwargs)

    def profile_link(self, username):
        "Returns a URL to this user's profile."
        return 'http://www.reddit.com/user/%s' % username

    def transform_paged_response(self, resp):
        """All of the relevant data is stored in a big 'data' hash, so take the response and return
        just it's contents"""
        return resp.get('data', {})

    def request_with_paging(self, path, callback, **kwargs):
        """Blogger uses page tokens for results, so we need to grab those and pass them along
        when possible.

        Inputs:
            * path - the relative path of the endpoint to retrieve
            * callback - method to be called with each page of results
            * kwargs - other arguments to pass along to the request method"""

        return super(Reddit, self).request_with_paging(
            path, callback,
            response_paging_token_field='after',
            request_paging_token_field='after',
            data_name='children',
            args={'limit': 100},
            **kwargs
        )


@daemon_class
class RedditDaemon(Daemon, StreamCachedService, Reddit):
    "Reddit Daemon OAuth2 API for Lightning"

    @recurring
    def values_from_profile(self, **kwargs):
        """get the user's current number of link and comment karma points"""
        def write_values(user):
            return defer.gatherResults([
                self.write_datum(method=method, data=datum, **kwargs)
                for method, datum in {
                    'num_link_karma': user.get('link_karma', 0),
                    'num_comment_karma': user.get('comment_karma', 0),
                }.iteritems()
            ]).addCallback(lambda ign: None)

        return self.request(path='api/v1/me.json', **kwargs).addCallback(write_values)

    @recurring
    def num_comments(self, **kwargs):
        """count up all of comments for this user and return the total"""

        num = {"comments": 0}

        def add_comments(comment_list):
            num['comments'] += len(comment_list)

        def fetch_comments(response):
            "take the response from the user endpont and fetch all the comments for that user. "
            username = response.get('name', '')
            return self.request_with_paging(
                use_ssl=False,
                path='user/%s/comments.json' % username,
                callback=add_comments,
                **kwargs
            )

        return self.request(path='api/v1/me.json', **kwargs) \
            .addCallback(fetch_comments) \
            .addCallback(lambda _: {'num': num['comments']})

    # Functions for the feed
    @recurring
    def iterate_over_submissions(self, **kwargs):
        """Extract link submissions from Reddits api and save them to the database"""

        num = {"links": 0}

        def save_submissions(submission_list):
            "save submissions to the database, also keep a running count"
            num['links'] += len(submission_list)
            return self.parse_and_save_stream_data(submission_list, **kwargs)

        def fetch_submissions(response):
            username = response.get('name', '')
            return self.parse_and_save_paged_stream(
                use_ssl=False,
                use_auth=False,
                path='user/%s/submitted.json' % username,
                save_callback=save_submissions, **kwargs
            )

        def write_link_count(_):
            return self.write_datum(method="num_links", data=num['links'], **kwargs)

        return self.request(path='api/v1/me.json', **kwargs) \
                   .addCallback(fetch_submissions).addCallback(write_link_count) \
                   .addCallback(lambda _: None)

    def parse_post(self, entry, **kwargs):
        "Take a submission `entry` from Reddits API and return it converted to standard LG format"
        post = entry.get('data', {})

        # Build author
        username = post.get('author')
        author = {
            'user_id': kwargs['authorization'].user_id,
            'username': username,
            'profile_link': self.profile_link(username),
        }

        # Build activity
        thumbnail_link = None
        if post.get('thumbnail') != 'self':
            thumbnail_link = post.get('thumbnail')
        activity_link = post.get('url')
        if post.get('permalink'):
            activity_link = 'http://www.reddit.com%s' % post.get('permalink')
        description = None
        if post.get('selftext'):
            description = post.get('selftext')
        activity = {
            'activity_link': activity_link,
            'caption': post.get('domain'),
            'description': description,
            'name': post.get('title'),
            'story': "%s submitted a post." % author['username'],
            'thumbnail_link': thumbnail_link,
            'type': StreamType.ARTICLE,
        }

        return StreamEvent(
            metadata={
                'post_id': post.get('id', ''),
                'timestamp': int(post.get('created_utc', '')),
                'service': self.name,
                'is_private': 0,
            },
            author=author,
            activity=activity,
        )

    @recurring
    @enqueue_delta(days=30)
    def profile(self, path='self', **kwargs):
        "Returns this user's profile."
        def build_profile(response):
            data = response or {}
            username = data.get('name')

            return Profile(
                username=username,
                profile_link=self.profile_link(username),
            )

        return self.request(
            path='api/v1/me', **kwargs
        ).addCallback(build_profile)


@service_class
class RedditWeb(Reddit, StreamCachedService, ContentAuthoredService, Web, OAuth2CSRFChecker):

    "Reddit Web OAuth2 API for Lightning"
    daemon_class = RedditDaemon

    @defer.inlineCallbacks
    def start_authorization(self, client_name, args):
        """Start the authorization process.
        Get authorization URL.
        Args:
            redirect_uri: string, URL to redirect to after request.
        """
        try:
            self.ensure_arguments(['redirect_uri'], args)
            state = yield self.generate_state_token()
            args.update({
                'client_id': self.app_info[self.environment]['app_id'],
                'response_type': 'code',
                'duration': 'permanent',
                'state': state,
                'scope': 'identity',
            })
            full_auth_url = self.auth_url + urllib.urlencode(args)
        except (KeyError, ValueError, LightningError) as exc:
            raise AuthError(exc.message)
        defer.returnValue(full_auth_url)

    @defer.inlineCallbacks
    def finish_authorization(self, client_name, args):
        """Complete last step to get an oauth_token.
        Args:
            code: string, code received from service after start_authorization
                step.
            redirect_uri: string, URL to hit after auth.
        """
        try:
            self.ensure_arguments(['code', 'redirect_uri'], args)
            yield self.check_state_token(args['state'])

            arguments = {
                'client_id': self.app_info[self.environment]['app_id'],
                'redirect_uri': args['redirect_uri'],
                'client_secret': self.app_info[self.environment]['app_secret'],
                'code': args['code'],
                'grant_type': 'authorization_code',
                'scope': 'identity',
            }

            headers = {
                'Authorization': [self.basic_authentication_header()]
            }

            resp = yield self.actually_request(
                url=self.access_token_url,
                postdata=urllib.urlencode(arguments),
                headers=headers,
                method='POST',
            )
            response = json.loads(resp.body)

            resp = yield self.request(
                path='api/v1/me',
                token=response['access_token'],
            )

            authorization = yield Authz(
                client_name=client_name,
                redirect_uri=args['redirect_uri'],
                refresh_token=response['refresh_token'],
                service_name=self.name,
                token=response['access_token'],
                user_id=resp['id'],
            ).set_token(self.datastore)

        except (KeyError, ValueError, LightningError) as exc:
            raise AuthError(exc.message)

        defer.returnValue(authorization)

    @api_method('GET')
    @check_account_created_timestamp
    def account_created_timestamp(self, **kwargs):
        """Returns the time at which the user first posted to to this serivice"""

        def parse_timestamp(resp):
            created = resp.get('created_utc')
            t = None
            if created:
                t = int(created)

            return {
                'timestamp': t,
            }

        return self.request(
            path='api/v1/me',
            **kwargs
        ).addCallback(parse_timestamp)


RedditWeb.api_method(
    'num_comment_karma', key_name='num',
    present="Returns this user's comment karma.",
    interval="Returns this user's comment karma over time.",
)

RedditWeb.api_method(
    'num_link_karma', key_name='num',
    present="Returns this user's link karma.",
    interval="Returns this user's link karma over time.",
)


RedditWeb.api_method(
    'num_links', key_name='num',
    present="Returns the number of links this user has submitted.",
    interval="Returns the number of links this user has submitted over time.",
)

RedditWeb.api_method(
    'num_comments', key_name='num',
    present="Returns the number of comments this user has submitted.",
    interval="Returns the number of comments this user has submitted over time.",
)

RedditWeb.api_method(
    'profile',
    present="Returns this user's profile.",
)

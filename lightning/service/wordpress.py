"Generic docstring A"
from __future__ import absolute_import

from lightning.service.base import (
    ServiceOAuth2, Web, ContentAuthoredService, Daemon, service_class,
    recurring, daemon_class, enqueue_delta, api_method, Profile
)


from lightning.error import Error, AuthError, LightningError
from lightning.model.authorization import Authz
from lightning.model.stream_event import StreamEvent, StreamType
from lightning.utils import timestamp_to_utc

from twisted.internet import defer

from calendar import timegm
import iso8601
import json
import urllib
import bleach


class WordPress(ServiceOAuth2):
    """WordPress OAuth2.0 API for Lightning.
    Lightning's implementation of the WordPress REST API.
    API:
        http://developer.wordpress.com/
    """
    name = 'wordpress'

    def __init__(self, *args, **kwargs):
        """Create a new WordPress service object.
        Attributes:
            app_info: dict, API keys and secrets per environment.
            domain: string, Domain the service hits.
            base_url: string, URL of domain with correct protocol.
            auth_url: string, URL used to build authorization URL.
            access_token_url: string, URL used to obtain an access_token.
            endpoint_url: string, URL used to call service methods.
        """
        super(WordPress, self).__init__(*args, **kwargs)
        self.app_info = {
            'local': {
                'app_id': 'fake',
                'app_secret': 'fake',
            },
            'beta': {
                'app_id': 'fake',
                'app_secret': 'fake3'
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

        self.domain = 'public-api.wordpress.com'
        self.base_url = 'https://' + self.domain
        self.auth_url = self.base_url + '/oauth2/authorize?'
        self.access_token_url = self.base_url + '/oauth2/token?'
        self.endpoint_url = self.base_url + '/rest/v1'

        self.status_errors.update({
            503: Error.RATE_LIMITED,
        })

    def request(self, **kwargs):
        if kwargs.get('authorization'):
            token = kwargs['authorization'].token
        # This path can happen if we call a method from finish_authorization()
        elif kwargs.get('token'):
            token = kwargs['token']
        else:
            assert False, 'No authorzation.token provided'

        if token:
            # Only set the bearer token for WordPress
            if kwargs.get('headers'):
                kwargs['headers']['Authorization'] = ['Bearer %s' % token]
            else:
                kwargs['headers'] = {'Authorization': ['Bearer %s' % token]}

        url = self.full_url(**kwargs)

        # XXX - This is a hack.  By using super(ServiceOAuth2), we are calling Serivce.request
        # in order to bypass ServiceOAuth2's request method which forces both the use of the
        # Bearer token and the querystring token.  Really, which form is used should be a parameter
        # passed to the ServiceOAuth2.request method.
        return super(ServiceOAuth2, self).request(url=url, **kwargs)

    def request_with_paging(self, path, callback, **kwargs):
        "WordPress specific values for request_with_paging. Currently only works with posts"
        if kwargs.get('forward', False):
            direction = 'after'
        else:
            direction = 'before'

        return super(WordPress, self).request_with_paging(
            path, callback,
            direction=direction, data_name='posts',
            **kwargs
        )

    def profile_url(self, **kwargs):
        "Returns a URL to this user's profile."
        return 'https://wordpress.com/%s' % kwargs['user_name']

    def get_primary_blog_id(self, **kwargs):

        def parse_primary_blog(user):
            return user.get('primary_blog', '')

        return self.request(path='me', **kwargs).addCallback(parse_primary_blog)


@daemon_class
class WordPressDaemon(Daemon, WordPress):
    "WordPress Daemon OAuth2 API for Lightning"

    @recurring
    @defer.inlineCallbacks
    def num_likes(self, **kwargs):
        """Number of likes."""
        likes = yield self.request(path='me/likes', **kwargs)
        defer.returnValue({'num': likes['found']})

    @recurring
    @defer.inlineCallbacks
    def values_from_posts(self, **kwargs):
        """Fetch the total number of blog posts and comments on the first 10"""
        blog_id = yield self.get_primary_blog_id(**kwargs)
        args = dict(type='post', number=10)
        response = yield self.request(path='sites/%s/posts' % blog_id, args=args, **kwargs)

        total_posts = response.get('found', 0)
        posts = response.get('posts', [])
        total_comments = 0
        for post in posts:
            total_comments += post.get('comment_count', 0)

        defer.gatherResults([
            self.write_datum(method=method, data=datum, **kwargs)
            for method, datum in {
                'num_posts': total_posts,
                'num_comments_recent_10_posts': total_comments,
            }.iteritems()
        ])

    @recurring
    @enqueue_delta(days=30)
    def profile(self, path='self', **kwargs):
        "Returns this user's profile."
        def build_profile(response):
            data = response or {}
            return Profile(
                name=data.get('display_name'),
                username=data.get('username'),
                email=data.get('email'),
                profile_picture_link=data.get('avatar_URL'),
                profile_link=data.get('profile_URL'),
            )

        return self.request(
            path='me', **kwargs
        ).addCallback(build_profile)


@service_class
class WordPressWeb(WordPress, ContentAuthoredService, Web):
    "WordPress Web OAuth2 API for Lightning"
    daemon_class = WordPressDaemon

    def start_authorization(self, client_name, args):
        """Start the authorization process.
        Get authorization URL.
        Args:
            redirect_uri: string, URL to redirect to after request.
        """
        self.ensure_arguments(['redirect_uri'], args)
        args['client_id'] = self.app_info[self.environment]['app_id']
        args['response_type'] = 'code'
        return defer.succeed(self.auth_url + urllib.urlencode(args))

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

            arguments = {
                'client_id': self.app_info[self.environment]['app_id'],
                'redirect_uri': args['redirect_uri'],
                'client_secret': self.app_info[self.environment]['app_secret'],
                'code': args['code'],
                'grant_type': 'authorization_code',
            }

            resp = yield self.actually_request(
                url=self.access_token_url,
                postdata=urllib.urlencode(arguments),
                method='POST',
            )

            response = json.loads(resp.body)
            resp = yield self.request(
                path='me',
                token=response['access_token'],
            )

            authorization = yield Authz(
                client_name=client_name,
                service_name=self.name,
                token=response['access_token'],
                user_id=resp['ID'],
            ).set_token(self.datastore)
        except (ValueError, KeyError, LightningError) as exc:
            raise AuthError(exc.message)
        defer.returnValue(authorization)

    @defer.inlineCallbacks
    def get_feed_url(self, **kwargs):
        blog_id = yield self.get_primary_blog_id(**kwargs)
        defer.returnValue('sites/%s/posts' % blog_id)

    def get_feed_args(self, **kwargs):
        return {'type': 'post', 'status': 'any'}

    def get_feed_limit(self, limit):
        return {'number': limit}

    def get_feed_timestamp(self, timestamp=None, forward=False, **kwargs):
        'Return the endpoint arguments need to specify the direction and timestamp in the right format'
        date = timestamp_to_utc(timestamp)
        if kwargs.get('forward', False):
            return {'after': date}
        else:
            return {'before': date}

    def parse_post(self, post, **kwargs):
        # Build author
        remote_author = post.get('author', {})
        author = dict(
            user_id=remote_author.get('ID'),
            name=remote_author.get('name'),
            username=None,
            profile_picture_link=remote_author.get('avatar_URL', ''),
            profile_link=remote_author.get('profile_URL', ''),
        )

        # Build activity
        html = post.get('excerpt', "")
        description = bleach.clean(html, tags=[], strip=True)
        description = description[:-1]  # Remove trailing newline
        activity = {
            'description': description,
            'activity_link': post.get('URL'),
            'name': post.get('title'),
            'type': StreamType.ARTICLE,
        }

        # Build metadata
        if post.get('status', 'private') == 'publish':
            is_private = 0
        else:
            is_private = 1

        return StreamEvent(
            metadata=dict(
                post_id=post["ID"],
                timestamp=timegm(iso8601.parse_date(post['date']).timetuple()),
                is_private=is_private,
            ),
            author=author,
            activity=activity,
        )

    @api_method('GET')
    def account_created_timestamp(self, **kwargs):
        """Returns the approximate (to within a month) time at which the user first posted to this service"""
        WORDPRESS_LAUNCH_TIMESTAMP = 1054011600

        return super(WordPressWeb, self).account_created_timestamp(
            low_start=WORDPRESS_LAUNCH_TIMESTAMP,
            **kwargs
        )


WordPressWeb.api_method(
    'num_posts', key_name='num',
    present="Returns the number of blog posts this person has made.",
    interval="Returns the number of blog posts this person has made over time.",
)

WordPressWeb.api_method(
    'num_comments_recent_10_posts', key_name='num',
    present="Returns the total number of comments on the persons 10 most recent posts.",
    interval="Returns the total number of comments on the persons 10 most recent posts over time.",
)

WordPressWeb.api_method(
    'num_likes', key_name='num',
    present="Returns the number of posts this person likes.",
    interval="Returns the number of posts this person likes over time.",
)

WordPressWeb.api_method(
    'profile',
    present="Returns this user's profile.",
)

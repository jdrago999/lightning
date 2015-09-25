"Generic docstring A"
from __future__ import absolute_import

from lightning.service.base import (
    ServiceOAuth2, Web, Daemon, service_class, recurring, daemon_class,
    enqueue_delta, Profile, api_method, ContentAuthoredService
)

from lightning.error import Error, AuthError, LightningError
from lightning.model.authorization import Authz
from lightning.model.stream_event import StreamEvent

from twisted.internet import defer

import json
import time
import urllib

class Instagram(ServiceOAuth2):
    """Instagram OAuth2.0 API for Lightning.
    Lightning's implementation of the Instagram REST API.
    API:
        http://instagram.com/developer/
    """
    name = 'instagram'

    def __init__(self, *args, **kwargs):
        """Create a new Instagram service object.
        Attributes:
            app_info: dict, API keys and secrets per environment.
            domain: string, Domain the service hits.
            base_url: string, URL of domain with correct protocol.
            auth_url: string, URL used to build authorization URL.
            access_token_url: string, URL used to obtain an access_token.
            endpoint_url: string, URL used to call service methods.
        """
        super(Instagram, self).__init__(*args, **kwargs)
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

        self.domain = 'api.instagram.com'
        self.base_url = 'https://' + self.domain
        self.auth_url = self.base_url + '/oauth/authorize?'
        self.access_token_url = self.base_url + '/oauth/access_token?'
        self.endpoint_url = self.base_url + '/v1'

        self.status_errors.update({
            503: Error.RATE_LIMITED,
        })

    def request_with_paging(self, path, callback, **kwargs):
        "Instagram-specific values for request_with_paging"
        # Instagram will only return a max of 20 items per call by default.
        if kwargs.get('forward', False):
            direction = 'next_url'
        else:
            direction = 'prev_url'

        return super(Instagram, self).request_with_paging(
            path, callback,
            direction=direction, paging='pagination', data_name='data',
            **kwargs
        )

    def profile_link(self, username):
        "Returns a URL to this user's profile."
        if username:
            return 'https://instagram.com/%s' % username
        return None

    ############################################
    # Below is the list of functions required to support reading the feed

    def get_feed(self, **kwargs):
        """get the global privacy setting for our user, then construct the feed as normal"""

        def get_feed_with_global_privacy(relationship):
            self.all_posts_private = relationship["data"]["target_user_is_private"]
            return super(Instagram, self).get_feed(**kwargs)

        return self.request(path='users/%s/relationship' % kwargs['authorization'].user_id, **kwargs).addCallback(get_feed_with_global_privacy)

    def get_feed_url(self, **kwargs):
        'The feed URL'
        return 'users/%s/media/recent' % kwargs['authorization'].user_id

    def get_feed_limit(self, limit):
        'Return the limit in the right format'
        return {'count': limit}

    def get_feed_timestamp(self, **kwargs):
        'Return the timestamp in the right format'
        timestamp = kwargs.get('timestamp', int(time.time()))
        if kwargs.get('forward', False):
            return {'min_timestamp': timestamp}
        else:
            return {'max_timestamp': timestamp}

    def parse_post(self, post, **kwargs):
        "Parse a feed post"
        # Build author
        user = post.get('user', {})
        username = user.get('username')

        author = {
            'user_id': user.get('id'),
            'name': user.get('full_name'),
            'username': username,
            'profile_picture_link': user.get('profile_picture'),
            'profile_link': self.profile_link(username),
        }

        # Build activity
        # Sometimes we get a caption that's set to None, so chaining get's
        # doesn't work here.
        caption = post.get('caption')
        if caption:
            story = caption.get('text')
        else:
            story = None

        activity = {
            'story': story,
            'activity_link': post.get('link')
        }

        if post.get('images'):
            activity['picture_link'] = post['images'].get('standard_resolution').get('url')
            activity['thumbnail_link'] = post['images'].get('thumbnail').get('url')

        if post.get('videos'):
            activity['video_link'] = post['videos'].get('standard_resolution').get('url')

        if post.get('location'):
            activity['location'] = {
                'name': post['location'].get('name'),
                'latitude': post['location'].get('latitude'),
                'longitude': post['location'].get('longitude'),
            }

        is_private = 0
        if self.all_posts_private:
            is_private = 1

        return StreamEvent(
            metadata=dict(
                post_id=post.get('id'),
                timestamp=int(post.get('created_time', 0)),
                is_private=is_private,
            ),
            author=author,
            activity=activity,
        )

    # TO HERE
    ############################################

@daemon_class
class InstagramDaemon(Daemon, Instagram):
    "Instagram Daemon OAuth2 API for Lightning"

    @recurring
    def values_from_profile(self, **kwargs):
        "Values from profile."
        def write_additional_values(response):
            counts = response.get('data', {}).get('counts', {})
            return defer.gatherResults([
                self.write_datum(method=method, data=datum, **kwargs)
                for method, datum in {
                    'num_followers': counts['followed_by'],
                    'num_followed': counts['follows'],
                    'num_media': counts['media'],
                }.iteritems()
            ]).addCallback(lambda ign: None)

        return self.request(
            path='users/self',
            **kwargs
        ).addCallback(write_additional_values)

    @recurring
    def media_counts(self, **kwargs):
        'Collects data for num_likes and num_comments.'
        num = {'likes': 0, 'comments': 0}

        def write_granular_data(data):
            if len(data):
                return defer.gatherResults([
                    # id, fromid, time, text
                    self.datastore.write_granular_datum(
                        method='comment',
                        item_id=datum['id'],
                        actor_id=datum.get('from', {}).get('id', ''),
                        timestamp=datum['created_time'],
                        authorization=kwargs['authorization'],
                    ) for datum in data
                ])

        def summate(data):
            to_write = []
            for media in data:
                comments = media.get('comments', {})
                # This may be incorrect for large numbers of comments on a single
                # item. Need an example to test with.
                to_write.extend(comments.get('data', []))
                num['comments'] += comments.get('count', 0)
                num['likes'] += media.get('likes', {}).get('count', 0)

            # Confirm this works by adding a comment to a picture
            return self.datastore.find_unwritten_granular_data(
                method='comment', data=to_write, **kwargs
            ).addCallback(
                write_granular_data
            ).addErrback(lambda ign: None)

        def write_values(_):
            return defer.gatherResults([
                self.write_datum(method=method, data=datum, **kwargs)
                for method, datum in {
                    'num_likes': num['likes'],
                    'num_comments': num['comments'],
                }.iteritems()
            ])

        return self.request_with_paging(
            path='users/self/media/recent',
            callback=summate,
            forward=True,
            **kwargs
        ).addCallback(write_values).addCallback(lambda ign: None)

    @recurring
    @enqueue_delta(days=30)
    def profile(self, path='self', **kwargs):
        "Returns this user's profile."
        def build_profile(response):
            data = response.get('data', {})
            username = data.get('username')
            if username:
                profile_link = self.profile_link(username=username)
            else:
                profile_link = None
            return Profile(
                name=data.get('full_name'),
                bio=data.get('bio'),
                profile_picture_link=data.get('profile_picture'),
                profile_link=profile_link,
                username=username,
            )

        # This ugliness is a hack to get granular data working. It needs to be
        # refactored in a bad way to have a common and consistent calling API
        # between Facebook and Instagram.
        return self.request(
            path='users/%s' % str(path), **kwargs
        ).addCallback(build_profile)


@service_class
class InstagramWeb(Instagram, ContentAuthoredService, Web):
    "Instagram Web OAuth2 API for Lightning"
    daemon_class = InstagramDaemon

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

            authorization = yield Authz(
                client_name=client_name,
                service_name=self.name,
                token=response['access_token'],
                user_id=response['user']['id'],
            ).set_token(self.datastore)
        except (LightningError, ValueError) as exc:
            raise AuthError(exc.message)

        defer.returnValue(authorization)

    @api_method('GET')
    def account_created_timestamp(self, **kwargs):
        """Returns the approximate (to within a month) time at which the user first posted to this service"""
        INSTAGRAM_LAUNCH_TIMESTAMP = 1286323200

        def extract_timestamp(resp):
            "Pull the first timestamp out of the feed response and return it"
            data = resp.get('data', {})
            if len(data):
                post = data[0]
                return int(post.get('created_time', 0))
            else:
                return None

        return super(InstagramWeb, self).account_created_timestamp(
            low_start=INSTAGRAM_LAUNCH_TIMESTAMP,
            extract_timestamp_callback=extract_timestamp,
            **kwargs
        )


InstagramWeb.api_method(
    'num_followers', key_name='num',
    present='Number of users following user',
    interval='Number of users following user over time',
)
InstagramWeb.api_method(
    'num_followed', key_name='num',
    present='Number of users followed by user',
    interval='Number of users followed by user over time',
)
InstagramWeb.api_method(
    'num_media', key_name='num',
    present='Number of videos and photos uploaded by user',
    interval='Number of videos and photos uploaded by user over time',
)
InstagramWeb.api_method(
    'num_likes', key_name='num',
    present='Number of likes on photos uploaded by user',
    interval='Number of likes on photos uploaded by user over time',
)
InstagramWeb.api_method(
    'num_comments', key_name='num',
    present='Number of comments on photos uploaded by user',
    interval='Number of comments on photos uploaded by user over time',
)

InstagramWeb.granular_method(
    'person_commented', key_name='comment',
    docstring="Retrieve data for all comments, storing the results granularly.",
)

InstagramWeb.api_method(
    'profile',
    present="Returns this user's profile.",
)

"Generic docstring A"
from __future__ import absolute_import

from lightning.service.base import (
    GoogleService, Daemon, Web, StreamCachedService, service_class,
    recurring, daemon_class, enqueue_delta, Profile
)


from lightning.error import Error, AuthError, LightningError
from lightning.model.authorization import Authz
from lightning.model.stream_event import StreamEvent, StreamType
from lightning.utils import get_youtube_video_id

from twisted.internet import defer

import calendar
from dateutil import parser as dateparser

import json
import urllib
import bleach
import re


class GooglePlus(GoogleService):
    "CLASS DOCSTRING"
    name = 'googleplus'

    def __init__(self, *args, **kwargs):
        "DOCSTRING"
        super(GooglePlus, self).__init__(*args, **kwargs)

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

        self.domain = 'www.googleapis.com'
        self.base_url = 'https://' + self.domain
        self.auth_url = 'https://accounts.google.com/o/oauth2/auth'
        self.access_token_url = 'https://accounts.google.com/o/oauth2/token'
        self.endpoint_url = self.base_url + '/plus/v1'

        self.permissions = {
            'testing': {
                'scope': 'https://www.googleapis.com/auth/plus.login',
            },
            'testing2': {
                'scope': 'https://www.googleapis.com/auth/plus.login',
            },
            'lg-console': {
                'scope': 'https://www.googleapis.com/auth/plus.login',
            },
        }

        self.status_errors.update({
            401: Error.REFRESH_TOKEN,
        })


    ############################################
    # Below is the list of functions required to support reading the feed
    ############################################

    def parse_post(self, post, **kwargs):
        "Parse a feed post"
        # Build author
        remote_author = post.get('actor', {})
        author = {
            'user_id': remote_author.get('id'),
            'name': remote_author.get('displayName'),
            'profile_picture_link': remote_author.get('image', {}).get('url'),
            'profile_link': remote_author.get('url'),
        }

        # Build activity
        html = post.get('object', {}).get('content', '')
        story = bleach.clean(html, tags=[], strip=True)
        activity = {
            'story': story,
            'activity_link': post.get('url'),
        }
        if len(post.get('object', {}).get('attachments', [])) > 0:
            # Just grab the first attachment for now.
            attachment = post['object']['attachments'][0]
            if attachment.get('objectType') == 'article':
                activity['picture_link'] = attachment.get('fullImage', {}).get('url')
                activity['thumbnail_link'] = attachment.get('image', {}).get('url')
            elif attachment.get('objectType') == 'album':
                if len(attachment.get('thumbnails', [])) > 1:
                    image = attachment['thumbnails'][0]
                    activity['picture_link'] = image.get('image', {}).get('url')
                    activity['thumbnail_link'] = image.get('image', {}).get('url')
            elif attachment.get('objectType') == 'video':
                activity['video_link'] = attachment.get('embed', {}).get('url')
                activity['picture_link'] = attachment.get('image', {}).get('url')
                activity['thumbnail_link'] = attachment.get('image', {}).get('url')
                video_id = get_youtube_video_id(activity['video_link'])
                if video_id:
                    activity['video_id'] = video_id
                    activity['type'] = StreamType.VIDEO_EMBED

        # Build metadata
        post_id = 'post:%s' % post.get('id', 0)
        timestamp = calendar.timegm(dateparser.parse(post.get('published', '')).utctimetuple())
        is_private = 1
        if post.get('access'):
            if post['access']['description'] == 'Public':
                is_private = 0

        return StreamEvent(
            metadata={
                'post_id': post_id,
                'timestamp': timestamp,
                'service': self.name,
                'is_private': is_private,  # XXX: We only get public activities right now.
            },
            author=author,
            activity=activity,
        )

    # TO HERE
    ############################################


@daemon_class
class GooglePlusDaemon(GooglePlus, StreamCachedService, Daemon):
    "GooglePlus Daemon"

    @recurring
    def iterate_over_activities(self, **kwargs):
        return self.parse_and_save_paged_stream(path='people/me/activities/public', **kwargs)

    @recurring
    @enqueue_delta(days=30)
    def profile(self, path='self', **kwargs):
        "Returns this user's profile."
        def build_profile(response):
            data = response or {}
            if data.get('image'):
                picture_url = data['image'].get('url')
            else:
                picture_url = None
            return Profile(
                name=data.get('displayName'),
                gender=data.get('gender'),
                profile_picture_link=picture_url,
                profile_link=data.get('url'),
            )

        return self.request(
            path='people/me', **kwargs
        ).addCallback(build_profile)


@service_class
class GooglePlusWeb(GooglePlus, StreamCachedService, Web):
    "GooglePlus Web"
    daemon_class = GooglePlusDaemon

    @defer.inlineCallbacks
    def finish_authorization(self, client_name, **kwargs):
        """Complete last step to get an oauth_token.
        Args:
            code: string, code received from service after start_authorization
                step.
            redirect_uri: string, URL to hit after auth.
        """
        try:
            self.ensure_arguments(['code', 'redirect_uri'], kwargs.get('args', {}))

            arguments = {
                'client_id': self.app_info[self.environment]['app_id'],
                'redirect_uri': kwargs['args']['redirect_uri'],
                'client_secret': self.app_info[self.environment]['app_secret'],
                'code': kwargs['args']['code'],
                'grant_type': 'authorization_code',
            }
            resp = yield self.actually_request(
                url=self.access_token_url,
                postdata=urllib.urlencode(arguments),
                method='POST',
            )

            response = json.loads(resp.body)

            resp = yield self.request(
                path='people/me',
                token=response['access_token'],
            )

            args = {
                'client_name': client_name,
                'service_name': self.name,
                'token': response['access_token'],
                'user_id': resp['id'],
            }

            # The refresh_token is only provided for the initial authorization. It is
            # **NOT** provided otherwise.

            if response.get('refresh_token'):
                args['refresh_token'] = response['refresh_token']

            authorization = yield Authz(**args).set_token(self.datastore)
        except (KeyError, ValueError, LightningError) as exc:
            raise AuthError(exc.message)
        defer.returnValue(authorization)

GooglePlusWeb.api_method(
    'profile',
    present="Returns this user's profile.",
)

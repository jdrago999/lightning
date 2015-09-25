"Generic docstring A"
from __future__ import absolute_import

from lightning.service.base import (
    GoogleService, Daemon, Web, StreamCachedService, ContentAuthoredService,
    service_class, recurring, daemon_class, enqueue_delta, Profile
)


from lightning.error import Error, AuthError, LightningError
from lightning.model.authorization import Authz
from lightning.model.stream_event import StreamEvent, StreamType

from twisted.internet import defer

from calendar import timegm
import iso8601
import json
import logging
import re
import time
import urllib


class Youtube(GoogleService):
    name = 'youtube'

    def __init__(self, *args, **kwargs):
        "DOCSTRING"
        super(Youtube, self).__init__(*args, **kwargs)

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
        self.base_url = 'https://' + self.domain + "/youtube/v3"
        self.auth_url = 'https://accounts.google.com/o/oauth2/auth'
        self.access_token_url = 'https://accounts.google.com/o/oauth2/token'
        self.endpoint_url = self.base_url

        self.status_errors.update({
            400: Error.BAD_PARAMETERS,
            401: Error.INVALID_TOKEN,
            403: Error.RATE_LIMITED,
        })
        self.permissions = {
            'testing': {
                'scope': 'https://gdata.youtube.com',
            },
            'testing2': {
                'scope': 'https://gdata.youtube.com',
            },
            'lg-console': {
                'scope': 'https://gdata.youtube.com',
            },
        }

    @defer.inlineCallbacks
    def parse_error(self, status, url, headers, body, **kwargs):
        """Parse errors from service"""
        msg = 'Unknown response'
        retry_at = int(time.time() + (60*60))

        # Error message from HTTP status
        if status in self.status_errors:
            msg = self.status_errors[status]

        try:
            content = json.loads(body)
            msg = content.get('error', msg)
        except (TypeError, ValueError):
            pass

        # Received an invalid_grant error from YouTube
        if msg == 'invalid_grant':
            logging.error('Got %s invalid_grant for %s' % (status, url))
            msg = Error.INVALID_TOKEN
        # Refresh token given in HTML body
        if re.search('Token invalid', body):
            msg = Error.REFRESH_TOKEN

        self.raise_error(msg, retry_at)

    def request_with_paging(self, path, callback, **kwargs):
        """
        This returns a Deferred that knows how to page through results.

        The assumption is that the callback is doing some sort of useful work,
        likely with an accumulator of some sort.

        Note: This request_with_paging is different from the other services
        because Youtube (and Google, in general) doesn't provide pagination URLs
        in a single place in their JSON. Instead, they provide two <link> values
        which have rel='previos' and rel='next'. This is a consequence of their
        using a XML-to-JSON converter. So, we must provide our own pagination.
        """

        stopback = kwargs.get('stopback', lambda: True)

        # Note the use of path at first, then full_url in subsequent iterations.
        @defer.inlineCallbacks
        def pager(resp):
            resp = resp.get('feed', {})
            data = resp.get('entry', [])
            yield defer.maybeDeferred(callback, data)

            should_stop = yield defer.maybeDeferred(stopback)
            if should_stop or len(data) == 0:
                return

            url = ''
            if kwargs.get('forward', False):
                # Get the rel='next'
                possible = [
                    item['href'] for item in resp['link']
                    if item['rel'] == 'next'
                ]
                if len(possible):
                    url = possible[0]
            else:
                # Get the rel='previous'
                possible = [
                    item['href'] for item in resp['link']
                    if item['rel'] == 'previous'
                ]
                if len(possible):
                    url = possible[0]

            if url:
                defer.returnValue(
                    self.request(full_url=url, **kwargs).addCallback(pager)
                )

        return self.request(path=path, **kwargs).addCallback(pager)

    def get_feed(self, **kwargs):
        'Generic method to iterate over the feed for N results.'
        posts = []
        limit = kwargs.get('num', 100)

        def add_post(data):
            # What if the user has never uploaded anything?
            if not data:
                return

            for post in data:
                proto = post['data']
                if proto:
                    if kwargs['show_private'] < proto['metadata']['is_private']:
                        continue

                    proto['metadata']['service'] = self.name
                    if str(kwargs['authorization'].user_id) == str(proto['author']['user_id']):
                        proto['metadata']['is_echo'] = 0
                    else:
                        proto['metadata']['is_echo'] = 1

                    if kwargs['echo'] >= proto['metadata']['is_echo']:
                        posts.append(proto)

        def return_posts(ign):
            return posts

        args = {
            'uuid': kwargs['authorization'].uuid,
            'limit': limit,
        }

        # most_recent_activity doesn't provide a timestamp
        if kwargs.get('timestamp'):
            if kwargs.get('forward'):
                args['start'] = kwargs['timestamp']
            else:
                args['end'] = kwargs['timestamp']

        return self.datastore.retrieve_stream_cache(
            **args
        ).addCallback(add_post).addCallback(return_posts)

    @defer.inlineCallbacks
    def parse_post(self, post, **kwargs):
        "Parse a feed post"
        # Build author
        user_id = post.get('author', [{}])[0].get('yt$userId', {}).get('$t')
        author = {
            'user_id': user_id,
            'name': 'I',  # default if we somehow don't get a user
        }
        if user_id:
            kwargs['path'] = 'feeds/api/users/%s' % user_id
            response = yield self.request(**kwargs)
            remote_author = self.parse_profile(response['entry'])
            author['username'] = remote_author.get('username')
            author['name'] = remote_author.get('name')
            author['profile_picture_link'] = remote_author.get('profile_picture_link')
            author['profile_link'] = remote_author.get('profile_link')

        # Build activity
        story = '%s uploaded a video' % author['name']
        if post.get('title'):
            story = '%s: "%s"' % (story, post['title'].get('$t', ''))

        media_group = post.get('media$group', {})
        video_id = media_group.get('yt$videoid', {}).get('$t', '')
        media_thumbnail = media_group.get('media$thumbnail', [])
        thumbnail_link = None
        for t in media_thumbnail:
            if t.get('yt$name') == 'default':
                thumbnail_link = t.get('url')
        activity = {
            'activity_link': "https://www.youtube.com/watch?v=%s" % video_id,
            'thumbnail_link': thumbnail_link,
            'story': story,
            'type': StreamType.VIDEO_EMBED,
            'video_id': video_id,
        }

        # YT returns a key with an empty array if the video is private.
        is_private = 0
        if not media_group.get('yt$private', True):
            is_private = 1

        defer.returnValue(StreamEvent(
            metadata={
                'post_id': post.get('id', {}).get('$t', ''),
                'timestamp': timegm(
                    iso8601.parse_date(
                        post.get('published', {})
                            .get('$t', '1970-01=01T00:00:00.000Z')
                    ).timetuple()
                ),
                'is_private': is_private,
            },
            author=author,
            activity=activity,
        ))

    def parse_profile(self, data):
        item = data['items'][0]
        snippet = item.get('snippet')
        username = item.get('id')
        name = snippet.get('title')
        profile_link = "https://www.youtube.com/channel/%s" % username
        profile_picture_link = snippet.get('thumbnails', {}).get('high', {}).get('url')

        return dict(
            name=name,
            username=username,
            profile_link=profile_link,
            profile_picture_link=profile_picture_link,
        )


@daemon_class
class YoutubeDaemon(Youtube, StreamCachedService, Daemon):
    "Youtube Daemon"

    @recurring
    def iterate_over_uploads(self, **kwargs):
        "User's videos."

        def write_values(_):
            return defer.gatherResults([
                self.write_datum(method=method, data=datum, **kwargs)
                for method, datum in {
                    'num_videos': num['total'],
                    'num_comments': num['comments'],
                    'num_likes': num['likes'],
                    'num_views': num['views'],
                    'num_favorites': num['favorites'],
                }.iteritems()
            ])

        return self.parse_and_save_paged_stream(
            path='feeds/api/users/default/uploads',
            **kwargs
        ).addCallback(lambda ign: None)

    @recurring
    @enqueue_delta(days=30)
    def profile(self, **kwargs):
        "Returns this user's profile."
        def build_profile(data):
            profile = self.parse_profile(data)
            return Profile(**profile)

        return self.request(
            path='channels',
            args=dict(part='snippet', mine='true'),
            **kwargs
        ).addCallback(build_profile)


@service_class
class YoutubeWeb(Youtube, StreamCachedService, ContentAuthoredService, Web):
    "Youtube Web"
    daemon_class = YoutubeDaemon

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

            kwargs['args']['part'] = 'id'
            kwargs['args']['mine'] = 'true'

            resp = yield self.request(
                path='channels',
                token=response['access_token'],
                **kwargs
            )

            args = {
                'client_name': client_name,
                'service_name': self.name,
                'token': response['access_token'],
                'user_id': resp['items'][0]['id'],
            }

            # The refresh_token is only provided for the initial authorization. It is
            # **NOT** provided otherwise.
            if response.get('refresh_token'):
                args['refresh_token'] = response['refresh_token']

            authorization = yield Authz(**args).set_token(self.datastore)
        except (LightningError, ValueError, KeyError) as exc:
            raise AuthError(exc.message)
        defer.returnValue(authorization)

YoutubeWeb.api_method(
    'profile',
    present="Returns this user's profile.",
)

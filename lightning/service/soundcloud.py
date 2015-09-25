"Generic docstring A"
from __future__ import absolute_import

from lightning.service.base import (
    ServiceOAuth2, Daemon, Web, StreamCachedService, service_class, recurring,
    daemon_class, enqueue_delta, Profile
)


from lightning.error import Error, AuthError, LightningError
from lightning.model.authorization import Authz
from lightning.model.stream_event import StreamEvent

from twisted.internet import defer

from calendar import timegm
from dateutil import parser as dateparser

import json
import urllib
import urlparse


class SoundCloud(ServiceOAuth2):
    "CLASS DOCSTRING"
    name = 'soundcloud'

    def __init__(self, *args, **kwargs):
        super(SoundCloud, self).__init__(*args, **kwargs)
        self.token_param = 'oauth_token'
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

        self.domain = 'api.soundcloud.com'
        self.base_url = 'https://' + self.domain
        self.auth_url = self.base_url + '/connect'
        self.access_token_url = self.base_url + '/oauth2/token'
        self.endpoint_url = self.base_url

        self.status_errors.update({
            403: Error.INSUFFICIENT_PERMISSIONS,
            422: Error.BAD_PARAMETERS,
            429: Error.RATE_LIMITED,
        })

    def get_authorized_full_url(self, url, **kwargs):
        """Take a fully qualified url without oauth parameters and return the same url with the ouath
        token appended. """

        url_parts = list(urlparse.urlparse(url))

        # now add the token to the querystring
        args = kwargs.get('args', {})
        if args.get(self.token_param):
            url_parts[4] += "&%s=%s" % (self.token_param, args.get(self.token_param))

        return urlparse.urlunparse(url_parts)


    def request_with_paging(self, path, callback, **kwargs):
        """ Page through results, defaulting to url paging"""
        return self.request_with_url_paging(path, callback, **kwargs)

    def request_with_url_paging(self, path, callback, **kwargs):
        """Page through all the results for the givien endpoint and call `callback` on each. Flickr
        uses limit and offset for page parameters, so we need to inform the parent method
        of these fields.

        Note: soundcloud has two methods of paging  one, which is limit/ofsett paging for endpoints
        like me/tracks.json and this one for url based paging, for endpoints like me/activities

        Inputs:
            * path - the relative path of the endpoint to retrieve
            * callback - method to be called with each page of results
            * kwargs - other arguments to pass along to the request method

        Yields: A deferred request which when completed will have called each page of results with `callback`"""

        if not kwargs.get('args'):
            kwargs['args'] = {}
        kwargs['args']['limit'] = 200
        return super(SoundCloud, self).request_with_paging(
            path, callback, direction='next_href', data_name='collection', **kwargs
        )

    def request_with_offset_paging(self, path, callback, **kwargs):
        """Page through all the results for the givien endpoint and call `callback` on each. SoundCloud
        uses limit and offset for page parameters, so we need to inform the parent method
        of these fields.

        Note: soundcloud has two methods of paging, this one, which is limit/ofsett paging for endpoints
        like me/tracks.json and another for url based paging, for endpoints like me/activities

        Inputs:
            * path - the relative path of the endpoint to retrieve
            * callback - method to be called with each page of results
            * kwargs - other arguments to pass along to the request method

        Yields: A deferred request which when completed will have called each page of results with `callback`"""


        limit = 200

        # soundcloud doesn't put the results array in any particular field, but instead, the entire response
        # is an array
        kwargs['data_name'] = None
        return super(SoundCloud, self).request_with_paging(path, callback,
            offset_increase=limit,
            starting_offset=0,
            limit_field='limit',
            offset_field='offset',
            limit=limit,
            **kwargs
        )


    def refresh_token(self, **kwargs):
        raise NotImplementedError

    ############################################
    # Below is the list of functions required to support reading the feed
    ############################################

    @defer.inlineCallbacks
    def get_author(self, author_id, **kwargs):
        "Fetch profile information for the given author id"

        kwargs['path'] = 'users/%s.json' % author_id
        person = yield self.request(**kwargs)

        author = {
            'user_id': author_id,
            'name': person.get('full_name', ''),
            'username': person.get('permalink', ''),
            'profile_picture_link': person.get('avatar_url', ''),
            'profile_link': person.get('permalink_url', ''),
        }
        defer.returnValue(author)

    @defer.inlineCallbacks
    def parse_post(self, post, **kwargs):
        "Parse a feed post"
        parsed = None

        # make sure this post has something to do with this user
        item = post.get('origin', {})

        if post.get('tags') in ['me', 'own'] or str(item.get('user_id')) == str(kwargs['authorization'].user_id):
            # Build author
            author = yield self.get_author(item.get('user_id'), **kwargs)

            # Build activity
            story = ''
            post_type = post.get('type')
            if post_type == 'track':
                story = '%s uploaded a track: "%s"' % (author['name'], item.get('title'))
            if post_type == 'comment':
                story = '%s commented on the track: "%s"' % (author['name'], item.get('track', {}).get('title'))
            if post_type == 'playlist':
                story = '%s added a playlist: "%s"' % (author['name'], item.get('title'))

            # if we story didn't get defiend above, just skip this one, since we don't really know what it is
            if story:
                activity = {
                    'story': story,
                    'activity_link': item.get('permalink_url'),
                }

                parsed = StreamEvent(
                    metadata={
                        'post_id': "%s:%s" % (item.get('kind'), item.get('id')),
                        'timestamp': timegm(dateparser.parse(post.get('created_at', '')).utctimetuple()),
                        'service': self.name,
                        'is_private': 0,
                    },
                    author=author,
                    activity=activity,
                )

        defer.returnValue(parsed)

    # TO HERE
    ############################################


@daemon_class
class SoundCloudDaemon(SoundCloud, StreamCachedService, Daemon):
    "SoundCloud Daemon"

    @recurring
    def iterate_over_activities(self, **kwargs):
        return self.parse_and_save_paged_stream(path='me/activities/all.json', **kwargs)

    @recurring
    def values_from_profile(self, **kwargs):
        "Fetch various stats from the current user's profile and write them to the database"
        def write_values(user):
            return defer.gatherResults([
                self.write_datum(method=method, data=datum, **kwargs)
                for method, datum in {
                    'num_public_tracks': user['track_count'],
                    'num_public_playlists': user['playlist_count'],
                    'num_following': user['followings_count'],
                    'num_followers': user['followers_count'],
                }.iteritems()
            ]).addCallback(lambda ign: None)

        return self.request(path='me.json', **kwargs).addCallback(write_values)

    @recurring
    @enqueue_delta(days=30)
    def profile(self, **kwargs):
        "Returns this user's profile."
        def build_profile(data):
            return Profile(
                name=data.get('full_name'),
                profile_picture_link=data.get('avatar_url'),
                profile_link=data.get('permalink_url'),
                username=data.get('permalink'),
                bio=data.get('description'),
            )

        return self.request(
            path='me.json',
            **kwargs
        ).addCallback(build_profile)


@service_class
class SoundCloudWeb(SoundCloud, StreamCachedService, Web):
    "SoundCloud Web"
    daemon_class = SoundCloudDaemon

    def start_authorization(self, **kwargs):
        """
        Get the authorization URL.

        Args:
            redirect_uri: string, URL to redirect to after request.
        """
        try:
            self.ensure_arguments(['redirect_uri'], kwargs.get('args', {}))

            kwargs['args']['client_id'] = self.app_info[self.environment]['app_id']
            kwargs['args']['response_type'] = 'code'
            kwargs['args']['access_type'] = 'offline'
            kwargs['args']['approval_prompt'] = 'auto'
            kwargs['args']['scope'] = 'non-expiring'
        except (KeyError, ValueError, LightningError) as exc:
            raise AuthError(exc.message)
        return defer.succeed(
            self.construct_authorization_url(
                base_uri=self.auth_url, **kwargs
            )
        )

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
                path='me.json',
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
                args['secret'] = response['refresh_token']

            authorization = yield Authz(**args).set_token(self.datastore)
        except (KeyError, ValueError, LightningError) as exc:
            raise AuthError(exc.message)
        defer.returnValue(authorization)

SoundCloudWeb.api_method(
    'num_public_tracks', key_name='num',
    present="Returns this user's number of public tracks.",
    interval="Returns this user's number of public tracks over time.",
)

SoundCloudWeb.api_method(
    'num_public_playlists', key_name='num',
    present="Returns this user's number of public playlists.",
    interval="Returns this user's number of public playlists over time.",
)

SoundCloudWeb.api_method(
    'num_followers', key_name='num',
    present="Returns this user's number of followers.",
    interval="Returns this user's number of followers over time.",
)

SoundCloudWeb.api_method(
    'num_following', key_name='num',
    present="Returns the number of people this user is following.",
    interval="Returns the number of people this user is following over time.",
)

SoundCloudWeb.api_method(
    'profile',
    present="Returns this user's profile.",
)

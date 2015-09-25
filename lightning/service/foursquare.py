"Generic docstring A"

from lightning.service.base import (
    ServiceOAuth2, Daemon, Web, MultiEndPointFeedService, ContentAuthoredService,
    service_class, recurring, daemon_class, enqueue_delta, Profile, api_method
)


from lightning.error import Error, AuthError, LightningError
from lightning.model.authorization import Authz
from lightning.model.stream_event import StreamEvent
from lightning.utils import build_full_name
from twisted.internet import defer

import json
import time
import urllib

class Foursquare(ServiceOAuth2):
    """Foursquare OAuth2.0 API for Lightning.
    Lightning's implementation of the Foursquare REST API.
    API:
        http://foursquare.com/developers/
    """
    name = 'foursquare'
    token_param = 'oauth_token'

    def __init__(self, *args, **kwargs):
        """Create a new Foursquare service object.
        Attributes:
            app_info: dict, API keys and secrets per environment.
            domain: string, Domain the service hits.
            base_url: string, URL of domain with correct protocol.
            auth_url: string, URL used to build authorization URL.
            access_token_url: string, URL used to obtain an access_token.
            endpoint_url: string, URL used to call service methods.
        """
        super(Foursquare, self).__init__(*args, **kwargs)
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

        self.domain = 'foursquare.com'
        self.base_url = 'https://' + self.domain
        self.auth_url = self.base_url + '/oauth2/authenticate?'
        self.access_token_url = self.base_url + '/oauth2/access_token'
        self.endpoint_url = 'https://api.' + self.domain + '/v2'
        self.api_version = '20131204'

    def parse_error(self, status, url, headers, body, **kwargs):
        """Parse errors from service"""
        # Reference: https://developer.foursquare.com/overview/responses
        body_errors = {
            'rate_limit_exceeded': Error.RATE_LIMITED,
            'param_error': Error.BAD_PARAMETERS,
            'invalid_auth': Error.INVALID_TOKEN,
            'not_authorized': Error.INSUFFICIENT_PERMISSIONS,
            'server_error': Error.UNKNOWN_RESPONSE,
            'other': Error.UNKNOWN_RESPONSE,
        }
        msg = 'Unknown response'
        retry_at = int(time.time() + (10*60))

        # Error message from HTTP status
        if status in self.status_errors:
            msg = self.status_errors[status]

        # Error message from body
        try:
            content = json.loads(body)
            body_error = content.get('meta', {}).get('errorType')
            msg = body_errors.get(body_error, msg)
        except (TypeError, ValueError):
            pass
        self.raise_error(msg, retry_at)

    def request(self, **kwargs):
        """
        Foursquare requires a "v" parameter to be passed in to all API requests
        specifying the version number expected.
        """
        if kwargs.get('args'):
            kwargs['args']['v'] = self.api_version
        else:
            kwargs['args'] = {'v': self.api_version}
        return super(Foursquare, self).request(**kwargs)

    def request_with_paging(self, path, callback, **kwargs):
        """
        This returns a Deferred that knows how to page through results.

        The assumption is that the callback is doing some sort of useful work,
        likely with an accumulator of some sort.

        Note: This request_with_paging is different from the other services
        because Foursquare doesn't provide pagination URLs in its responses. So,
        we must provide our own pagination using limit/offset.
        """

        stopback = kwargs.get('stopback', lambda: True)

        kwargs['args'] = kwargs.get('args', {})
        paging = {
            'limit': kwargs['args'].get('limit', 250),
            'offset': 0,
        }
        kwargs['args']['limit'] = paging['limit']

        def pager(resp):
            data = resp['response']['checkins'].get('items', [])

            callback(data)

            if stopback() or len(data) == 0:
                return

            paging['offset'] += paging['limit']
            kwargs['args']['offset'] = paging['offset']

            return self.request(path=path, **kwargs).addCallback(pager)

        return self.request(path=path, **kwargs).addCallback(pager)

    def profile_url(self, **kwargs):
        "Returns a URL to this user's profile."
        return 'https://foursquare.com/user/%s' % kwargs['user_id']


@daemon_class
class FoursquareDaemon(Daemon, Foursquare):

    "Foursquare Daemon OAuth2 API for Lightning"
    @recurring
    def values_from_profile(self, **kwargs):
        'Values from profile'
        def write_additional_values(data):
            user = data['response']['user']
            # Write some counts ourselves.
            return defer.gatherResults([
                self.write_datum(method=method, data=datum, **kwargs)
                for method, datum in {
                    'num_friends': user.get('friends', {})['count'],
                    'num_checkins': user.get('checkins', {})['count'],
                    'num_mayorships': user.get('mayorships', {})['count'],
                    'num_photos': user.get('photos', {})['count'],
                    'num_lists': sum([
                        item['count']
                        for item in user.get('lists', {}).get('groups', [{}])
                    ]),
                }.iteritems()
            ]).addCallback(lambda ign: None)

        return self.request(
            path='users/self',
            **kwargs
        ).addCallback(write_additional_values)

    @recurring
    @enqueue_delta(days=30)
    def profile(self, **kwargs):
        "Returns this user's profile."
        def build_profile(response):
            user = response.get('response', {}).get('user', {})
            name = build_full_name(user.get('firstName'), user.get('lastName'))
            profile_picture_link = None
            if user.get('photo'):
                profile_picture_link = '%s100x100%s' % (user['photo'].get('prefix'), user['photo'].get('suffix'))
            return Profile(
                name=name,
                email=user.get('contact', {}).get('email'),
                bio=user.get('bio'),
                gender=user.get('gender'),
                profile_picture_link=profile_picture_link,
                profile_link='https://foursquare.com/user/%s' % kwargs['authorization'].user_id,
                username=None,
            )

        return self.request(
            path='users/self',
            **kwargs
        ).addCallback(build_profile)


@service_class
class FoursquareWeb(Foursquare, MultiEndPointFeedService, ContentAuthoredService, Web):

    "Foursquare Web OAuth2 API for Lightning"
    daemon_class = FoursquareDaemon

    def start_authorization(self, client_name, args):
        """Start the authorization process.
        Get authorization URL.
        Args:
            redirect_uri: string, URL to redirect to after request.
        """
        try:
            self.ensure_arguments(['redirect_uri'], args)
            args['client_id'] = self.app_info[self.environment]['app_id']
            args['response_type'] = 'code'
        except (KeyError, ValueError, LightningError) as exc:
            raise AuthError(exc.message)
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
            token = response['access_token']

            resp = yield self.request(
                path='users/self',
                token=token,
            )

            authorization = yield Authz(
                client_name=client_name,
                service_name=self.name,
                token=token,
                user_id=resp['response']['user']['id'],
            ).set_token(self.datastore)
        except (KeyError, ValueError, AuthError) as exc:
            raise AuthError(exc.message)
        defer.returnValue(authorization)

    # Below is the list of functions required to support reading the feed

    def get_feed(self, **kwargs):
        """
        Foursquare-specific code for getting the feed

        Fetch the profile, and store it for later so it can be used by `parse_*` methods,
        then call each relevant enpoint and parse items from each accordingly.
        """

        def get_profile(profile):
            kwargs['profile'] = profile
            endpoint_to_parse_method = {
                'users/self/checkins': 'parse_checkin',
            }

            # Delegate processing to MultiEndPointFeedService.get_feed()
            return super(FoursquareWeb, self).get_feed(
                endpoint_to_parse_method=endpoint_to_parse_method, **kwargs
            )

        return self.profile(**kwargs).addCallback(get_profile)

    def get_feed_args(self, **kwargs):
        'The feed args'
        return {'sort': 'newestfirst'}

    def get_feed_limit(self, limit):
        'Return the limit in the right format'
        return {'limit': limit}

    def get_feed_timestamp(self, **kwargs):
        'Return the timestamp in the right format'
        timestamp = kwargs.get('timestamp', int(time.time()))
        if kwargs.get('forward', False):
            return {'afterTimestamp': timestamp}
        else:
            return {'beforeTimestamp': timestamp}

    def get_author(self, user_id, profile):
        author = {
            'user_id': user_id,
            'username': None,
        }
        if profile:
            author['name'] = profile.get('name')
            author['profile_link'] = self.profile_url(user_id=user_id)
            author['profile_picture_link'] = profile.get('profile_picture_link')
        return author

    def get_location(self, venue):
        if venue:
            return {
                'latitude': venue.get('location', {}).get('lat'),
                'longitude': venue.get('location', {}).get('lng'),
                'name': venue.get('name')
            }
        return None

    def parse_checkin(self, post, **kwargs):
        "Parse a checkin for inclusion into the timeline"
        # Build author

        author = self.get_author(
            kwargs['authorization'].user_id,
            kwargs.get('profile')
        )

        # Build activity
        text = 'Checkin'
        activity_link = None

        if post.get('venue'):
            text += ' at ' + post['venue'].get('name', 'unknown venue')
            if post['venue'].get('id'):
                activity_link = "https://foursquare.com/venue/%s" % post['venue'].get('id')
            location = self.get_location(post.get('venue'))
        elif post.get('location'):
            if post['location'].get('name'):
                text += ' at ' + post['location']['name']
            else:
                text += ' at (' \
                    + post['location'].get('lat', 'LAT') + ',' \
                    + post['location'].get('lng', 'LONG') + ')'
        else:
            text += ' at unknown'

        if post.get('shout'):
            text += ': ' + post['shout']

        activity = {
            'activity_link': activity_link,
            'story': text,
            'location': location,
        }

        if len(post.get('photos').get('items', [])) > 0:
            item = post['photos']['items'][0]
            if item.get('prefix') and item.get('suffix'):
                activity['picture_link'] = item['prefix'] + 'original' + item['suffix']
                activity['thumbnail_link'] = item['prefix'] + '100x100' + item['suffix']

        # Existence indicates privacy.
        if post.get('private'):
            is_private = 1
        else:
            is_private = 0

        return StreamEvent(
            metadata=dict(
                post_id=post['id'],
                timestamp=post.get('createdAt', 0),
                is_private=is_private,
            ),
            author=author,
            activity=activity,
        )

    # TO HERE
    #

    @api_method('GET')
    def account_created_timestamp(self, **kwargs):
        """Returns the approximate (to within a month) time at which the user first posted to this service"""
        FOURSQUARE_LAUNCH_TIMESTAMP = 1072915200

        return super(FoursquareWeb, self).account_created_timestamp(
            low_start=FOURSQUARE_LAUNCH_TIMESTAMP,
            **kwargs
        )


FoursquareWeb.api_method(
    'num_friends', key_name='num',
    present="Number of friends",
    interval="Number of friends over time",
)
FoursquareWeb.api_method(
    'num_checkins', key_name='num',
    present="Number of check-ins",
    interval="Number of check-ins over time",
)
FoursquareWeb.api_method(
    'num_mayorships', key_name='num',
    present="Number of mayorships",
    interval="Number of mayorships over time",
)
FoursquareWeb.api_method(
    'num_photos', key_name='num',
    present="Number of photos",
    interval="Number of photos over time",
)
FoursquareWeb.api_method(
    'num_lists', key_name='num',
    present="Number of lists",
    interval="Number of lists over time",
)
FoursquareWeb.api_method(
    'profile',
    present="Returns this user's profile.",
)

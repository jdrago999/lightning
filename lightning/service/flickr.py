"Generic docstring A"
from __future__ import absolute_import

from lightning.service.base import (
    ServiceOAuth1, Daemon, Web, ContentAuthoredService, service_class, recurring,
    daemon_class, enqueue_delta, check_account_created_timestamp, api_method,
    Profile
)


from lightning.error import Error, AuthError, LightningError
from lightning.model.authorization import Authz
from lightning.model.stream_event import StreamEvent
from lightning.utils import compose_url
from twisted.internet import defer

import json
import time
import calendar
import dateutil.parser
import urllib
import urlparse

class Flickr(ServiceOAuth1):
    """Flickr OAuth1.0a API for Lightning.
    Lightning's implementation of Flickr's REST API.
    API:
       http://www.flickr.com/services/api/
    """
    name = 'flickr'

    def __init__(self, *args, **kwargs):
        """Create a new Flickr service object.
        Attributes:
            app_info: dict, API keys and secrets per environment.
            domain: string, Domain the service hits.
            base_url: string, URL of domain with correct protocol.
            auth_url: string, URL used to build authorization URL.
            access_token_url: string, URL used to obtain an access_token.
            endpoint_url: string, URL used to call service methods.
        """
        super(Flickr, self).__init__(*args, **kwargs)

        self.app_info = {
            'local': {
                'app_id': 'fake',
                'app_secret': 'fake'
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

        self.domain = 'api.flickr.com'
        self.base_url = 'https://' + self.domain + "/services"
        self.auth_url = self.base_url + '/oauth/request_token'
        self.access_token_url = self.base_url + '/oauth/access_token'
        self.endpoint_url = self.base_url + '/rest'

        self.oauth_version = '1.0'
        self.oauth_signature_method = 'HMAC-SHA1'

    def parse_error(self, status, url, headers, body, **kwargs):
        """Parse errors from service"""
        body_errors = {
            96: Error.INVALID_TOKEN,
            97: Error.INVALID_TOKEN,
            98: Error.INVALID_TOKEN,
            99: Error.INSUFFICIENT_PERMISSIONS,
            100: Error.INVALID_TOKEN,
            105: Error.OVER_CAPACITY,
            111: Error.BAD_PARAMETERS,
            112: Error.BAD_PARAMETERS,
        }
        msg = 'Unknown response'
        retry_at = int(time.time() + (60*60))

        # Error message from HTTP status
        if status in self.status_errors:
            msg = self.status_errors[status]

        # Error message from body
        try:
            content = json.loads(body)
            body_error = content.get('code', {})
            msg = body_errors.get(body_error, msg)
            msg = content.get('message', msg)
        except (TypeError, ValueError):
            pass
        self.raise_error(msg, retry_at)

    def request_with_paging(self, path, callback, data_name='items', **kwargs):
        """Page through all the results for the givien endpoint and call `callback` on each. Flickr
        uses page number and page index for page parameters, so we need to inform the parent method
        of these fields.

        Returns: A deferred request which when completed will have called each page of results with `callback`

        Inputs:
            * path - the relative path of the endpoint to retrieve
            * callback - method to be called with each page of results
            * kwargs - other arguments to pass along to the request method"""

        kwargs['data_name'] = data_name
        return super(Flickr, self).request_with_paging(path, callback,
            offset_increase=1,
            starting_offset=1,
            limit_field='per_page',
            offset_field='page',
            limit=500,
            **kwargs
        )

    ############################################
    # Below is the list of functions required to support reading the feed
    ############################################

    def transform_paged_response(self, resp):
        return resp['photos']

    def get_feed(self, **kwargs):
        """set the author to be used in parsed photos, and returns the stream of photos in the
        standard LG format"""

        def get_feed_with_photos(author_profile):
            self.author_profile = author_profile
            return super(Flickr, self).get_feed(data_name='photo', **kwargs)

        return self.profile(**kwargs).addCallback(get_feed_with_photos)


    def get_feed_url(self, **kwargs):
        """return the base url for the feed for Flickr.  Since Flickr endpionts are all
        querystring based, we just use the base url"""
        return ''


    def get_feed_timestamp(self, timestamp=None, forward=False, **kwargs):
        "return the parameters we need to send to the Flickr API to get the specified date range"

        # We set the default timestamp here, because if we do so above, it will be set to the time that
        # the lightning service started, not the current time
        if not timestamp:
            timestamp = int(time.time())

        if forward:
            time_params =  {
                'min_upload_date': timestamp,
            }
        else:
            time_params =  {
                'max_upload_date': timestamp,
            }
        return time_params

    def get_feed_args(self, **kwargs):
        return {
            'user_id': kwargs['authorization'].user_id,
            'format': 'json',
            'nojsoncallback': '1',
            'method': 'flickr.photos.search',
            'extras': 'original_format,date_upload',
        }


    def get_feed_limit(self, limit):
        return {'per_page': limit}

    def construct_photo_url(self, farm_id, server_id, photo_id, secret, size):
        """Construct a Flickr photo url.
        Args:
            size: 't' for thumbnail, 'z' for medium, or 'b' for large
        """
        if farm_id and server_id and photo_id and secret:
            return "http://farm%s.staticflickr.com/%s/%s_%s_%s.jpg" % \
                (farm_id, server_id, photo_id, secret, size)
        return None

    def parse_post(self, post, **kwargs):
        "Take a photo as returned by the flickr api and return it in standard LG stream format"
        author = {
            'user_id': post.get('owner'),
            'name': self.author_profile['name'],
            'username': self.author_profile['username'],
            'profile_picture_link': self.author_profile['profile_picture_link'],
            'profile_link': self.author_profile['profile_link'],
        }

        picture_link = self.construct_photo_url(
            post.get('farm'),
            post.get('server'),
            post.get('id'),
            post.get('secret'),
            'z',
        )
        thumbnail_link = self.construct_photo_url(
            post.get('farm'),
            post.get('server'),
            post.get('id'),
            post.get('secret'),
            't',
        )

        activity = {
            'story': "%s uploaded a photo." % author['name'],
            'picture_link': picture_link,
            'thumbnail_link': thumbnail_link,
            'name': post.get('title'),
        }

        timestamp = int(post.get('dateupload', 0))
        if int(post.get('ispublic', 0)) == 0:
            is_private = 1
        else:
            is_private = 0

        return StreamEvent(
            metadata={
                'post_id': post.get('id'),
                'timestamp': timestamp,
                'service': self.name,
                'is_private': is_private,
            },
            author=author,
            activity=activity,
        )


    # TO HERE
    ############################################

    def construct_endpoint_url(self, **kwargs):
        args = kwargs
        args['format'] = 'json'
        args['nojsoncallback'] = '1'
        return compose_url('', query=kwargs)

    def profile_url(self, user_id):
        return self.construct_endpoint_url(
            method='flickr.people.getInfo',
            user_id=user_id
        )


@daemon_class
class FlickrDaemon(Flickr, Daemon):
    """Flickr Daemon OAuth1 API for Lightning"""

    @recurring
    def num_photos(self, **kwargs):
        'pull in number of photos from the profile'
        def parse_photos(data):
            person = data['person']
            photos = person['photos']
            # Write some counts ourselves.
            return {'num': photos.get('count', {}).get('_content', 0)}

        authorization = kwargs['authorization']
        url = self.profile_url(authorization.user_id)
        return self.request(
            path=url,
            **kwargs
        ).addCallback(parse_photos)


    def get_count(self, object_type, response_type=None, authorization=None):
        """fetches the total field from the given object type's getList method in the flickr API  and returns it
        Inputs:
            * object_type - this is the type of flickr object to be counted, typically pluralized
            * response_type - this is the name of the object type as it will appaea in the Flickr response.
                It defaults to the `object_type` value.
            * authorization - the Lightning Authorizatoin used to authenticate the current user"""

        if not response_type:
            response_type = object_type

        def parse_count(response):
            return {'num': response.get(response_type, {}).get('total', 0)}

        args = {
            'format': 'json',
            'nojsoncallback': '1',
            'method': "flickr.%s.getList" % object_type,
        }

        return self.request(path='', args=args, authorization=authorization).addCallback(parse_count)

    @recurring
    def num_contacts(self, **kwargs):
        "fetches this users number of contacts and returns it"
        return self.get_count('contacts', authorization=kwargs['authorization'])

    @recurring
    def num_favorites(self, **kwargs):
        "fetches this users number of favorites and returns it"
        return self.get_count('favorites', response_type='photos', authorization=kwargs['authorization'])

    @recurring
    def num_galleries(self, **kwargs):
        "fetches this users number of galleries and returns it"
        return self.get_count('galleries', authorization=kwargs['authorization'])

    @recurring
    def num_photosets(self, **kwargs):
        "fetches this users number of photosets and returns it"
        return self.get_count('photosets', authorization=kwargs['authorization'])

    @recurring
    @enqueue_delta(days=30)
    def profile(self, **kwargs):
        "Returns this user's profile."
        def construct_portrait_url(person):
            icon_farm = person['iconfarm']
            icon_server = person['iconserver']
            user_id = person['nsid']
            url = "http://farm%s.staticflickr.com/%s/buddyicons/%s.jpg" % (icon_farm, icon_server, user_id)
            return url

        def build_profile(response):
            person = response.get('person', {})
            profile_picture_link = construct_portrait_url(person)
            return Profile(
                name=person.get('realname', {}).get('_content'),
                username=person.get('username', {}).get('_content'),
                profile_link=person.get('profileurl', {}).get('_content'),
                profile_picture_link=profile_picture_link,
                bio=person.get('description', {}).get('_content'),
            )

        authorization = kwargs['authorization']
        url = self.profile_url(authorization.user_id)
        return self.request(
            path=url,
            **kwargs
        ).addCallback(build_profile)


@service_class
class FlickrWeb(Flickr, ContentAuthoredService, Web):
    """Flickr Web OAuth1 API for Lightning"""
    daemon_class = FlickrDaemon

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

        except (KeyError, ValueError, LightningError) as exc:
            raise AuthError(exc.message)

        defer.returnValue(
            self.base_url + '/oauth/authorize?perms=read&oauth_token=' +
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
            user_id = response['user_nsid'][0]

            authorization = yield Authz(
                client_name=client_name,
                service_name=self.name,
                token=token,
                user_id=user_id,
                secret=secret,
            ).set_token(self.datastore)
        except (KeyError, ValueError, LightningError) as exc:
            raise AuthError(exc.message)
        defer.returnValue(authorization)

    @api_method('GET')
    @check_account_created_timestamp
    def account_created_timestamp(self, **kwargs):
        """Returns the timestamp this user account was created on"""

        def parse_timestamp(resp):
            try:
                date = dateutil.parser.parse(resp['person']['photos']['firstdatetaken']['_content']).utctimetuple()
                t = calendar.timegm(date)
            except:
                t = None

            return {
                'timestamp': t,
            }

        url = self.profile_url(kwargs['authorization'].user_id)
        return self.request(
            path=url,
            **kwargs
        ).addCallback(parse_timestamp)


FlickrWeb.api_method(
    'num_photos',
    key_name='num',
    present='Number of photos.',
    interval='Number of photos over time.',
)

FlickrWeb.api_method(
    'num_contacts',
    key_name='num',
    present='Number of contacts this user has added.',
    interval='Number of contacts this user has added over time.',
)

FlickrWeb.api_method(
    'num_favorites',
    key_name='num',
    present='Number of photos this user has favorited.',
    interval='Number of photos this user has favorited over time.',
)

FlickrWeb.api_method(
    'num_galleries',
    key_name='num',
    present='Number of galleries this user has created.',
    interval='Number of galleries this user has created over time.',
)

FlickrWeb.api_method(
    'num_photosets',
    key_name='num',
    present='Number of photosets this user has created.',
    interval='Number of photosets this user has created over time.',
)

FlickrWeb.api_method(
    'profile',
    present="Returns this user's profile.",
)

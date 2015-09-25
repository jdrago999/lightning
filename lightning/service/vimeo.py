"Generic docstring A"
from __future__ import absolute_import

from lightning.service.base import (
    ServiceOAuth1, Daemon, Web, StreamCachedService, ContentAuthoredService,
    service_class, recurring, daemon_class, enqueue_delta, api_method,
    check_account_created_timestamp, Profile
)


from lightning.error import Error, AuthError, LightningError
from lightning.model.authorization import Authz
from lightning.model.stream_event import StreamEvent, StreamType
from lightning.utils import compose_url
from twisted.internet import defer

import calendar
from dateutil import parser as dateparser
import json
import time
import urllib
import urlparse


class Vimeo(ServiceOAuth1):
    """Vimeo OAuth1.0a API for Lightning.
    Lightning's implementation of Vimeo's REST API.
    API:
        http://developer.vimeo.com/
    """
    name = 'vimeo'

    def __init__(self, *args, **kwargs):
        """Create a new Vimeo service object.
        Attributes:
            app_info: dict, API keys and secrets per environment.
            domain: string, Domain the service hits.
            base_url: string, URL of domain with correct protocol.
            auth_url: string, URL used to build authorization URL.
            access_token_url: string, URL used to obtain an access_token.
            endpoint_url: string, URL used to call service methods.
        """
        super(Vimeo, self).__init__(*args, **kwargs)

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

        self.domain = 'vimeo.com'
        self.base_url = 'https://' + self.domain
        self.auth_url = self.base_url + '/oauth/request_token'
        self.access_token_url = self.base_url + '/oauth/access_token'
        self.endpoint_url = self.base_url + '/api/rest/v2'

        self.oauth_version = '1.0'
        self.oauth_signature_method = 'HMAC-SHA1'
        # XXX: Vimeo sends errors with 200 status code, so check every Vimeo
        # response for an error before processing.
        self.good_statuses = []

    def parse_error(self, status, url, headers, body, **kwargs):
        """Parse errors from service"""
        body_errors = {
            99: Error.INSUFFICIENT_PERMISSIONS,
            105: Error.OVER_CAPACITY,
            401: Error.INVALID_TOKEN
        }
        msg = None
        retry_at = int(time.time() + (60*60))

        # Error message from HTTP status
        if status in self.status_errors:
            msg = self.status_errors[status]

        # Error message from body
        try:
            content = json.loads(body)
            body_error = content.get('err', {}).get('code')
            msg = content.get('err', {}).get('msg', msg)
            msg = body_errors.get(body_error, msg)
        except (TypeError, ValueError):
            pass

        # XXX: Ignore 'Page out of bounds' errors from Vimeo which basically
        # indicates that we're out of results. Only raise an error here if we
        # actually get an error message, since Vimeo sends 200 pages with errors
        if msg != None and msg != 'Page out of bounds':
            self.raise_error(msg, retry_at)

    def request_with_paging(self, path, callback, **kwargs):
        """
        This returns a Deferred that knows how to page through results.

        The assumption is that the callback is doing some sort of useful work,
        likely with an accumulator of some sort.

        Note: This request_with_paging is different from the other services
        because Vimeo  doesn't provide pagination URLs in its responses. So,
        we must provide our own pagination using page/per_page.

        Vimeo returns results like this:
        {
            "generated_in": "0.0203",
            "stat": "ok",
            "videos":{
                "on_this_page": "3",
                "page": "1",
                "perpage": "50",
                "total": "3",
                "video":[
                    { ... }, { ... }, { ... }
            }
        }
        Thus the caller needs to specify where to get at the actual results by specifying the
        `result_field_name` that contains pagaing data, and the `result_list_field_name`
        which specifies the actual results inside that. Note how, confusingly 'videos' contains
        a single object, while 'video' contains an array.  Since most requests for Vimeo are
        likely about videos, we default to that.
        """
        result_field_name = kwargs.get('result_field_name', 'videos')
        result_list_field_name = kwargs.get('result_list_field_name', 'video')

        stopback = kwargs.get('stopback', lambda: False)

        kwargs['args'] = kwargs.get('args', {})
        paging = {
            'page': kwargs['args'].get('page', 1),
            'per_page': 50,
        }
        kwargs['args']['per_page'] = paging['per_page']

        def collect_data(response):
            """Middleware to handle deferred from callback"""
            data = response.get(result_field_name, {})
            result_list = data.get(result_list_field_name, [])
            return defer.maybeDeferred(callback, result_list).addCallback(lambda ign: response)

        def pager(response):
            data = response.get(result_field_name, {})
            result_list = data.get(result_list_field_name, [])

            if stopback() or len(result_list) == 0:
                return
            paging['page'] += 1
            kwargs['args']['page'] = paging['page']

            self.request(path=path, **kwargs).addCallback(collect_data).addCallback(pager)

        return self.request(path=path, **kwargs).addCallback(collect_data).addCallback(pager)

    ############################################
    # Below is the list of functions required to support reading the feed
    ############################################

    @defer.inlineCallbacks
    def get_author(self, owner_id, **kwargs):
        kwargs['args'] = {
            'format': 'json',
            'method': 'vimeo.people.getInfo',
            'user_id': owner_id
        }
        kwargs['path'] = ''
        response = yield self.request(**kwargs)
        person = response.get('person', {})
        portrait_url = self.extract_portrait_url(person, size=300)

        author = {
            'user_id': owner_id,
            'name': person.get('display_name', ''),
            'username': person.get('username', ''),
            'profile_picture_link': portrait_url,
            'profile_link': person.get('profileurl', ''),
        }

        defer.returnValue(author)

    @defer.inlineCallbacks
    def parse_post(self, post, **kwargs):
        "Parse a feed post"
        # Build author
        owner_id = post.get('owner', '')
        author = yield self.get_author(owner_id, **kwargs)

        # Build activity
        story = '%s uploaded a video' % (author['name'])
        if post.get('title'):
            story = '%s: "%s"' % (story, post['title'])

        video_id = post.get('id', 0)
        activity = {
            'story': story,
            'type': StreamType.VIDEO_EMBED,
            'video_id': video_id,
            'activity_link': "https://vimeo.com/%s" % video_id,
        }

        if post.get('privacy') == 'anybody':
            is_private = 0
        else:
            is_private = 1

        event = StreamEvent(
            metadata={
                'post_id': "video:%s" % video_id,
                'timestamp': calendar.timegm(dateparser.parse(post.get('upload_date', '')).utctimetuple()),
                'service': self.name,
                'is_private': is_private,
            },
            author=author,
            activity=activity,
        )
        defer.returnValue(event)

    # TO HERE
    ############################################

    def profile_url(self, token):
        return compose_url('', query={
            'format': 'json',
            'method': 'vimeo.people.getInfo',
            'user_id': token
        })

    def extract_portrait_url(self, person, size=300):
        portrait_list = person.get("portraits", {}).get("portrait", [])
        portrait_urls = [portrait.get("_content", '') for portrait in portrait_list
                if portrait["height"] == str(size)]

        if portrait_urls:
            return portrait_urls[0]
        else:
            return ''


@daemon_class
class VimeoDaemon(Vimeo, StreamCachedService, Daemon):
    """Vimeo Daemon OAuth1 API for Lightning"""

    @recurring
    def iterate_over_videos(self, **kwargs):
        if not kwargs.get('args'):
            kwargs['args'] = {}
        kwargs['args']['format'] = 'json'
        kwargs['args']['method'] = 'vimeo.videos.getUploaded'
        kwargs['args']['user_id'] = kwargs['authorization'].user_id

        return self.parse_and_save_paged_stream(path='', **kwargs)

    @recurring
    def values_from_profile(self, **kwargs):
        "Returns this user's profile."
        def write_additional_values(data):
            user = data['person']

            # Write some counts ourselves.
            return defer.gatherResults([
                self.write_datum(method=method, data=datum, **kwargs)
                for method, datum in {
                    'num_contacts': user['number_of_contacts'],
                    'num_uploads': user['number_of_uploads'],
                    'num_likes': user['number_of_likes'],
                    'num_videos': user['number_of_videos'],
                    'num_videos_appears_in': user['number_of_videos_appears_in'],
                    'num_albums': user['number_of_albums'],
                    'num_channels': user['number_of_channels'],
                    'num_groups': user['number_of_groups'],
                }.iteritems()
            ]).addCallback(lambda ign: None)

        authorization = kwargs['authorization']
        url = self.profile_url(authorization.token)
        return self.request(
            path=url,
            **kwargs
        ).addCallback(write_additional_values)

    @recurring
    @enqueue_delta(days=30)
    def profile(self, **kwargs):
        "Returns this user's profile."

        def build_profile(response):
            person = response['person']
            portrait_url = self.extract_portrait_url(person, size=300)

            return Profile(
                name=person.get('display_name'),
                username=person.get('username'),
                profile_picture_link=portrait_url,
                profile_link=person.get('profileurl'),
                bio=person.get('bio'),
            )

        url = self.profile_url(kwargs['authorization'].token)

        return self.request(
            path=url,
            **kwargs
        ).addCallback(build_profile)


@service_class
class VimeoWeb(Vimeo, StreamCachedService, ContentAuthoredService, Web):
    """Vimeo Web OAuth1 API for Lightning"""
    daemon_class = VimeoDaemon

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
            self.base_url + '/oauth/authorize?oauth_token=' +
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

            self.token = response['oauth_token'][0]
            secret = response['oauth_token_secret'][0]

            url = self.profile_url(self.token)
            resp = yield self.request(
                path=url,
                token=self.token,
                secret=secret,
            )

            authorization = yield Authz(
                client_name=client_name,
                service_name=self.name,
                token=self.token,
                user_id=resp['person']['id'],
                secret=secret,
            ).set_token(self.datastore)

        except (KeyError, ValueError, LightningError) as exc:
            raise AuthError(exc.message)

        defer.returnValue(authorization)

    @api_method('GET')
    @check_account_created_timestamp
    def account_created_timestamp(self, **kwargs):
        """Returns the time at which the user first posted to to this serivice"""

        def parse_timestamp(resp):
            person = resp['person']

            created = person.get('created_on')
            t = None
            if created:
                t = calendar.timegm(dateparser.parse(created).utctimetuple())

            return {
                'timestamp': t,
            }

        url = self.profile_url(kwargs['authorization'].token)

        return self.request(
            path=url,
            **kwargs
        ).addCallback(parse_timestamp)


VimeoWeb.api_method(
    'num_contacts',
    key_name='num',
    present='Number of contacts.',
    interval='Number of contacts over time.',
)

VimeoWeb.api_method(
    'num_uploads',
    key_name='num',
    present='Number of uploads.',
    interval='Number of uploads over time.',
)

VimeoWeb.api_method(
    'num_likes',
    key_name='num',
    present='Number of likes.',
    interval='Number of likes over time.',
)

VimeoWeb.api_method(
    'num_videos',
    key_name='num',
    present='Number of videos.',
    interval='Number of videos over time.',
)

VimeoWeb.api_method(
    'num_videos_appears_in',
    key_name='num',
    present='Number of videos appears in.',
    interval='Number of videos appears in over time.',
)

VimeoWeb.api_method(
    'num_albums',
    key_name='num',
    present='Number of albums.',
    interval='Number of albums over time.',
)

VimeoWeb.api_method(
    'num_channels',
    key_name='num',
    present='Number of channels.',
    interval='Number of channels over time.',
)

VimeoWeb.api_method(
    'num_groups',
    key_name='num',
    present='Number of groups.',
    interval='Number of groups over time.',
)

VimeoWeb.api_method(
    'profile',
    present="Returns this user's profile.",
)

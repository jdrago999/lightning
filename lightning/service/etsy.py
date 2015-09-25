"Generic docstring A"
from __future__ import absolute_import

from lightning.service.base import (
    ServiceOAuth1, Daemon, Web, StreamCachedService, service_class, recurring,
    api_method, daemon_class, enqueue_delta, check_account_created_timestamp,
    Profile
)


from lightning.error import Error, AuthError, LightningError
from lightning.model.authorization import Authz
from lightning.model.limit import Limit
from lightning.model.stream_event import StreamEvent, StreamType
from lightning.utils import build_full_name, create_post_id
import logging
from twisted.internet import defer

import urllib
import urlparse
import time
from datetime import timedelta

class Etsy(ServiceOAuth1):
    """Etsy OAuth1.0a API for Lightning.
    Lightning's implementation of Etsy's REST API.
    API:
        http://www.etsy.com/developers/documentation/
    """
    name = 'etsy'

    def __init__(self, *args, **kwargs):
        """Create a new Etsy service object.
        Attributes:
            app_info: dict, API keys and secrets per environment.
            domain: string, Domain the service hits.
            base_url: string, URL of domain with correct protocol.
            auth_url: string, URL used to build authorization URL.
            access_token_url: string, URL used to obtain an access_token.
            endpoint_url: string, URL used to call service methods.
        """
        super(Etsy, self).__init__(*args, **kwargs)

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

        permissions = '%20'.join([
            "email_r",
            "listings_r",
            "transactions_r",
            "profile_r",
            "favorites_rw",
            "shops_rw",
            "cart_rw",
            "recommend_rw",
            "feedback_r",
            "treasury_r",
            "treasury_w"
        ])

        self.domain = 'openapi.etsy.com'
        self.base_url = 'https://' + self.domain + "/v2"
        self.auth_url = self.base_url + '/oauth/request_token?scope=%s' % permissions
        self.access_token_url = self.base_url + '/oauth/access_token'
        self.endpoint_url = self.base_url

        self.oauth_version = '1.0'
        self.oauth_signature_method = 'HMAC-SHA1'

        # These are used solely for testing rate limiting
        self.request_count = 0
        self.start_time = time.time()


    @Limit.request_rate(1, every='second')
    def request(self, *args, **kwargs):

        from pprint import pformat
        if kwargs.get('authorization'):
            logging.error("request to etsy: %s " % kwargs.get('authorization').uuid)
        return super(Etsy, self).request(*args, **kwargs)

    def parse_error(self, status, url, headers, body, **kwargs):
        """Parse errors from service"""
        msg = 'Unknown response'
        retry_at = int(time.time() + (60 * 60 * 2))
        logging.error(headers)

        # Error message from HTTP status
        if status in self.status_errors:
            msg = self.status_errors[status]
        # Some 403 errors may actually be invalid tokens
        if msg == Error.RATE_LIMITED and headers.get('X-ErrorDetail', ['None'])[0] == 'oauth_problem=token_rejected':
            msg = Error.INVALID_TOKEN
        self.raise_error(msg, retry_at)


    def request_with_paging(self, path, callback, **kwargs):
        """Page through all the results for the givien endpoint and call `callback` on each. Etsy
        uses limit and offset for page parameters, so we need to inform the parent method
        of these fields.

        Args:
            * path - the relative path of the endpoint to retrieve
            * callback - method to be called with each page of results
            * kwargs - other arguments to pass along to the request method

        Yields: A deferred request which when completed will have called each page of results with `callback`"""

        limit = 100
        return super(Etsy, self).request_with_paging(path, callback,
            offset_increase=limit,
            starting_offset=0,
            limit_field='limit',
            offset_field='offset',
            limit=limit,
            data_name="results",
            **kwargs
        )

    def profile_link(self, username):
        if username:
            return "http://etsy.com/people/%s" % username
        return None

    ############################################
    # Below are the functions required to support reading the feed
    ############################################

    @defer.inlineCallbacks
    def parse_posts(self, entry_list, parse_method='parse_post', **kwargs):
        """ Take a list of entries from etsy's activiy feed, and convert it into a list of LG
        formatted posts for the stream.

        This version processes posts in sequence rather than in parallel, due to the way etsy handles rate limits"""

        parse_func = getattr(self, parse_method)

        results = []

        for entry in entry_list:
            result = yield parse_func(entry, **kwargs)
            results.append(result)

        defer.returnValue(results)

    @defer.inlineCallbacks
    def parse_post(self, post, **kwargs):
        "Parse a feed post"

        # Determine post type
        post_type = 'transaction'
        if 'message' in post:
            post_type = 'review'

        # Build author
        author = {}
        buyer_id = post.get('buyer_user_id')
        if buyer_id:
            kwargs['path'] = 'users/%s/profile' % buyer_id
            response = yield self.request(**kwargs)
            results = response.get('results')
            if len(results) >= 1:
                buyer = results[0]
                profile_picture_link = buyer.get('image_url_75x75')
                if profile_picture_link == 'https://www.etsy.com/images/avatars/default_avatar_75px.png':
                    profile_picture_link = None
                author = {
                    'user_id': buyer_id,
                    'name': "%s %s" % (buyer.get('first_name'), buyer.get('last_name')),
                    'username': buyer.get('login_name'),
                    'profile_picture_link': profile_picture_link,
                    'profile_link': self.profile_link(buyer.get('login_name')),
                }

        # Build activity
        activity = {}
        if post_type == 'transaction':
            story = '%s bought "%s" from you' % (author['username'], post['title'])
            activity['type'] = StreamType.TRANSACTION
        elif post_type == 'review':
            story = post['message']
            # Don't send back Etsy's placeholder image.
            if post['image_url_fullxfull'] != 'https://www.etsy.com/images/grey.gif':
                activity['picture_link'] = post['image_url_fullxfull']
                activity['thumbnail_link'] = post.get('image_url_155x125')
        activity['story'] = story
        activity['name'] = post.get('title')
        activity['description'] = post.get('description')

        image_id = post.get('image_listing_id')
        listing_id = post.get('listing_id')

        if image_id and listing_id:
            kwargs['path'] = 'listings/%s/images/%s' % (listing_id, image_id)

            try:
                response = yield self.request(**kwargs)
                results = response.get('results')
                if len(results) >= 1:
                    image = results[0]
                    activity['picture_link'] = image.get('url_fullxfull')
                    activity['thumbnail_link'] = image.get('url_170x135')
            except Exception, e:
                activity['picture_link'] = None
                activity['thumbnail_link'] = None

        defer.returnValue(StreamEvent(
            metadata={
                'post_id': create_post_id(post_type, post['transaction_id']),
                'timestamp': post.get('creation_tsz', 0),
                'service': self.name,
                'is_private': 0,  # XXX: Defaults to public for now
            },
            author=author,
            activity=activity,
        ))

    # TO HERE
    ############################################

@daemon_class
class EtsyDaemon(Etsy, StreamCachedService, Daemon):
    """Etsy Daemon OAuth1 API for Lightning"""
    # Per http://www.etsy.com/developers/documentation/getting_started/api_basics
    # we will get more requests every 2 hours.
    _delay = timedelta(minutes=120)

    @recurring
    @enqueue_delta(hours=2)
    @defer.inlineCallbacks
    def iterate_over_transactions_and_reviews(self, **kwargs):
        paths = ['users/__SELF__/feedback/as-subject']
        results = []
        shop_name = yield self.get_shop_name(**kwargs)
        if shop_name:
            paths.append('shops/%s/transactions' % (shop_name))
        def extend_data(data):
            results.extend(data)

        for p in paths:
            response = yield self.request_with_paging(
                path=p,
                callback=extend_data,
                **kwargs
            )

        self.parse_and_save_stream_data(results, **kwargs)

    def get_shop_name(self, **kwargs):
        def parse_shop_name(response):
            results = response.get('results', [])
            if len(results) > 0:
                return results[0].get('shop_name')
            else:
                return None

        return self.request(path='users/__SELF__/shops', **kwargs).addCallback(parse_shop_name)

    @recurring
    def values_from_user_record(self, **kwargs):
        def write_values(response):
            results = response.get('results', [])

            if len(results) > 0:
                feedback = results[0].get('feedback_info', {})
                # If we have no feedback, make the percentage score 0 instead of null
                score = feedback.get('score', 0) or 0

                return defer.gatherResults([
                        self.write_datum(method=method, data=datum, **kwargs)
                        for method, datum in {
                            'positive_feedback_percentage': score,
                            'num_feedback': feedback.get('count', 0),
                        }.iteritems()
                ]).addCallback(lambda ign: None)

        return self.request(path='users/__SELF__', **kwargs).addCallback(write_values)

    @recurring
    def num_favorites(self, **kwargs):
        """Number of favorites"""
        def parse_favorites(response):
            return {'num': response['count']}
        return self.request(path='users/__SELF__/favorites/listings', **kwargs).addCallback(parse_favorites)

    @recurring
    @defer.inlineCallbacks
    def num_active_listings(self, **kwargs):
        "Number of active listings"
        listings = yield self.get_count('shops/%s/listings/active', **kwargs)
        defer.returnValue(listings)

    @recurring
    @defer.inlineCallbacks
    def num_sales(self, **kwargs):
        "Number of sales"
        sales = yield self.get_count('shops/%s/transactions', **kwargs)
        defer.returnValue(sales)

    @recurring
    @defer.inlineCallbacks
    def num_feedback_written(self, **kwargs):
        """Number of feedback written"""
        response = yield self.request(path='users/__SELF__/feedback/as-author', **kwargs)
        defer.returnValue({'num': response['count']})

    @defer.inlineCallbacks
    def get_count(self, path_template, **kwargs):
        shop_name = yield self.get_shop_name(**kwargs)
        count = 0
        if shop_name:
            result = yield self.request(path=path_template % shop_name, **kwargs)
            count = result.get('count', 0)

        defer.returnValue({'num': count})

    @recurring
    @enqueue_delta(days=30)
    def profile(self, **kwargs):
        "Returns this user's profile."
        def build_profile(response):
            response = response['results'][0]
            name = build_full_name(response.get('first_name'), response.get('last_name'))
            profile_link = self.profile_link(response.get('login_name'))
            return Profile(
                name=name,
                profile_picture_link=response.get('image_url_75x75'),
                profile_link=profile_link,
                bio=response.get('bio'),
                username=response.get('login_name'),
                gender=response.get('gender'),
            )

        return self.request(
           path='users/__SELF__/profile',
            **kwargs
        ).addCallback(build_profile)


@service_class
class EtsyWeb(Etsy, StreamCachedService, Web):
    """Etsy Web OAuth1 API for Lightning"""
    daemon_class = EtsyDaemon

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
            'https://etsy.com/oauth/signin?oauth_token=' +
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
                path='users/__SELF__',
                token=token,
                secret=secret,
            )

            authorization = yield Authz(
                client_name=client_name,
                service_name=self.name,
                token=token,
                user_id=resp['results'][0]['user_id'],
                secret=secret,
            ).set_token(self.datastore)
        except (ValueError, KeyError, LightningError) as exc:
            raise AuthError(exc.message)
        defer.returnValue(authorization)

    @api_method('GET')
    def most_recent_activity(self, **kwargs):
        "The most recent activity on this service's feed"
        return super(EtsyWeb, self).most_recent_activity(echo=1, **kwargs)

    @api_method('GET')
    @check_account_created_timestamp
    def account_created_timestamp(self, **kwargs):
        """Returns the time at which the user first posted to to this serivice"""

        def parse_timestamp(resp):
            data = resp['results'][0]
            t = data.get('join_tsz')

            return {
                'timestamp': t,
            }
        return self.request(
            path='users/__SELF__/profile',
            **kwargs
        ).addCallback(parse_timestamp)

    @api_method('GET')
    @defer.inlineCallbacks
    def recent_reviews(self, echo=1, **kwargs):
        "The recent reviews of this user"
        reviews = yield self.get_feed(
            num=5,
            echo=echo,
            show_private=kwargs['arguments'].get('show_private', 0),
            stream_type='reviews',
            **kwargs
        )
        defer.returnValue({"data": reviews})

EtsyWeb.api_method(
    'num_favorites',
    key_name='num',
    present='Number of favorites.',
    interval='Number of favorites over time.',
)

EtsyWeb.api_method(
    'num_active_listings',
    key_name='num',
    present='Number of active listings.',
    interval='Number of active listings over time.',
)

EtsyWeb.api_method(
    'num_sales',
    key_name='num',
    present='Number of sales.',
    interval='Number of sales over time.',
)

EtsyWeb.api_method(
    'num_feedback',
    key_name='num',
    present='Number of feedback.',
    interval='Number of feedback over time.',
)

EtsyWeb.api_method(
    'num_feedback_written',
    key_name='num',
    present='Number of feedback written.',
    interval='Number of feedback written over time.',
)

EtsyWeb.api_method(
    'positive_feedback_percentage',
    key_name='num',
    present='Pecentage of positive feedback.',
    interval='Percentage of positive feedback over time.',
)

EtsyWeb.api_method(
    'profile',
    present="Returns this user's profile.",
)

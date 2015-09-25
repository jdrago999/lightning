"Generic docstring A"
from __future__ import absolute_import

from lightning.service.base import (
    ServiceOAuth1, Daemon, Web, api_method, service_class, Contact, Education,
    Profile, Work
)

from lightning.error import AuthError, LightningError
from lightning.model.authorization import Authz
from lightning.model.stream_event import StreamEvent
from lightning.service.response_filter import (
    ResponseFilter, ResponseFilterType, response_filter
)
from lightning.utils import build_full_name

from twisted.internet import defer

import faker
import logging
import phonenumbers
import random
import re
from time import time
import urllib
import urlparse


class LinkedIn(ServiceOAuth1):
    """LinkedIn OAuth1.0a API for Lightning.
    Lightning's implementation of LinkedIn's REST API.
    API:
        https://developer.linkedin.com/rest
    """
    name = 'linkedin'

    def __init__(self, *args, **kwargs):
        """Create a new LinkedIn service object.
        Attributes:
            app_info: dict, API keys and secrets per environment.
            domain: string, Domain the service hits.
            base_url: string, URL of domain with correct protocol.
            auth_url: string, URL used to build authorization URL.
            access_token_url: string, URL used to obtain an access_token.
            endpoint_url: string, URL used to call service methods.
        """
        super(LinkedIn, self).__init__(*args, **kwargs)

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

        self.domain = 'api.linkedin.com'
        self.base_url = 'https://' + self.domain
        self.auth_url = self.base_url + '/uas/oauth/requestToken'
        self.access_token_url = self.base_url + '/uas/oauth/accessToken'
        self.revoke_url = self.base_url + '/uas/oauth/invalidateToken'
        self.endpoint_url = self.base_url + '/v1'

        self.oauth_signature_method = 'HMAC-SHA1'
        self.response_filter = LinkedInLoadTestFilter()

    default_permissions = 'r_basicprofile'
    permissions = {
        'testing': {
            'scope': default_permissions,
        },
        'testing2': {
            'scope': default_permissions,
        },
        'lg-console': {
            'scope': default_permissions,
        },
    }

    def request_with_paging(self, path, callback, **kwargs):
        """Page through all the results for the givien endpoint and call `callback` on each. Flickr
        uses limit and offset for page parameters, so we need to inform the parent method
        of these fields.

        Args:
            * path - the relative path of the endpoint to retrieve
            * callback - method to be called with each page of results
            * kwargs - other arguments to pass along to the request method

        Yields: A deferred request which when completed will have called each page of results with `callback`"""

        limit = 50
        return super(LinkedIn, self).request_with_paging(path, callback,
            offset_increase=limit,
            starting_offset=0,
            limit_field='count',
            offset_field='start',
            limit=limit,
            data_name="values",
            **kwargs
        )



class LinkedInDaemon(LinkedIn, Daemon):
    """LinkedIn Daemon OAuth1 API for Lightning"""
    pass


@service_class
class LinkedInWeb(LinkedIn, Web):
    """LinkedIn Web OAuth1 API for Lightning"""
    daemon_class = LinkedInDaemon

    @defer.inlineCallbacks
    def start_authorization(self, client_name, args):
        """Start the authorization process.
        Get authorization URL.
        Args:
            oauth_callback: string, URL to redirect to after request.
        """
        try:
            self.ensure_arguments(['redirect_uri'], args)

            resp = yield self.request(
                full_url=self.auth_url,
                args={
                    'oauth_callback': args['redirect_uri'],
                    'scope': self.permissions[client_name]['scope'],
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
        except (ValueError, LightningError) as exc:
            raise AuthError(exc.message)

        defer.returnValue(
            self.base_url + '/uas/oauth/authorize?oauth_token=' + request_token
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
                    'scope': self.permissions[client_name]['scope'],
                }),
                token=inflight_authz.request_token,
                secret=inflight_authz.secret,
                verifier=args['oauth_verifier'],
                no_parse=True,
            )

            response = urlparse.parse_qs(resp.body, strict_parsing=True)

            token = response['oauth_token'][0]
            secret = response['oauth_token_secret'][0]
            resp = yield self.request(
                path='people/~:(id)',
                token=token,
                secret=secret,
            )

            authorization = yield Authz(
                client_name=client_name,
                service_name=self.name,
                token=token,
                user_id=resp['id'],
                secret=secret,
            ).set_token(self.datastore)
        except (ValueError, LightningError) as exc:
            raise AuthError(exc.message)
        defer.returnValue(authorization)

    def revoke_authorization(self, authorization):
        """Revoke oauth_token.
        Invalidates user's oauth_token with service and removes from datastore.
        """
        # TODO(ray): Fix LinkedIn revoke auth
        return defer.succeed(True)

    def service_revoke_authorization(self, client_name, args):
        "Asynchronously revoke authoriation. This is unimplemented."
        raise NotImplementedError

    @api_method('GET')
    def profile(self, **kwargs):
        "Returns this user's profile."
        def update_large_profile_picture_link(profile):
            # Image from the normal profile endpoint can be small and blurry,
            # so try to fetch the original image and use that. Default to
            # the normal image if not found.
            def build_profile_picture_link(data, profile):
                values = data.get('values', [])
                if values:
                    profile['profile_picture_link'] = values[0]
                return profile
            return self.request(
                path='people/~/picture-urls::(original)',
                **kwargs
            ).addCallback(build_profile_picture_link, profile)
        def build_profile(data):
            name = build_full_name(data.get('firstName'), data.get('lastName'))

            # LinkedIn doesn't provide a username. This only will be available
            # if the user has made their profile public.
            username = None
            match = re.match(r'.*/in/(.*)$', data.get('publicProfileUrl'))
            if match:
                username = match.group(1)
            return Profile(
                bio=data.get('summary'),
                first_name=data.get('firstName'),
                headline=data.get('headline'),
                last_name=data.get('lastName'),
                maiden_name=data.get('maidenName'),
                name=name,
                profile_link=data.get('publicProfileUrl'),
                profile_picture_link=data.get('pictureUrl'),
                username=username,
            )

        args = ','.join([
            'first-name',
            'headline',
            'last-name',
            'maiden-name',
            'picture-url',
            'public-profile-url',
            'summary',
        ])
        return self.request(
            path='people/~:(%s)' % args,
            **kwargs
        ).addCallback(build_profile).addCallback(update_large_profile_picture_link)

    @classmethod
    def get_date_from_position(cls, position):
        """Parse start and end dates for a LinkedIn position into Month and Year tuples.
        """
        if position.get('startDate', False):
            start_date_month = position['startDate'].get('month')
            start_date_year = position['startDate'].get('year')
        else:
            start_date_month = None
            start_date_year = None

        if position.get('endDate', False):
            end_date_month = position['endDate'].get('month')
            end_date_year = position['endDate'].get('year')
        else:
            end_date_month = None
            end_date_year = None
        return (start_date_month, start_date_year, end_date_month, end_date_year)


    @api_method('GET')
    def work(self, **kwargs):
        "Returns this user's work information"
        def build_work(person):
            positions = person.get('positions', []).get('values', [])
            parsed_positions = []
            for p in positions:
                (start_date_month, start_date_year, end_date_month, end_date_year) = self.get_date_from_position(p)
                w = Work(
                    end_date_month=end_date_month,
                    end_date_year=end_date_year,
                    is_current=p.get('isCurrent'),
                    organization_name=p.get('company', {}).get('name'),
                    start_date_month=start_date_month,
                    start_date_year=start_date_year,
                    title=p.get('title'),
                    work_id=p.get('id'),
                )
                parsed_positions.append(w)
            return {'data': parsed_positions}

        return self.request(
            path='people/~:(positions)',
            **kwargs
        ).addCallback(build_work)

    @api_method('GET')
    def contact(self, **kwargs):
        "Returns this user's contact information"
        def build_contact(person):
            location = person.get('location', {})
            region = location.get('name')
            country_code = location.get('country', {}).get('code')
            phone_numbers = []
            try:
                for p in person.get('phoneNumbers', {}).get('values', []):
                    pn = phonenumbers.parse(p['phoneNumber'], "US")
                    number = phonenumbers.format_number(pn, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
                    # We only want the digits from US numbers
                    if number[:3] == "+1 ":
                        number = number.replace("+1 ", "")
                        number = number.replace("-", "")
                        phone_numbers.append({
                            'phone_number': number,
                        })
            except phonenumbers.phonenumberutil.NumberParseException as exc:
                logging.info(exc.message)

            if not phone_numbers:
                phone_numbers = None

            return Contact(
                region=region,
                country_code=country_code,
                phone_numbers=phone_numbers,
            )

        return self.request(
            path='people/~:(location,phone-numbers)',
            **kwargs
        ).addCallback(build_contact)

    def most_recent_activity(self, **kwargs):
        pass

    def get_feed(self, **kwargs):
        []

class LinkedInLoadTestFilter(ResponseFilter):
    __metaclass__ = ResponseFilterType

    def __init__(self):
        super(LinkedInLoadTestFilter, self).__init__()

    @response_filter(path='uas/oauth/requestToken', parse_json=False)
    def filter_request_token(self, response, **kwargs):
        """Filter the oauth_token and oauth_token_secret of the requestToken step"""
        result = urlparse.parse_qs(response.body)
        result['oauth_token'] = self.fake_hex_string(32)
        result['oauth_token_secret'] = self.fake_hex_string(32)
        response.body = urllib.urlencode(result)
        return response

    @response_filter(path='uas/oauth/accessToken', parse_json=False)
    def filter_access_token(self, response, **kwargs):
        """Filter the oauth_token and oauth_token_secret of the accessToken step.
        Note: you will need to pass in a fake `oauth_verifier` to the final oauth step.
        """
        result = urlparse.parse_qs(response.body)
        result['oauth_token'] = self.fake_hex_string(32)
        result['oauth_token_secret'] = self.fake_hex_string(32)
        response.body = urllib.urlencode(result)
        return response

    @response_filter(path='v1/people/~:(first-name,headline,last-name,maiden-name,picture-url,public-profile-url,summary)')
    def filter_profile(self, response, **kwargs):
        "Replace things in the profile response with fake stuff"

        username = random.choice([faker.internet.user_name(), None])
        if username:
            fake_profile_url = 'http://linkedin.com/in/%s' % username
        else:
            fake_profile_url = 'http://%s/%s' % (faker.internet.domain_name(), self.fake_hex_string(10))
        change = {
            'firstName': faker.name.first_name(),
            'headline': self.fake_words(random.randint(5, 20)),
            'lastName': faker.name.last_name(),
            'maidenName': faker.name.last_name(),
            'pictureUrl': None,
            'publicProfileUrl': fake_profile_url,
            'summary': self.fake_words(random.randint(5, 20)),
        }
        response.update(change)
        return response

    @response_filter(path='v1/people/~:(id)')
    def filter_id(self, response, **kwargs):
        response.update({'id': self.fake_hex_string(20)})
        return response

    def fake_person(self):
        return {
            'id': self.fake_hex_string(5),
            'name': random.choice([faker.name.name(), None]),
            'firstName': random.choice([faker.name.first_name(), None]),
            'lastName': random.choice([faker.name.last_name(), None]),
            'pictureUrl': None,
            'siteStandardProfileRequest': {
                'url': 'http://%s/%s' % (faker.internet.domain_name(), self.fake_hex_string(10))
            }
        }

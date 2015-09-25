"Generic docstring A"
from __future__ import absolute_import

from .base import ServiceOAuthAUTHVER, Daemon, Web,\
    api_method, service_class, recurring, daemon_class, profile_method

from ..authorization import Authorization
from ..command import OKCommand, RetryCommand, EnqueueCommand, \
    InvalidateTokenCommand, CommandContext, CommandContextException
from ..error import RequestError, ApiMethodError

from twisted.internet import defer

import json

class SERVICE(ServiceOAuthAUTHVER):
    "CLASS DOCSTRING"
    name = 'SERVICENAME'
    def __init__(self, *args, **kwargs):
        "DOCSTRING"
        super(SERVICE, self).__init__(*args, **kwargs)

        self.app_info = {
            'local': {
                'app_id': ID,
                'app_secret': SECRET,
            },
            'beta': {
                'app_id': ID,
                'app_secret': SECRET,
            },
            'preprod': {
                'app_id': ID,
                'app_secret': SECRET,
            },
            'prod': {
                'app_id': ID,
                'app_secret': SECRET,
            },
        }
        self.app_info['dev'] = self.app_info['local']

        self.domain = DOMAIN
        self.base_url = 'https://' + self.domain
        self.auth_url = self.base_url + AUTH_URL
        self.access_token_url = self.base_url + ACCESS_URL
        self.endpoint_url = self.base_url

    def handle_response(self, status, url, headers, body, context, **kwargs):
        "Handle response"
        raise NotImplementedError

    def request_with_paging(self, path, callback, **kwargs):
        raise NotImplementedError

    def get_feed_url(self, **kwargs):
        'The feed URL'
        raise NotImplementedError
    def get_feed_limit(self, limit):
        'Return the limit in the right format'
        raise NotImplementedError
    def get_feed_timestamp(self, **kwargs):
        'Return the timestamp in the right format'
        raise NotImplementedError
    def parse_post(self, post, **kwargs):
        "Parse a feed post"
        raise NotImplementedError

        return dict(
            metadata=dict(
                post_id=post['id'],
                timestamp=timegm(
                    iso8601.parse_date(post['created_time']).timetuple()
                ),
            ),
            author=dict(
                user_id=user_id,
                user_name=post.get('from', {}).get('name', ''),
                picture_url=picture_url,
                profile_url=profile_url,
            ),
            activity=activity,
        )

@daemon_class
class SERVICEDaemon(SERVICE, Daemon):
    "SERVICE Daemon"
    def serialize_value(self, method, value):
        'Override of serialize_value'
        return value['num']

    @recurring
    def num_friends(self, **kwargs):
        "User's number of friends."
        raise NotImplementedError

@service_class
class SERVICEWeb(SERVICE, Web):
    "SERVICE Web"
    daemon_class = SERVICEDaemon

    @api_method
    def profile(self, **kwargs):
        "Returns this user's profile."
        raise NotImplementedError

        def build_profile(data):
            user_id = kwargs['authorization'].user_id()
            return profile_method(
                email=data.get('email', ''),
                gender=data.get('gender', ''),
                profile_link=data.get('link', ''),
                profile_picture_link=self.picture_url(user_id=user_id, **kwargs),
                name=data.get('name', ''),
                username=data.get('username', ''),
                bio=data.get('bio', ''),
            )

        return self.request(
            path='me',
            args={'fields': 'name,link,gender,email,bio,username'},
            **kwargs
        ).addCallback(build_profile)

SERVICEWeb.api_method(
    'num_friends', key_name='num',
    present="Returns this user's number of friends.",
    interval="Returns this user's number of friends over time.",
)

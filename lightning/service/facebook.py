"Generic docstring A"
from __future__ import absolute_import

from lightning.service.base import (
    ServiceOAuth2, Daemon, Web, OAuth2CSRFChecker, service_class, recurring,
    daemon_class, enqueue_delta, api_method,
    Birth, Contact, Education, Profile, Work
)


from lightning.error import Error, AuthError, LightningError, InsufficientPermissionsError
from lightning.model.authorization import Authz
from lightning.model.limit import Limit
from lightning.model.stream_event import StreamEvent, StreamType
from lightning.utils import get_state_abbreviation, get_youtube_video_id

from twisted.internet import defer

import base64
from calendar import timegm
import hashlib
import hmac
import iso8601
import json
import logging
import pprint
import random
import re
import requests
import time
import urllib
import urlparse

class Facebook(ServiceOAuth2):
    """Facebook OAuth2.0 API for Lightning
    Lightning's implementation of the Facebook REST API.
    API:
        http://developers.facebook.com/docs/reference/api/
    """
    name = 'facebook'

    def __init__(self, *args, **kwargs):
        """Create a new Facebook service object.
        Attributes:
            app_info: dict, API keys and secrets per environment.
            domain: string, Domain the service hits.
            base_url: string, URL of domain with correct protocol.
            auth_url: string, URL used to build authorization URL.
            access_token_url: string, URL used to obtain an access_token.
            endpoint_url: string, URL used to call service methods.
        """
        super(Facebook, self).__init__(*args, **kwargs)

        self.app_info = {
            'local': {
                'app_id': 'fake',
                'app_secret': 'fake',
                'app_access_token': 'fake',
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

        self.domain = 'graph.facebook.com'
        self.base_url = 'https://' + self.domain + '/v2.3'
        self.auth_url = 'https://www.facebook.com/v2.3/dialog/oauth'
        self.access_token_url = self.base_url + '/oauth/access_token'
        self.endpoint_url = self.base_url

        permissions = [
            'email',
            'user_friends',
            # XXX - The following permisisons are not needed by iD currently and require
            # new approval by FB, so they are turned off for now

            # 'user_about_me',
            # 'user_education_history',
            # 'user_work_history',
            # 'user_location',
            # 'user_birthday',
            # 'user_website',
            # 'read_requests',
            # 'read_stream',
        ]
        self.permissions = {
            'testing': {
                'scope': ','.join(permissions),
            },
            'testing2': {
                'scope': ','.join(permissions),
            },
            'lg-console': {
                'scope': ','.join(permissions),
            },
        }

    @Limit.max_simultaneous_calls(10)
    def actually_request(self, *args, **kwargs):
        return super(Facebook, self).actually_request(*args, **kwargs)

    def parse_error(self, status, url, headers, body, **kwargs):
        """Parse errors from service"""
        # Reference: https://github.com/phwd/fbec
        body_errors = {
            4: Error.RATE_LIMITED,
            190: Error.INVALID_TOKEN,
            191: Error.INVALID_REDIRECT,
            200: Error.INSUFFICIENT_PERMISSIONS,
            460: Error.INVALID_TOKEN,
            463: Error.INVALID_TOKEN,
            467: Error.INVALID_TOKEN,
        }
        msg = 'Unknown response'
        retry_at = int(time.time() + (60*60))

        status_msg = None
        # Error message from HTTP status
        if status in self.status_errors:
            status_msg = self.status_errors[status]

        # Error message from body
        try:
            content = json.loads(body)
            body_error = content.get('error', {}).get('code')
            body_msg = body_errors.get(body_error)
            if status_msg:
                msg = status_msg
            elif body_msg:
                msg = body_msg
            else:
                msg = content.get('error', {}).get('message', msg)
        except (TypeError, ValueError):
            pass
        self.raise_error(msg, retry_at)

    def profile_picture_link(self, **kwargs):
        "Returns a URL to this user's profile picture."
        return '%s/%s/picture?width=500' % (self.endpoint_url, kwargs['user_id'])

    def profile_link(self, **kwargs):
        "Returns a URL to this user's profile."
        return 'https://www.facebook.com/%s' % kwargs['user_id']

    def request_with_paging(self, path, callback, **kwargs):
        """
        This returns a Deferred that knows how to page through results.

        Facebook provides two different methods for doing request - FQL and the
        Graph API. The Graph API uses the "standard" method of pagination, and so
        defers to the super() implementation with Facebook-specific values.

        FQL is very much like MySQL and provides a LIMIT <offset, count>.
        """

        lim = {'offset': 0, 'count': 100}
        if path == 'fql':
            stopback = kwargs.get('stopback', lambda: False)
            if kwargs.get('args'):
                args = kwargs.get('args', {})
                del kwargs['args']
            else:
                args = {}
            query = args.get('q', "")

            def collect_data(resp):
                """call the callback, in a deferred safe way, and return the original reposne for the pager to
                pick up"""
                return defer.maybeDeferred(callback, resp).addCallback(lambda ign: resp)


            def pager(response):
                if not response or len(response.get('data', [])) == 0:
                    return

                if stopback():
                    return

                lim['offset'] += lim['count']

                args['q'] = query + " LIMIT %d, %d" % (lim['offset'], lim['count'])
                return self.request(path=path, args=args, **kwargs).addCallback(collect_data).addCallback(pager)

            args['q'] = query + " LIMIT %d, %d" % (lim['offset'], lim['count'])
            return self.request(path=path, args=args, **kwargs).addCallback(collect_data).addCallback(pager)
        else:
            if kwargs.get('forward', False):
                direction = 'previous'
            else:
                direction = 'next'

            return super(Facebook, self).request_with_paging(
                path, callback,
                direction=direction, paging='paging', data_name='data',
                **kwargs
            )

    ############################################
    # Below is the list of functions required to support reading the feed

    def get_feed_url(self, **kwargs):
        'The feed URL'
        return 'me/feed'

    def get_feed_limit(self, limit):
        'Return the limit in the right format'
        return {'limit': limit}

    def get_feed_timestamp(self, **kwargs):
        'Return the timestamp in the right format'
        timestamp = kwargs.get('timestamp', int(time.time()))
        if kwargs.get('forward', False):
            return {'since': timestamp}
        else:
            return {'until': timestamp}

    def should_include_post(self, post, **kwargs):
        """Should the stream include this post?
        Determine whether a post belongs to the requested stream_type and
        return a boolean indicating whether it should be included or not.
        """
        stream_type = kwargs['stream_type']
        if stream_type:
            if stream_type == 'photos_uploaded':
                activity_type = post.get('activity', {}).get('type')
                if activity_type == 'photo' or activity_type == 'video':
                    return True
            return False
        else:
            return True

    @defer.inlineCallbacks
    def parse_post(self, post, **kwargs):
        "Parse a feed post"

        user_id = post.get('from', {}).get('id', '')
        author_name = post.get('from', {}).get('name')
        profile_picture_link = ''
        profile_link = ''
        if user_id:
            profile_picture_link = self.profile_picture_link(user_id=user_id)
            profile_link = self.profile_link(user_id=user_id)

        activity = dict(
            story=post.get('story', post.get('message')),
        )

        if post.get('place'):
            place = {}
            place['name'] = post['place'].get('name')
            location = post['place'].get('location')
            if location:
                place['latitude'] = location.get('latitude')
                place['longitude'] = location.get('longitude')
                activity['location'] = place

        # These are any links that might exist.
        if post.get('link'):
            activity['activity_link'] = post.get('link')
            activity['name'] = post.get('name')
            activity['caption'] = post.get('caption')
            activity['description'] = post.get('description')

        # These are pictures
        if post.get('picture'):
            thumbnail_link = post['picture']
            picture_link = None

            if post['type'] == 'photo':
                try:
                    picture = yield self.request(path=str(post['object_id']), **kwargs)
                    picture_link = picture.get('images', [{}])[0].get('source')

                except:
                    # couldn't get the full size picture, let's just use the thumbnail:
                    picture_link = post.get('picture')

            else:
                # XXX: We got a thumbnail_link but not a picture_link
                # we want this as a photo so set manually.
                activity['type'] = StreamType.PHOTO
                picture_link = thumbnail_link

            activity['picture_link'] = picture_link
            activity['thumbnail_link'] = thumbnail_link

        # These are videos or Flash movies
        if post.get('type') == 'video':
            activity['video_link'] = post['source']
            video_id = get_youtube_video_id(activity['video_link'])
            if video_id:
                activity['video_id'] = video_id
                activity['type'] = StreamType.VIDEO_EMBED

        if post.get('story_tags'):
            additional_users = []
            for _, items in post['story_tags'].iteritems():
                for item in items:
                    if item.get('type', '') != 'user':
                        continue

                    if item['id'] == user_id:
                        continue

                    additional_users.append({
                        'user_id': item['id'],
                        'name': item.get('name'),
                        'profile_picture_link': self.profile_picture_link(user_id=item['id'], **kwargs),
                        'profile_link': self.profile_link(user_id=item['id'], **kwargs),
                    })
            if additional_users:
                activity['additional_users'] = additional_users
                # XXX: Set multiple friend-add event to a status type.
                if post.get('status_type') == 'approved_friend':
                    activity['type'] = StreamType.STATUS
        privacy = post.get('privacy', {}).get('value')
        if privacy == 'EVERYONE':
            is_private = 0
        else:
            # Assume everything else is private
            is_private = 1

        # If we have a post that's from the auth'd user, on another user's
        # timeline. Default to private for now, since we have no privacy data.
        for user in activity.get('additional_users', {}):
            found = activity['story'].find("%s's timeline" % user.get('user_name', ''))
            if(found != -1):
                if(user_id == kwargs['authorization'].user_id):
                    is_private = 1

        defer.returnValue( StreamEvent(
            metadata=dict(
                post_id=post['id'],
                timestamp=timegm(
                    iso8601.parse_date(post['created_time']).timetuple()
                ),
                is_private=is_private,
            ),
            author=dict(
                user_id=user_id,
                name=author_name,
                username=None,
                profile_picture_link=profile_picture_link,
                profile_link=profile_link,
            ),
            activity=activity,
        ))


    # TO HERE
    ############################################

@daemon_class
class FacebookDaemon(Facebook, Daemon):
    "Facebook Daemon OAuth2 API for Lightning"

    def serialize_value(self, method, value):
        'Override of serialize_value'
        if method in ['avg_friends_of_friends', 'profile']:
            return json.dumps(value)
        else:
            return value['num']

    def fql_request(self, query, **kwargs):
        """A helper method for the FQL requests."""
        # Per https://developers.facebook.com/blog/post/478/, the max number of
        # results returned in a FQL query is 5000. In the second-to-last paragraph,
        # the final sentence says:
        # "... it is helpful to know that the maximum number of results we will
        # fetch before running the visibility checks is 5,000."

        return self.request(
            path='fql',
            args=dict(q=query),
            with_sum='data',
            **kwargs
        )

    #@recurring
    def num_comments(self, **kwargs):
        "Number of comments on items created by this user."
        # This is how to build a closed-over variable in Python.
        num = [0]

        # Convert to request_with_paging
        query = "SELECT object_id FROM comment WHERE " \
            + "object_id IN(SELECT object_id FROM photo_tag WHERE subject=me()) LIMIT 5000"

        def add_to_num(ret):
            num[0] += ret['num']
        d1 = self.fql_request(query, **kwargs).addCallback(add_to_num)

        # This really wants to be FQL, but there's no 'posts' table!
        def summate(data):
            num[0] += sum([
                item.get('comments', {}).get('count', 0)
                for item in data
            ])
        d2 = self.request_with_paging(
            path='me/posts', args={'limit': 500}, callback=summate, **kwargs
        )

        return defer.gatherResults([d1, d2]).addCallback(lambda ign: {'num': num[0]})

    # This query does not seem to require pagination support. It will return all
    # the friends regardless of how many there are.
    def friends_query(self, user):
        return "SELECT uid2 FROM friend WHERE uid1 = %s LIMIT 5000" % user

    @recurring
    @defer.inlineCallbacks
    def num_friends(self, **kwargs):
        "User's number of friends."

        friends = yield self.request(path='me/friends', **kwargs)
        count = friends.get('summary', {}).get('total_count')

        defer.returnValue({
          'num': count
        })

    def avg_friends_of_friends(self, **kwargs):
        "The average number of friends for each of user's friends."
        def errback(err):
            logging.error('Facebook error: avg_friends_of_friends receieved %s' % err)
            return {'num': 0}

        def get_for_all_friends(response):
            return defer.gatherResults([
                (self.num_friends(user_id=datum['uid2'], **kwargs)
                    .addErrback(errback))
                for datum in response.get('data', [])
            ])

        def return_json(data):
            total = 0
            length = 0
            for datum in data:
                if datum['num']:
                    total += datum['num']
                    length += 1

            if not length:
                return {'num': 0, 'visible': 0}
            return {'num': total/length, 'visible': length}

        # fql_request() automatically adds "with_sum='data'"
        return self.request(
            path='fql',
            args=dict(q=self.friends_query('me()')),
            **kwargs
        ).addCallback(get_for_all_friends).addCallback(return_json)

    # This likely will not need pagination support as the number of open friend
    # requests is never likely to be larger than a single response.
    @recurring
    def num_friend_requests(self, **kwargs):
        "User's number of friend requests."
        return self.fql_request(
            "SELECT uid_from FROM friend_request WHERE uid_to = me() LIMIT 5000",
            **kwargs
        )

    @recurring
    def num_x_photos(self, **kwargs):
        'Collects data for num_likes_photos and num_comments_photos.'
        num = {'like': 0, 'comment': 0, 'total': 0}

        def summate(proto):
            data = proto.get('data', [])
            num['total'] += len(data)
            for item in data:
                for x in ['comment', 'like']:
                    num[x] += item.get('%s_info' % x, {}).get('%s_count' % x, 0)

        def write_values(_):
            return defer.gatherResults([
                self.write_datum(method=method, data=datum, **kwargs)
                for method, datum in {
                    'num_photos_uploaded': num['total'],
                    'num_likes_photos': num['like'],
                    'num_comments_photos': num['comment'],
                }.iteritems()
            ])

        # fql_request() automatically adds "with_sum='data'"
        return self.request_with_paging(
            path='fql',
            args=dict(q="SELECT object_id, like_info, comment_info FROM photo WHERE owner = me()"),
            callback=summate,
            **kwargs
        ).addCallback(write_values).addCallback(lambda ign: None)

    def num_photos_tagged_in(self, **kwargs):
        "Number of photos where the user is tagged in"
        total = {'num': 0}

        def summate(value):
            total['num'] += value.get('num', 0)

        return self.request_with_paging(
            path='fql',
            args=dict(q="SELECT object_id FROM photo_tag WHERE subject = me()"),
            callback=summate,
            **kwargs
        ).addCallback(lambda ign: total)

    def num_posts(self, **kwargs):
        "User's number of posts."
        num = [0]

        def count_posts(data):
            num[0] += len(data)

        def return_json(_):
            return {'num': num[0]}

        return self.request_with_paging(
            path='me/posts',
            args={'limit': 500, 'fields': 'id'},
            callback=count_posts,
            **kwargs
        ).addCallback(return_json)

    def _all_comments_query(self, time, uid):
        query = "SELECT id,fromid,time,text FROM comment WHERE "

        if time:
            query += "time >= %d AND" % time

        # Comments on my comments
        #OR object_id IN (SELECT id FROM comment WHERE owner=me())
        # Status updates directed at me?

        # Need permissions: user_questions, user_videos

        query += """
            (
            object_id IN (SELECT object_id FROM album WHERE owner='%s')
            OR object_id IN (SELECT checkin_id FROM checkin WHERE author_uid='%s')
            OR object_id IN (SELECT note_id FROM note WHERE uid='%s')
            OR object_id IN (SELECT object_id FROM photo WHERE owner='%s')
            OR object_id IN (SELECT object_id FROM photo_tag WHERE subject='%s')
            OR object_id IN (SELECT id FROM question WHERE owner='%s')
            OR object_id IN (SELECT status_id FROM status WHERE uid='%s')
            OR object_id IN (SELECT vid FROM video WHERE owner='%s')
            OR object_id IN (SELECT vid FROM video_tag WHERE subject='%s')
            )
            ORDER BY time ASC
        """ % (uid, uid, uid, uid, uid, uid, uid, uid, uid)

        return query

    # XXX This may not handle pagination properly with the subqueries
    # This handles pagination in its own way.
    @recurring
    def person_commented(self, **kwargs):
        "Retrieve data for all comments, storing the results granularly."

        def write_granular_data(data):
            if not len(data):
                raise NotImplementedError

            return defer.gatherResults([
                # id, fromid, time, text
                self.datastore.write_granular_datum(
                    method='comment',
                    item_id=datum['id'],
                    actor_id=datum['fromid'],
                    timestamp=datum['time'],
                    authorization=kwargs['authorization'],
                ) for datum in data
            ])

        def handle_results(results):
            data = results.get('data', [])
            if not len(data):
                raise NotImplementedError

            # Filter the data by what IDs we have
            return self.datastore.find_unwritten_granular_data(
                method='comment', data=data, **kwargs
            ).addCallback(
                write_granular_data
            ).addCallback(
                lambda timestamp: self._all_comments_query(
                    data[-1]['time'], kwargs['authorization'].user_id
                )
            ).addCallback(
                # fql_request() automatically adds "with_sum='data'"
                lambda query: self.request(path='fql', args=dict(q=query), **kwargs)
            ).addCallback(
                handle_results
            ).addErrback(lambda ign: None)

        self.datastore.get_last_granular_timestamp(
            method='comment', **kwargs
        ).addCallback(
            lambda timestamp: self._all_comments_query(
                timestamp, kwargs['authorization'].user_id
            )
        ).addCallback(
            # fql_request() automatically adds "with_sum='data'"
            lambda query: self.request(path='fql', args=dict(q=query), **kwargs)
        ).addCallback(
            handle_results
        ).addErrback(lambda ign: None)

    @recurring
    @enqueue_delta(days=30)
    def profile(self, path='me', **kwargs):
        "Returns this user's profile."
        def build_profile(data):
            user_id = data['id']
            return Profile(
                email=data.get('email'),
                gender=data.get('gender'),
                profile_link=data.get('link'),
                profile_picture_link=self.profile_picture_link(user_id=user_id, **kwargs),
                name=data.get('name'),
                first_name=data.get('first_name'),
                middle_name=data.get('middle_name'),
                last_name=data.get('last_name'),
                bio=data.get('bio'),
            )

        return self.request(
            path=path,
            args={'fields': 'name,first_name,middle_name,last_name,link,gender,email,bio'},
            **kwargs
        ).addCallback(build_profile)

    def generate_test_user(self, full_name, installed='true'):
        """Generate a test user account.
        Generates a FB user for testing purposes per:
        http://developers.facebook.com/docs/test_users/
        Params:
            full_name: string, Name for test user.
            installed: string, optional
        Returns:
            Test user profile.
        """
        user = requests.post(
            '%s/%s/accounts/test-users' % (
                self.base_url, self.app_info[self.environment]['app_id'],
            ),
            data=urllib.urlencode(dict(
                installed=installed,
                name=full_name,
                permissions=self.permissions['testing']['scope'],
                locale='en_US',  # This is the default
                method='POST',
                access_token=self.app_info[self.environment]['app_access_token'],
            )),
        )
        return json.loads(user.content)

    def make_friends(self, user1, user2):
        ret = requests.post(
            '%s/%s/friends/%s' % (
                self.base_url, user1['id'], user2['id']
            ),
            data=urllib.urlencode(dict(
                access_token=user1['access_token'],
            )),
        )
        if ret.content != 'true':
            ret = json.loads(ret.content)
            logging.warning('%s' % pprint.pformat(ret))
            raise NotImplementedError
        ret = requests.post(
            '%s/%s/friends/%s' % (
                self.base_url, user2['id'], user1['id']
            ),
            data=urllib.urlencode(dict(
                access_token=user2['access_token'],
            )),
        )
        if ret.content != 'true':
            ret = json.loads(ret.content)
            logging.warning('%s' % pprint.pformat(ret))
            raise NotImplementedError

    def delete_test_user(self, user):
        """Deletes our test user account.
        Params:
            uid: string, id of test user to delete.
        """
        requests.delete(
            '%s/%s' % (self.base_url, user['id']),
            data=urllib.urlencode(dict(
                access_token=self.app_info[self.environment]['app_access_token'],
            )),
        )


@service_class
class FacebookWeb(Facebook, Web, OAuth2CSRFChecker):
    "Facebook Web OAuth2 API for Lightning"
    daemon_class = FacebookDaemon

    @defer.inlineCallbacks
    def start_authorization(self, **kwargs):
        """
        Get the authorization URL.

        Args:
            redirect_uri: string, URL to redirect to after request.
        """
        try:
            self.ensure_arguments(['redirect_uri'], kwargs.get('args', {}))

            uuid = yield self.generate_state_token()

            kwargs['args']['client_id'] = self.app_info[self.environment]['app_id']
            kwargs['args']['state'] = uuid
            kwargs['args']['reponse_type'] = 'code'

        except (KeyError, LightningError) as exc:
            raise AuthError(exc.message)


        defer.returnValue(
            self.construct_authorization_url(
                base_uri=self.auth_url, **kwargs
            )
        )

    @defer.inlineCallbacks
    def finish_authorization(self, client_name, **kwargs):
        """Complete last step to get an oauth_token."""
        try:
            self.ensure_arguments(['code', 'redirect_uri', 'state'], kwargs.get('args', {}))

            yield self.check_state_token(kwargs['args']['state'])

            arguments = {
                'client_id': self.app_info[self.environment]['app_id'],
                'redirect_uri': kwargs['args']['redirect_uri'],
                'client_secret': self.app_info[self.environment]['app_secret'],
                'code': kwargs['args']['code'],
            }

            resp = yield self.actually_request(
                url=self.access_token_url,
                postdata=urllib.urlencode(arguments),
                method='POST',
            )
            # Query String on success
            response = json.loads(resp.body)
            token = response['access_token']
            user_id = yield self.fetch_user_id(token)

            if not user_id:
                raise AuthError('No user_id for %s' % token)

            authorization = yield Authz(
                client_name=client_name,
                service_name=self.name,
                token=token,
                user_id=user_id,
            ).set_token(self.datastore)
            logging.info("after authz")
        except ValueError:
            # JSON on error
            response = json.loads(resp.body)
            raise AuthError(response)
        except LightningError as exc:
            raise AuthError(exc.message)

        defer.returnValue(authorization)

    @defer.inlineCallbacks
    def fetch_user_id(self, token):
        resp = yield self.request(
            path='me',
            args={'fields': 'id'},
            token=token,
        )
        user_id = resp['id']
        defer.returnValue(user_id)

    def revoke_authorization(self, authorization):
        """Revoke oauth_token.
        Invalidates user's oauth_token with service and removes from datastore.
        """
        # TODO(ray): Implement Facebook revoke authorization.
        return defer.succeed(True)

    def service_revoke_authorization(self, client_name, args):
        """Service revoke_authorization endpoint.
        Handle calls to revoke authorization made by service
        Args:
            signed_request: string, signed_request from service.
        """
        self.ensure_arguments(['signed_request'], args)
        signed_request = args['signed_request']
        data = self._parse_signed_request(signed_request)
        user_id = data.get('user_id')
        return defer.succeed(user_id)

    def _b64_decode_url(self, str):
        """Base 64 Decode a string
        Returns:
            Base 64 decoded string.
        """
        str_padded = str + '=' * (4 - len(str) % 4)
        str_padded = str_padded.encode('ascii')
        return base64.urlsafe_b64decode(str_padded)

    def _generate_signature(self, payload):
        """Generates a signature to verify given data against service."""
        signature = hmac.new(
            self.app_info[self.environment]['app_secret'],
            msg=payload,
            digestmod=hashlib.sha256
        )
        encoded_signature = signature.digest()
        encoded_signature = base64.urlsafe_b64encode(encoded_signature)
        encoded_signature = encoded_signature.replace('=', '')
        return encoded_signature

    def _parse_signed_request(self, signed_request):
        """Parse signed_request and return its data.
        Params:
            signed_request: string, signed_request from service.
        """
        args = signed_request.split('.', 2)
        encoded_sig = args[0]
        payload = args[1]

        sig = self._b64_decode_url(encoded_sig)
        data = json.loads(self._b64_decode_url(payload))

        if data.get('algorithm').upper() != 'HMAC-SHA256':
            return None
        else:
            expected_sig = self._generate_signature(payload)
            expected_sig = self._b64_decode_url(expected_sig)

        if sig != expected_sig:
            return None

        return data

    @defer.inlineCallbacks
    def check_permissions(self, **kwargs):
        """Check token permissions.

        Checks if the token has the permissions required by the application.

        Raises:
            InsufficientPermissionsError
        """
        resp = yield self.request(
            path='me',
            args={'fields': 'permissions'},
            **kwargs
        )

        user_permissions = resp.get('permissions', {}).get('data', [])[0]
        app_permissions = self.permissions['testing2']['scope'].split(',')

        # Don't check default permissions
        for p in ['basic_info', 'installed', 'user_friends', 'export_stream']:
            if p in user_permissions:
                del user_permissions[p]

        # Raise error if all the permissions we requested aren't there.
        if not set(app_permissions) <= set(user_permissions):
            diff = ', '.join(set(app_permissions) - set(user_permissions))
            raise InsufficientPermissionsError("Missing permissions: %s" % diff)
        defer.returnValue(True)

    @classmethod
    def get_date_from_position(cls, position):
        """Parse start and end dates for a Facebook position into Month and Year tuples.
        """
        if position.get('start_date', False) and position.get('start_date') != '0000-00':
            date = position['start_date'].split('-')  # ['2013', '08', '12']
            start_date_month = int(date[1])
            start_date_year = int(date[0])
        else:
            start_date_month = None
            start_date_year = None

        if position.get('end_date', False) and position.get('end_date') != '0000-00':
            date = position['end_date'].split('-')  # ['2013', '08', '12']
            end_date_month = int(date[1])
            end_date_year = int(date[0])
        else:
            end_date_month = None
            end_date_year = None
        return (start_date_month, start_date_year, end_date_month, end_date_year)

    @classmethod
    def get_city_state(cls, response):
        """Parse the location for a Facebook response into City and State tuple.
        """
        if response.get('location'):
            location = response['location']['name'].split(', ')  # ['Redwood City', 'California']
            city = location[0]
            state = get_state_abbreviation(location[1])
        else:
            city = None
            state = None
        return (city, state)

    @api_method('GET')
    @defer.inlineCallbacks
    def education(self, **kwargs):
        "Returns this user's education information"
        person = yield self.request(
            path='me',
            args={'fields': 'education'},
            **kwargs
        )
        educations = person.get('education', [])
        if not educations:
            yield self.check_permissions(**kwargs)
        parsed_educations = []
        concentrations = []
        for p in educations:
            try:
                end_date_year = int(p.get('year', {}).get('name'))
            except:
                end_date_year = None

            for c in p.get('concentration', {}):
                if c.get('name'):
                    concentrations.append(c['name'])
            field_of_study = None
            if concentrations:
                field_of_study = ', '.join(concentrations)
            if p['type'] == 'High School':
                degree_earned = 'High School'
            else:
                degree_earned = p.get('degree', {}).get('name')
            e = Education(
                school_name=p.get('school', {}).get('name'),
                field_of_study=field_of_study,
                degree_earned=degree_earned,
                end_date_year=end_date_year,
            )
            parsed_educations.append(e)
        defer.returnValue({'data': parsed_educations})

    @api_method('GET')
    @defer.inlineCallbacks
    def work(self, **kwargs):
        """Returns this user's work information"""
        person = yield self.request(
            path='me',
            args={'fields': 'work'},
            **kwargs
        )
        positions = person.get('work', [])
        if not positions:
            yield self.check_permissions(**kwargs)
        parsed_positions = []
        for p in positions:
            (start_date_month, start_date_year, end_date_month, end_date_year) = self.get_date_from_position(p)
            (city, state) = self.get_city_state(p)
            w = Work(
                title=p.get('position', {}).get('name'),
                organization_name=p.get('employer', {}).get('name'),
                start_date_month=start_date_month,
                start_date_year=start_date_year,
                end_date_month=end_date_month,
                end_date_year=end_date_year,
                city=city,
                state=state,
            )
            parsed_positions.append(w)
        defer.returnValue({'data': parsed_positions})

    @api_method('GET')
    @defer.inlineCallbacks
    def birth(self, **kwargs):
        """Returns this user's birth information"""
        person = yield self.request(
            path='me',
            args={'fields': 'birthday'},
            **kwargs
        )
        birthday = person.get('birthday')
        if not birthday:
            yield self.check_permissions(**kwargs)
        try:
            birth_date = birthday.split('/')
            month = int(birth_date[0])
            day = int(birth_date[1])
            year = int(birth_date[2])
        except:
            month = None
            day = None
            year = None
        defer.returnValue(Birth(
            dob_month=month,
            dob_day=day,
            dob_year=year,
        ))

    @api_method('GET')
    @defer.inlineCallbacks
    def contact(self, **kwargs):
        """Returns this user's contact information"""
        person = yield self.request(
            path='me',
            args={'fields': 'location'},
            **kwargs
        )
        (city, state) = self.get_city_state(person)
        country_code = None
        if city and state:
            country_code = 'us'
        defer.returnValue(Contact(
            city=city,
            state=state,
            country_code=country_code,
        ))

    @api_method('GET')
    @defer.inlineCallbacks
    def website(self, **kwargs):
        """Returns this user's website information"""
        person = yield self.request(
            path='me',
            args={'fields': 'website'},
            **kwargs
        )

        website = person.get('website')

        defer.returnValue({
            'website': website
        })

    @api_method('GET')
    def account_created_timestamp(self, **kwargs):
        """Returns the approximate (to within a month) time at which the user first posted to this service"""
        FACEBOOK_LAUNCH_TIMESTAMP = 1072915200

        return super(FacebookWeb, self).account_created_timestamp(
            low_start=FACEBOOK_LAUNCH_TIMESTAMP,
            limit=11,
            **kwargs
        )

    @api_method('GET')
    @defer.inlineCallbacks
    def random_friend_id(self, **kwargs):
        """Returns a random friend_id from this user's friends."""
        friends = yield self.request(
            path='me/friends',
            args={'fields': 'id'},
            **kwargs
        )
        random_friend_id = None
        if friends['data']:
            friend_ids = [ f['id'] for f in friends['data'] ]
            random_friend_id = random.choice(friend_ids)
        defer.returnValue({'friend_id': random_friend_id})

    @api_method('GET')
    @defer.inlineCallbacks
    def recent_content_authored(self, echo=0, **kwargs):
        "The recent content authored by this user"

        started_paging_at = time.time()
        def stop_if_taking_too_long():
            # Only spend a couple seconds paging through results before stopping
            if (time.time() - started_paging_at) > 2:
                return True
            return False


        content_authored = yield self.get_feed(
            num=5,
            echo=echo,
            show_private=kwargs['arguments'].get('show_private', 0),
            stream_type='photos_uploaded',
            stopback=stop_if_taking_too_long,
            **kwargs
        )
        defer.returnValue({"data": content_authored})

FacebookWeb.api_method(
    'num_friend_requests', key_name='num',
    present="Returns this user's number of friend requests",
    interval="Returns this user's number of friend requests over time"
)

FacebookWeb.api_method(
    'num_friends', key_name='num',
    present="Returns this user's number of friends.",
    interval="Returns this user's number of friends over time.",
)

FacebookWeb.api_method(
    'num_photos_uploaded', key_name='num',
    present='Returns number of photos uploaded by this user.',
    interval='Returns number of photos uploaded by this user over time.',
)

FacebookWeb.api_method(
    'num_likes_photos', key_name='num',
    present='Returns number of likes for photos uploaded by this user.',
    interval='Returns number of likes for photos uploaded by this user over time.',
)

FacebookWeb.api_method(
    'num_comments_photos', key_name='num',
    present='Returns number of comments on photos uploaded by this user.',
    interval='Returns number of comments on photos uploaded by this user over time.',
)

FacebookWeb.granular_method(
    'person_commented', key_name='comment',
    docstring="Retrieve data for all comments, storing the results granularly.",
)

FacebookWeb.api_method(
    'profile',
    present="Returns this user's profile.",
)

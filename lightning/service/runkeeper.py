"Generic docstring A"
from __future__ import absolute_import

from lightning.service.base import (
    ServiceOAuth2, Web, Daemon, service_class, recurring, daemon_class,
    enqueue_delta, Profile, api_method
)


from lightning.error import Error, AuthError, LightningError
from lightning.model.authorization import Authz
from lightning.model.stream_event import StreamEvent
from lightning.utils import meters_to_human_readable, seconds_to_human_readable, meters_to_miles

from twisted.internet import defer

from datetime import datetime
import json
import time
import urllib


class RunKeeper(ServiceOAuth2):
    """RunKeeper OAuth2.0 API for Lightning.
    Lightning's implementation of the RunKeeper REST API.
    API:
        http://runkeeper.com/developer/
    """
    name = 'runkeeper'

    def __init__(self, *args, **kwargs):
        """Create a new RunKeeper service object.
        Attributes:
            app_info: dict, API keys and secrets per environment.
            domain: string, Domain the service hits.
            base_url: string, URL of domain with correct protocol.
            auth_url: string, URL used to build authorization URL.
            access_token_url: string, URL used to obtain an access_token.
            endpoint_url: string, URL used to call service methods.
        """
        super(RunKeeper, self).__init__(*args, **kwargs)
        self.app_info = {
            'local': {
                'app_id': 'fake',
                'app_secret': 'fake',
            },
            'beta': {
                'app_id': 'fake',
                'app_secret': 'fake'
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

        self.domain = 'runkeeper.com'
        self.base_url = 'https://' + self.domain
        self.auth_url = self.base_url + '/apps/authorize?'
        self.access_token_url = self.base_url + '/apps/token?'
        self.endpoint_url = 'https://api.' + self.domain
        self.status_errors.update({
            403: Error.INSUFFICIENT_PERMISSIONS,
        })

    def request(self, **kwargs):
        if kwargs.get('authorization'):
            token = kwargs['authorization'].token
        # This path can happen if we call a method from finish_authorization()
        elif kwargs.get('token'):
            token = kwargs['token']
        else:
            assert False, 'No authorzation.token provided'

        if token:
            # Only set the bearer token for RunKeeper
            if kwargs.get('headers'):
                kwargs['headers']['Authorization'] = ['Bearer %s' % token]
            else:
                kwargs['headers'] = {'Authorization': ['Bearer %s' % token]}

        url = self.full_url(**kwargs)
        return super(ServiceOAuth2, self).request(url=url, **kwargs)

    def request_with_paging(self, path, callback, **kwargs):
        "RunKeeper-specific values for request_with_paging"
        if kwargs.get('forward', False):
            direction = 'next'
        else:
            direction = 'previous'

        return super(RunKeeper, self).request_with_paging(
            path, callback,
            direction=direction, data_name='items',
            **kwargs
        )

    def profile_url(self, **kwargs):
        "Returns a URL to this user's profile."
        return 'https://runkeeper.com/%s' % kwargs['user_name']

    ############################################
    # Below is the list of functions required to support reading the feed

    def get_feed_url(self, **kwargs):
        'The feed URL'
        return 'fitnessActivities'

    def get_feed_limit(self, limit):
        'Return the limit in the right format'
        return {'pageSize': limit}

    def get_feed_timestamp(self, **kwargs):
        'Return the timestamp in the right format'
        date = datetime.fromtimestamp(kwargs.get('timestamp', int(time.time()))).strftime('%Y-%m-%d')
        if kwargs.get('forward', False):
            return {'noEarlierThan': date}
        else:
            return {'noLaterThan': date}

    @defer.inlineCallbacks
    def parse_post(self, post, **kwargs):
        "Parse a feed post"
        # Build author
        # TODO(ray): Fix bug with profile here as part of #31846
        author = yield self.profile(**kwargs)
        if not author:
            author = Profile()
        author['user_id'] = kwargs['authorization'].user_id

        # Build activity
        # Length of activity
        duration = post.get('duration', 0)
        duration = seconds_to_human_readable(duration)
        # Distance
        distance = post.get('total_distance', 0)
        distance = meters_to_human_readable(distance)
        # Build our story
        activity_type = post.get('type', 'Other')
        story = ''
        type_to_verb = {
            'Running': 'ran',
            'Walking': 'walked',
            'Cycling': 'cycled',
            'Swimming': 'swam',
            'Elliptical': 'used the elliptical',
            'Arc Trainer': 'used the arc trainer',
            'Strength Training': 'strength trained',
            'Circuit Training': 'curcuit trained',
            'Mountain Biking': 'biked',
            'Downhill Skiing': 'skied',
            'Cross-Country Skiing': 'skied',
            'XC Skiing': 'skied',
            'Snowboarding': 'snowboarded',
            'Wheelchair': 'wheeled',
            'Rowing': 'rowed',
            'Meditation': 'meditated',
            'Hiking': 'hiked',
            'Skating': 'skated',
            'Group Workout': 'worked out in a group',
            'Dance': 'danced',
            'Boxing / MMA': 'boxed',
            'Stairmaster / Stepwell': 'worked on stairs',
            'Sports': 'played sports',
            'Other': 'worked out',
        }
        verb = type_to_verb.get(activity_type, "worked on %s" % activity_type.lower())
        story = '%s %s' % (author['name'], verb)
        if distance:
            story = '%s %s' % (story, distance)
        if duration:
            story = '%s for %s' % (story, duration)
        activity = {
            'story': story,
        }
        # Metadata
        # Grab post_id from end of uri
        post_id = post.get('uri', '/0/0').split('/')[2]
        is_private = post.get('private', 0)
        # Convert time from Fri, 15 Mar 2013 16:17:26 to timestamp
        start_time = post.get('start_time', None)
        time_struct = time.strptime(start_time, '%a, %d %b %Y %H:%M:%S')
        timestamp = int(time.mktime(time_struct))

        defer.returnValue(StreamEvent(
            metadata=dict(
                post_id=post_id,
                timestamp=timestamp,
                is_private=is_private,
            ),
            author=author,
            activity=activity,
        ))

    # TO HERE
    ############################################


@daemon_class
class RunKeeperDaemon(Daemon, RunKeeper):
    "RunKeeper Daemon OAuth2 API for Lightning"

    @recurring
    def num_friends(self, **kwargs):
        """Number of friends"""
        def parse_friends(response):
            return {'num': response.get('size', 0)}
        return self.request(path='team', **kwargs).addCallback(parse_friends)

    @recurring
    def num_activities(self, **kwargs):
        """Number of activities"""
        def parse_activities(response):
            return {'num': response.get('size', 0)}
        return self.request(path='fitnessActivities', **kwargs).addCallback(parse_activities)

    @recurring
    def num_comments(self, **kwargs):
        """Number of comments"""
        # First, get a paged list of all of the user's activities (main method body)
        # Then, for each of these activities, get a list of comments (summate)
        # add the length of each comment list to `count` (add_comments_for_activity)
        count = [0]

        def construct_comment_path(activity_uri):
            parts = activity_uri.split('/')
            activity_id = parts[2]
            return 'fitnessActivities/%s/comments' % activity_id

        def add_comments_for_activity(response):
            activity_comments = response.get('comments', [])
            activity_comment_count = len(activity_comments)

            count[0] += activity_comment_count

        def summate(activities):

            return defer.gatherResults([
                (self.request(path=construct_comment_path(activity.get('uri')),
                    **kwargs).addCallback(add_comments_for_activity))
                for activity in activities
            ])

        return self.request_with_paging(
            path='fitnessActivities',
            callback=summate,
            **kwargs).addCallback(lambda _: {'num': count[0]})

    @recurring
    def values_from_activities(self, **kwargs):
        """Fetch values for  calories, duration and distance"""
        num = {
            'calories': 0,
            'duration': 0,
            'distance': 0,
        }

        def construct_activity_path(activity_uri):
            # trim off the inital slash, since our path's don't take them
            return activity_uri[1:]

        def add_stats_for_activity(response):
            num['calories'] += int(response.get('total_calories', 0))
            num['duration'] += int(response.get('duration', 0))
            num['distance'] += float(response.get('total_distance', 0))

        def summate(activities):
            return defer.gatherResults([
                (self.request(path=construct_activity_path(activity.get('uri')),
                    **kwargs).addCallback(add_stats_for_activity))
                for activity in activities
            ])

        def write_values(_):
            return defer.gatherResults([
                self.write_datum(method=method, data=datum, **kwargs)
                for method, datum in {
                    'num_calories': num['calories'],
                    'total_duration': num['duration'],
                    'total_distance': meters_to_miles(num['distance']),
                }.iteritems()
           ])

        return self.request_with_paging(
            path='fitnessActivities',
            callback=summate,
            **kwargs).addCallback(write_values).addCallback(lambda ign: None)

    @recurring
    @enqueue_delta(days=30)
    def profile(self, path='self', **kwargs):
        "Returns this user's profile."
        def build_profile(response):
            data = response or {}
            return Profile(
                name=data.get('name'),
                username=None,
                gender=data.get('gender'),
                profile_picture_link=data.get('normal_picture'),
                profile_link=data.get('profile'),
            )

        return self.request(
            path='profile', **kwargs
        ).addCallback(build_profile)


@service_class
class RunKeeperWeb(RunKeeper, Web):
    "RunKeeper Web OAuth2 API for Lightning"
    daemon_class = RunKeeperDaemon

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
        except (KeyError, LightningError) as exc:
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

            resp = yield self.request(
                path='user',
                token=response['access_token'],
            )

            authorization = yield Authz(
                client_name=client_name,
                service_name=self.name,
                token=response['access_token'],
                user_id=resp['userID'],
            ).set_token(self.datastore)

        except (KeyError, ValueError, LightningError) as exc:
            raise AuthError(exc.message)

        defer.returnValue(authorization)

    @api_method('GET')
    def account_created_timestamp(self, **kwargs):
        """Returns the approximate (to within a month) time at which the user first posted to this service"""
        RUNKEEPER_LAUNCH_TIMESTAMP = 1199145600

        return super(RunKeeperWeb, self).account_created_timestamp(
            low_start=RUNKEEPER_LAUNCH_TIMESTAMP,
            **kwargs
        )


RunKeeperWeb.api_method(
    'num_friends', key_name='num',
    present="Returns this user's number of friends.",
    interval="Returns this user's number of friends over time.",
)

RunKeeperWeb.api_method(
    'num_comments', key_name='num',
    present="Returns the number of comments on the user's activities.",
    interval="Returns the number of comments on the user's activities over time.",
)

RunKeeperWeb.api_method(
    'num_activities', key_name='num',
    present="Returns this user's number of activities.",
    interval="Returns this user's number of activities over time.",
)

RunKeeperWeb.api_method(
    'num_calories', key_name='num',
    present="Returns this user's number of calories.",
    interval="Returns this user's number of calories over time.",
)

RunKeeperWeb.api_method(
    'total_duration', key_name='num',
    present="Returns this user's total time spent on fitness activities (in seconds).",
    interval="Returns this user's total time spent on fitness activities (in seconds) over time.",
)

RunKeeperWeb.api_method(
    'total_distance', key_name='num',
    present="Returns this user's total distance traveled (in meters).",
    interval="Returns this user's total distance traveled (in meters) over time.",
)

RunKeeperWeb.api_method(
    'profile',
    present="Returns this user's profile.",
)

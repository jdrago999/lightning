"Generic docstring A"
from __future__ import absolute_import

from lightning.service.base import (
    GoogleService, Daemon, Web, MultiEndPointFeedService, ContentAuthoredService,
    service_class, recurring, daemon_class, enqueue_delta, api_method, Profile
)


from lightning.error import Error, AuthError, LightningError
from lightning.model.authorization import Authz
from lightning.model.stream_event import StreamEvent, StreamType
from lightning.utils import timestamp_to_utc
from twisted.internet import defer

import calendar
from dateutil import parser as dateparser

import json
import urllib
import bleach


class Blogger(GoogleService):

    "CLASS DOCSTRING"
    name = 'blogger'

    def __init__(self, *args, **kwargs):
        "DOCSTRING"
        super(Blogger, self).__init__(*args, **kwargs)

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
        self.base_url = 'https://' + self.domain + "/blogger/v3"
        self.auth_url = 'https://accounts.google.com/o/oauth2/auth'
        self.access_token_url = 'https://accounts.google.com/o/oauth2/token'
        self.endpoint_url = self.base_url

        self.permissions = {
            'testing': {
                'scope': 'https://www.googleapis.com/auth/blogger',
            },
            'testing': {
                'scope': 'https://www.googleapis.com/auth/blogger',
            },
            'lg-console': {
                'scope': 'https://www.googleapis.com/auth/blogger',
            },
        }

        self.status_errors.update({
            401: Error.REFRESH_TOKEN,
        })

    def get_feed(self, **kwargs):
        """returns a list of posts, in standard LG format from each of the currently
        authenticated users blogs
            Inputs:
                * kwargs - parameters to be passed along to the parents get_feed"""

        def process_blogs(blog_responese):
            """Take the blogger endpoint response, extract the blog ids and return something
            like the following which maps post enpoints to the post parsing method:

            {
                'blogs/125/posts': 'parse_post',
                'blogs/127/posts': 'parse_post',
                ...
            }

            Pass that along to This format our parent, MultiEndPointFeedService.get_feed() to parse
            each page of blog's posts  into the proper LG timeline format.

            Inputs:
                * the reponse from the blogger API blogs endpoint
            Returns
                * A an LG stream formatted list of posts from each blog
            """

            endpoint_to_parse_method = {}
            blogs = blog_responese.get('items', [])
            for blog in blogs:
                blog_id = blog.get('id')
                path = 'blogs/%s/posts' % blog_id
                endpoint_to_parse_method[path] = 'parse_post'

            return super(Blogger, self).get_feed(
                endpoint_to_parse_method=endpoint_to_parse_method, **kwargs
            )

        return self.request(path='users/self/blogs', **kwargs).addCallback(process_blogs)

    def get_feed_limit(self, limit):
        "return the field and value of the max number of results per page the Blogger API should give us.  Also make sure the limit is within the range that bloger expects"
        max_limit = 20
        if limit > max_limit:
            limit = max_limit
        return {'maxResults': limit}

    def get_feed_timestamp(self, timestamp=None, forward=False, **kwargs):
        "return the parameters we need to send to the Blogger API to get the specified date range"
        if forward:
            start_datetime = timestamp_to_utc(timestamp)
            end_datetime = ""
            time_params = {
                'startDate': start_datetime,
            }
        else:
            start_datetime = ""
            end_datetime = timestamp_to_utc(timestamp)
            time_params = {
                'endDate': end_datetime
            }

        return time_params

    def parse_post(self, post, **kwargs):
        "Take a post as returned by the bloger api and return it in standard LG stream format"
        # Build author
        remote_author = post.get("author", {})
        profile_picture_link = remote_author.get("image", {}).get("url")

        # Blogger sends us this awful, tiny image as a profile picture if the
        # user doesn't have one. Delete it.
        if profile_picture_link == 'http://img2.blogblog.com/img/b16-rounded.gif':
            profile_picture_link = None

        # Turn protocol-relative URL into SSL
        if profile_picture_link and profile_picture_link[:2] == '//':
            profile_picture_link = "https:%s" % profile_picture_link

        author = {
            "user_id": remote_author.get('id'),
            "name": remote_author.get('displayName'),
            "profile_picture_link": profile_picture_link,
            "profile_link": remote_author.get('url'),
        }

        # Build activity
        html = post.get('content', "")
        description = bleach.clean(html, tags=[], strip=True)
        description = description[:-1]  # Remove trailing newline
        title = post.get('title')

        activity = {
            'activity_link': post.get('url'),
            'description': description,
            'name': title,
            'type': StreamType.ARTICLE,
        }

        # Build metadata
        post_id = "post:%s" % post.get('id', 0)
        timestamp = calendar.timegm(dateparser.parse(post.get('published', '')).utctimetuple())
        metadata = {
            'post_id': post_id,
            'timestamp': timestamp,
            'service': self.name,
            'is_private': 0,
        }

        return StreamEvent(
            metadata=metadata,
            author=author,
            activity=activity,
        )


@daemon_class
class BloggerDaemon(Blogger, Daemon):
    "Blogger Daemon"

    @recurring
    @enqueue_delta(days=30)
    def profile(self, **kwargs):
        "Returns this user's profile."
        def build_profile(data):
            name = data.get('displayName')
            if name == 'Unknown':
                name = None

            return Profile(
                name=name,
                profile_link=data.get('url')
            )

        return self.request(
            path='users/self',
            **kwargs
        ).addCallback(build_profile)

    @recurring
    def values_from_blogs(self, **kwargs):
        """get number of blogs and posts from the blog endpoint"""

        num = {
            'posts': 0,
            'pages': 0,
            'blogs': 0,
            'comments': 0,
        }

        def save_total_comments(_):
            """other values are saved elsewhere, but now we've totaled up the commments from
            relevant posts, we just need to save those"""
            return self.write_datum(
                method='num_comments_recent_10_posts',
                data=num['comments'], **kwargs)

        def parse_comments(response):
            """take a response form Bloggers posts endpoint and pull the number of comments for
            that post.  Add that number to our running total for comments"""
            items = response.get('items', [])
            for item in items:
                replies = item.get('replies', {})
                num['comments'] += int(replies.get('totalItems', 0))

        def comment_count(items):
            "fetch a comment count from each blog and save a datapoint with the total form each"

            paths = ["blogs/%s/posts" % item.get('id') for item in items]

            # We are only interested in comments on the 10 most recent posts
            # for each blog
            args = {'maxResults': 10}

            return defer.DeferredList([
                self.request(path=path, args=args, **kwargs).addCallback(
                    parse_comments)
                for path in paths]).addCallback(save_total_comments)

        def get_counts(response):
            "save counts for blogs, pages, posts and comments"

            items = response.get('items', [])
            for item in items:
                posts = item.get('posts', {})
                pages = item.get('pages', {})
                num['blogs'] += 1
                num['posts'] += posts.get('totalItems', 0)
                num['pages'] += pages.get('totalItems', 0)

            # Add deferreds to save the results we can get directly
            results_to_gather = [self.write_datum(method=method, data=datum, **kwargs)
                                 for method, datum in {
                                 'num_posts': num['posts'],
                                 'num_blogs': num['blogs'],
                                 'num_pages': num['pages'],
                                 }.iteritems()]

            # Add deferred to save the comments, which we need to get from a different,
            # dependent endpoint

            results_to_gather.append(comment_count(items))
            return defer.gatherResults(results_to_gather)
        return self.request(path='users/self/blogs',
                            **kwargs).addCallback(get_counts).addCallback(lambda _: None)


@service_class
class BloggerWeb(Blogger, MultiEndPointFeedService, ContentAuthoredService, Web):

    "Blogger Web"
    daemon_class = BloggerDaemon

    @defer.inlineCallbacks
    def finish_authorization(self, client_name, **kwargs):
        """Complete last step to get an oauth_token.
        Args:
            code: string, code received from service after start_authorization
                step.
            redirect_uri: string, URL to hit after auth.
        """
        try:
            self.ensure_arguments(
                ['code', 'redirect_uri'], kwargs.get('args', {}))

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

            # This needs handle_response() goodness
            resp = yield self.request(
                path='users/self',
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
                args['refresh_token'] = response['refresh_token']

            authorization = yield Authz(**args).set_token(self.datastore)

        except (KeyError, ValueError, LightningError) as exc:
            raise AuthError(exc.message)
        defer.returnValue(authorization)

    @api_method('GET')
    def account_created_timestamp(self, **kwargs):
        """Returns the approximate (to within a month) time at which the user first posted to this service"""
        BLOGGER_LAUNCH_TIMESTAMP = 1072915200

        return super(BloggerWeb, self).account_created_timestamp(
            low_start=BLOGGER_LAUNCH_TIMESTAMP,
            **kwargs
        )


BloggerWeb.api_method(
    'num_posts', key_name='num',
    present="Returns this user's number of posts.",
    interval="Returns this user's number of posts over time.",
)

BloggerWeb.api_method(
    'num_pages', key_name='num',
    present="Returns the number of pages on this user's blogs.",
    interval="Returns the number of pages on this user's blogs over time.",
)

BloggerWeb.api_method(
    'num_blogs', key_name='num',
    present="Returns this user's number of blogs.",
    interval="Returns this user's number of blogs over time.",
)

BloggerWeb.api_method(
    'num_comments_recent_10_posts', key_name='num',
    present="Returns the total number of comments on the persons 10 most recent posts from each blog.",
    interval="Returns the total number of comments on the persons 10 most recent posts from each blog over time.",
)

BloggerWeb.api_method(
    'profile',
    present="Returns this user's profile.",
)

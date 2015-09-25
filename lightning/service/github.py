"Generic docstring A"
from __future__ import absolute_import

from lightning.service.base import (
    ServiceOAuth2, Web, Daemon, OAuth2CSRFChecker, StreamCachedService,
    ContentAuthoredService, service_class, recurring, daemon_class,
    enqueue_delta, Profile, api_method, check_account_created_timestamp
)

from lightning.service.response_filter import ResponseFilter, ResponseFilterType, response_filter



from lightning.error import Error, AuthError, LightningError
from lightning.model.authorization import Authz
from lightning.model.stream_event import StreamEvent
from twisted.internet import defer

import json
import urllib
import faker
from dateutil import parser as dateparser
import calendar
import random
from lightning.utils import timestamp_to_utc


class GitHub(ServiceOAuth2):
    """GitHub OAuth2.0 API for Lightning.
    Lightning's implementation of the GitHub REST API.
    API:
        http://developer.github.com/v3/
    """
    name = 'github'


    def __init__(self, *args, **kwargs):
        """Create a new GitHub service object.
        Attributes:
            app_info: dict, API keys and secrets per environment.
            domain: string, Domain the service hits.
            base_url: string, URL of domain with correct protocol.
            auth_url: string, URL used to build authorization URL.
            access_token_url: string, URL used to obtain an access_token.
            endpoint_url: string, URL used to call service methods.
        """
        super(GitHub, self).__init__(*args, **kwargs)
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

        self.domain = 'github.com'
        self.base_url = 'https://' + self.domain
        self.auth_url = self.base_url + '/login/oauth/authorize?'
        self.access_token_url = self.base_url + '/login/oauth/access_token?'
        self.endpoint_url = 'https://api.github.com'
        self.response_filter = GitHubLoadTestFilter()

        self.status_errors.update({
            422: Error.BAD_PARAMETERS,
            503: Error.INSUFFICIENT_PERMISSIONS
        })

    def request(self, **kwargs):
        kwargs['headers'] = kwargs.get('headers', {})
        kwargs['headers']['User-Agent'] = [
            "Inflection GitHub API Broker v1.0"]
        return super(GitHub, self).request(**kwargs)


    def request_with_paging(self, path, callback, data_name=None, **kwargs):
        """Page through all the results for the givien endpoint and call `callback` on each. GitHub
        uses page number and page index for page parameters, so we need to inform the parent method
        of these fields.

        Returns: A deferred request which when completed will have called each page of results with `callback`

        Inputs:
            * path - the relative path of the endpoint to retrieve
            * callback - method to be called with each page of results
            * kwargs - other arguments to pass along to the request method"""

        kwargs['data_name'] = data_name
        return super(GitHub, self).request_with_paging(path, callback,
            offset_increase=1,
            starting_offset=1,
            limit_field='per_page',
            offset_field='page',
            limit=100,
            **kwargs
        )

    ############################################
    # Below are the functions required to support reading the feed
    ############################################

    def parse_post(self, post, **kwargs):
        "Parse a feed post"

        # Build author
        profile = kwargs.get('profile', {})
        user = post.get('owner', {})
        username = user.get('login')

        # Build profile_link
        profile_link = None
        if username:
            profile_link = 'https://github.com/%s' % username

        author = {
            'user_id': user.get('id'),
            'name': profile.get('name'),
            'username': username,
            'profile_picture_link': user.get('avatar_url'),
            'profile_link': profile_link,
        }

        # Build activity
        story = '%s created a gist.' % (author['name'] or username)
        activity = {
            'activity_link': post.get('html_url'),
            'description': post.get('description'),
            'story': story,
        }

        # Build metadata
        timestamp = calendar.timegm(dateparser.parse(post.get('created_at', '')).utctimetuple())
        if post.get('public'):
            is_private = 0
        else:
            is_private = 1


        return StreamEvent(
            metadata={
                'post_id': 'gist:%s' % post.get('id', 0),
                'timestamp': timestamp,
                'service': self.name,
                'is_private': is_private,
            },
            author=author,
            activity=activity,
        )

    # TO HERE
    ############################################

@daemon_class
class GitHubDaemon(Daemon, StreamCachedService, GitHub):
    "GitHub Daemon OAuth2 API for Lightning"

    @recurring
    def iterate_over_gists(self, **kwargs):
        "fetch all the gists for the current user and save them to the stream cache"

        def set_profile(user):
            kwargs['profile'] =  Profile(
                name=user.get('name'),
                profile_picture_link=user.get('avatar_url'),
                profile_link=user.get('html_url'),
                username=user.get('login'),
            )

            return self.parse_and_save_paged_stream(
                path='gists',
                **kwargs)

        # First, we fetch the users profile, since it is used to generate the author of all the gists
        # we are fetching, then once its fetched, set_proifle actually fetches all the gists and passes
        # control to save_gists, which saves them
        return self.request(path='user', **kwargs).addCallback(set_profile)

    @recurring
    def values_from_repos(self, **kwargs):
        """Pull all of the current users repos, and total up their watchers and forks"""
        num = {
            'forks': 0,
            'watchers': 0
        }
        def add_repo_stats(repo_list):
            for repo in repo_list:
                num['forks'] += repo.get('forks', 0)
                num['watchers'] += repo.get('watchers', 0)

        def write_values(_):
            return defer.gatherResults([
                self.write_datum(method=method, data=datum, **kwargs)
                for method, datum in {
                    'num_forks': num['forks'],
                    'num_watchers': num['watchers']
                }.iteritems()
           ])


        return self.request_with_paging(path='user/repos', callback=add_repo_stats, **kwargs) \
            .addCallback(write_values).addCallback(lambda ign: None)


    @recurring
    def num_starred_gists(self, **kwargs):
        "Pull in all the starred gists for the current user and return a count"
        num = {
            'starred_gists': 0
        }

        def add_gists(gist_list):
            for gist in gist_list:
                num['starred_gists'] += 1

        return self.request_with_paging(path='gists/starred', callback=add_gists, **kwargs) \
            .addCallback(lambda _: {'num': num['starred_gists']})

    @recurring
    def values_from_user(self, **kwargs):
        """Pull project views, appreciations, comments, and profile views from the stats endpoint and save
        them to the database"""

        def write_values(user):

            # Write some counts.
            return defer.gatherResults([
                self.write_datum(method=method, data=datum, **kwargs)
                for method, datum in {
                    'num_public_repos': user['public_repos'],
                    'num_public_gists': user['public_gists'],
                    'num_following': user['following'],
                    'num_followers': user['followers'],

                }.iteritems()
            ]).addCallback(lambda ign: None)

        return self.request(path='user', **kwargs).addCallback(write_values)

    @recurring
    @enqueue_delta(days=30)
    def profile(self, **kwargs):
        "Returns this user's profile."
        def build_profile(response):
            user = response or {}

            return Profile(
                name=user.get('name'),
                profile_picture_link=user.get('avatar_url'),
                profile_link=user.get('html_url'),
                username=user.get('login'),
            )

        return self.request(path='user', **kwargs).addCallback(build_profile)


@service_class
class GitHubWeb(GitHub, StreamCachedService, ContentAuthoredService, Web, OAuth2CSRFChecker):
    "GitHub Web OAuth2 API for Lightning"
    daemon_class = GitHubDaemon

    @defer.inlineCallbacks
    def start_authorization(self, client_name, args):
        """Start the authorization process.
        Get authorization URL.
        Args:
            redirect_uri: string, URL to redirect to after request.
        """

        try:
            self.ensure_arguments(['redirect_uri'], args)
            uuid = yield self.generate_state_token()
            args['state'] = uuid
            args['client_id'] = self.app_info[self.environment]['app_id']
            args['response_type'] = 'code'
            args['scope'] = 'user,user:email,user:follow,repo,repo:status,notifications,gist'
        except (KeyError, ValueError, LightningError) as exc:
            raise AuthError(exc.message)
        defer.returnValue(self.auth_url + urllib.urlencode(args))

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

            headers = {
                'Accept': ['application/json']
            }

            resp = yield self.actually_request(
                url=self.access_token_url,
                postdata=urllib.urlencode(arguments),
                headers=headers,
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
                user_id=resp['id'],
            ).set_token(self.datastore)
        except (ValueError, KeyError, LightningError) as exc:
            raise AuthError(exc.message)
        defer.returnValue(authorization)

    @api_method('GET')
    @check_account_created_timestamp
    def account_created_timestamp(self, **kwargs):
        """Returns the time at which the user first posted to to this serivice"""

        def parse_timestamp(resp):
            created = resp.get('created_at')
            t = None
            if created:
                t = calendar.timegm(dateparser.parse(created).utctimetuple())

            return {
                'timestamp': t,
            }
        return self.request(
            path='user',
            **kwargs
        ).addCallback(parse_timestamp)

GitHubWeb.api_method(
    'num_public_repos', key_name='num',
    present="Returns the number of public repos this user has.",
    interval="Returns the number of public repos this user has over time.",
)

GitHubWeb.api_method(
    'num_public_gists', key_name='num',
    present="Returns the number of public gists  user has created.",
    interval="Returns the number of public gists  user has created over time",
)

GitHubWeb.api_method(
    'num_followers', key_name='num',
    present='Returns the number of followers this person has.',
    interval='Returns the number of followers this person has over time.',
)

GitHubWeb.api_method(
    'num_following', key_name='num',
    present="Returns the number of people this user is following.",
    interval="Returns the number of people this user is following over time.",
)

GitHubWeb.api_method(
    'num_forks', key_name='num',
    present="Returns the number of forks this user's repositories have.",
    interval="Returns the number of forks this user's repositories have over time.",
)

GitHubWeb.api_method(
    'num_watchers', key_name='num',
    present="Returns the number of watchers this user's repositories have.",
    interval="Returns the number of watchers this user's repositories have over time.",
)

GitHubWeb.api_method(
    'num_starred_gists', key_name='num',
    present="Returns the number of gists this user has starred.",
    interval="Returns the number of gists this user has starred over time.",
)

GitHubWeb.api_method(
    'profile',
    present="Returns this user's profile.",
)


class GitHubLoadTestFilter(ResponseFilter):
    __metaclass__ = ResponseFilterType

    def __init__(self):
        # We need to use the same  user_id through all calls to this filter, so that it can remain consistant

        #self.user_id = self.fake_id()

        super(GitHubLoadTestFilter, self).__init__()

    @response_filter(path='user')
    def filter_profile(self, response, **kwargs):
        "Replace things in the profile resopne with fake stuff"

        login = faker.internet.user_name()
        change = {
            'id': self.fake_id(),
            'login': login,
            'name': faker.name.name(),
            'email': faker.internet.email(),
            'html_url': 'https://github.com/%s' % login,
            'public_repos': random.randint(1, 100),
            'public_gists': random.randint(1, 100),
            'followers': random.randint(1, 100),
            'following': random.randint(1, 100),
        }
        response.update(change)
        return response

    @response_filter(path='login/oauth/access_token')
    def filter_access_token(self, response, **kwargs):
        "replace the access token github gives us with a random one"

        response['access_token'] = self.fake_hex_string(32)
        return response


    def fake_mini_user(self):
        login = faker.internet.user_name()

        return {
            'id': self.fake_id(),
            'login': login,
            'name': faker.name.name(),
            'avatar_url': 'https://github.com/images/error/octocat_happy.gif',
            'gravatar_id': self.fake_hex_string(32),
            'url': 'https://github.com/%s' % login,
        }

    def fake_public(self, force_public=False, force_private=False):
        if force_public and force_private:
            raise "can't force both public and private"
        elif force_public:
            is_public = True
        elif force_private:
            is_public = False
        else:
            is_public = bool(random.randint(0, 1))
        return is_public

    def fake_id(self):
        return random.randint(10000, 100000-1)

    def fake_repo(self, force_public=False, force_private=False):
        owner = self.fake_mini_user()
        is_public = self.fake_public(force_public=force_public, force_private=force_private)

        repo_id = self.fake_id()
        name = self.fake_words(1)
        forks = random.randint(0, 100)
        watchers = random.randint(0, 100)

        repo = {
            'id': repo_id,
            'owner': owner,
            'name': name,
            'full_name': "%s/%s" % (owner['login'], name),
            'description': self.fake_words(random.randint(5, 20)),
            'private': not is_public,
            'fork': bool(random.randint(0, 1)),
            'url': "https://api.github.com/repos/%s/%s" % (owner['login'], name),
            'html_url': "https://github.com/%s/%s" % (owner['login'], name),
            'clone_url': "https://github.com/%s/%s.git" % (owner['login'], name),
            'git_url': "git://github.com:%s/%s.git" % (owner['login'], name),
            'ssh_url': "git@github.com:%s/%s.git" % (owner['login'], name),
            'svn_url': "https://svn.github.com/%s/%s" % (owner['login'], name),
            'mirror_url': "git://git.example.com/%s/%s" % (owner['login'], name),

            'homepage': 'https://github.com',
            'language': None,
            'forks': forks,
            'forks_count': forks,
            'watchers': watchers,
            'watchers_count': watchers,
            'size': random.randint(0, 1000),
            'master_branch': 'master',
            'open_issues': 0,
            'pushed_at': timestamp_to_utc(self.fake_timestamp()),
            'created_at': timestamp_to_utc(self.fake_timestamp()),
            'updated_at': timestamp_to_utc(self.fake_timestamp()),
       }

        return repo



    def fake_gist(self, force_public=False, force_private=False):

        user = self.fake_mini_user()
        is_public = self.fake_public(force_public=force_public, force_private=force_private)

        gist_id = self.fake_id()
        gist = {
            'url': "https://api.github.com/gists/%s" % self.fake_hex_string(20),
            'id': gist_id,
            'description': self.fake_words(random.randint(5, 20)),
            'public': is_public,
            'user': user,
            'files': {},
            'comments': random.randint(0,100),
            'created_at': timestamp_to_utc(self.fake_timestamp()),
            'comments_url': "https://api.github.com/gists/%s/comments/" % self.fake_hex_string(20),
            'html_url': "https://gist.github.com/%s" % gist_id,
            'git_pull_url': "git://gist.github.com/%s.git" % gist_id,
            'git_push_url': "git@gist.github.com:%s.git" % gist_id,

       }

        return gist

    def fake_gist_list(self):
        "return a random number of gists"
        gists = self.fake_list(self.fake_gist)
        return gists

    def fake_repo_list(self):
        "return a random number of repos"
        return self.fake_list(self.fake_repo)

    def fake_list(self, fake_item_method):
        "return a list of fake items generated by `fake_item_method`"

        # have a 50/50 chance of having any results on this page at all
        if random.randint(0,1) == 0:
            num_results = 0
        else:
            num_results = random.randint(0,100)

        results = []
        for i in range(1, num_results):
            fake_item = fake_item_method(self)
            results.append(fake_item)
        return results

    @response_filter(path='gists')
    def filter_gists(self, response, **kwargs):
        "replace gists with a random number of them"
        return self.fake_gist_list()

    @response_filter(path='user/repos')
    def filter_repos(self, response, **kwargs):
        "replace repos with a random number of them"
        return self.fake_repo_list()

    @response_filter(path='gists/starred')
    def filter_starred_gists(self, response, **kwargs):
        "replace starred gists with a random number of them"
        return self.fake_gist_list()

from __future__ import absolute_import

from .base import TestService

from lightning.recorder import recorder
from lightning.service.github import GitHubWeb, GitHubDaemon

from twisted.internet import defer

from bs4 import BeautifulSoup
import requests

# This is a 'real user' for use with authorization tests
AUTHN_TEST_USER = {
    'user_id': 1234,
    'email': 'test@example.com',
    'password': 'testpassword',
    'name': 'Example User',
    'picture': 'https://exampleurl',
    'profile_link': 'https://github.com/example',
}


class TestGitHub(TestService):
    def set_authorization(self, **kwargs):
        # If we don't care about these values, then just hack something in.
        #for key in ['token', 'user_id']:
        #    if not kwargs.get(key):
        #        kwargs[key] = 'asdf'

        kwargs['service_name'] = 'github'
        return super(TestGitHub, self).set_authorization(**kwargs)


class TestGitHubWeb(TestGitHub):
    @defer.inlineCallbacks
    def setUp(self):
        yield super(TestGitHubWeb, self).setUp()
        self.service = GitHubWeb(
            datastore=self.app.db,
        )
        self.daemon = self.service.daemon_object()

        recorder.wrap(self.service.actually_request)
        recorder.wrap(self.daemon.actually_request)
        recorder.wrap(requests.request)
        # recorder.record()

    def tearDown(self):
        recorder.save()
        super(TestGitHubWeb, self).tearDown()

    def test_methods(self):
        self.assertEqual(self.service.methods(), {
            'GET': {
                'account_created_timestamp': 'Returns the time at which the user first posted to to this serivice',
                'most_recent_activity': "The most recent activity on this service's feed",
                'recent_content_authored': "The recent content authored by this user",
                'num_followers': 'Returns the number of followers this person has.',
                'num_followers_interval': 'Returns the number of followers this person has over time.',
                'num_following': 'Returns the number of people this user is following.',
                'num_following_interval': 'Returns the number of people this user is following over time.',
                'num_forks': "Returns the number of forks this user's repositories have.",
                'num_forks_interval': "Returns the number of forks this user's repositories have over time.",
                'num_public_gists': 'Returns the number of public gists  user has created.',
                'num_public_gists_interval': 'Returns the number of public gists  user has created over time',
                'num_public_repos': 'Returns the number of public repos this user has.',
                'num_public_repos_interval': 'Returns the number of public repos this user has over time.',
                'num_starred_gists': 'Returns the number of gists this user has starred.',
                'num_starred_gists_interval': 'Returns the number of gists this user has starred over time.',
                'num_watchers': "Returns the number of watchers this user's repositories have.",
                'num_watchers_interval': "Returns the number of watchers this user's repositories have over time.",
                'profile': "Returns this user's profile."
            },
            'POST': {}
        })

from __future__ import absolute_import

from .base import TestService
from twisted.internet import defer

from lightning.recorder import recorder
from lightning.service.linkedin import LinkedInWeb
from lightning.utils import get_arguments_from_redirect

from bs4 import BeautifulSoup
import requests

# This is a 'real user' for use with authorization tests
AUTHN_TEST_USER = {
    'user_id': '5AAAAAS',
    'email': 'example@example.com',
    'password': 'testpassword',
    'firstName': 'Example',
    'lastName': 'User',
    'maidenName': 'Visitor',
    'username': None,
    'headline': 'Engineering is fun',
    'profile_link': 'http://www.linkedin.com/pub/example-user/11/222/333',
    'profile_picture_link': ('http://m.c.lnkd.licdn.com/mpr/mprx/0_AAAAA_'
        'AAA_BBB-CCCC'),
}


class TestLinkedIn(TestService):
    def set_authorization(self, **kwargs):
        # If we don't care about these values, then just hack something in.
        for key in ['token', 'user_id', 'secret']:
            if not kwargs.get(key):
                kwargs[key] = 'asdf'

        kwargs['service_name'] = 'linkedin'

        return super(TestLinkedIn, self).set_authorization(**kwargs)


class TestLinkedInWeb(TestLinkedIn):
    @defer.inlineCallbacks
    def setUp(self, *args, **kwargs):
        yield super(TestLinkedInWeb, self).setUp(*args, **kwargs)
        self.service = LinkedInWeb(
            datastore=self.app.db,
        )
        self.daemon = self.service.daemon_object()

        recorder.wrap(self.service.actually_request)
        recorder.wrap(self.daemon.actually_request)
        recorder.wrap(requests.request)
        recorder.play()
        # recorder.record()

    def tearDown(self):
        recorder.save()
        super(TestLinkedInWeb, self).tearDown()

    def submit_login_form(self, uri, args):
        login_form = requests.get(
            uri,
            headers=self.headers(),
        )

        # Get the request to be the actual request we need for the CSRF bypass
        # in the post() below.
        login_form = self.follow_redirect_until_not(
            login_form,
            r'linkedin.com/',
        )

        soup = BeautifulSoup(login_form.content)
        arguments = self.extract_form_fields(soup.form)

        arguments['session_key'] = args['username']
        arguments['session_password'] = args['password']

        return requests.post(
            'https://www.linkedin.com' + soup.form['action'],
            headers=self.headers(),
            data=arguments,
            cookies=login_form.cookies,
            # We need to trap the redirect back to localhost:5000
            allow_redirects=False,
        )

    @defer.inlineCallbacks
    def test_authorize(self):
        redir_uri = 'https://lg-local.example.com/id/auth/callback/linkedin'

        # Just match a regex since we'll also get back a requestToken from
        # this since it's an OAuth 1.0 Service.

        expected_redirect = r'https://api.linkedin.com/uas/oauth/authorize\?oauth_token='

        redirect_uri = yield self.service.start_authorization(
            client_name='testing',
            args={'redirect_uri': redir_uri},
        )
        self.assertRegexpMatches(redirect_uri, expected_redirect)
        response = self.submit_login_form(
            uri=redirect_uri,
            args=dict(
                username=AUTHN_TEST_USER['email'],
                password=AUTHN_TEST_USER['password'],
            ),
        )

        self.assertNotEqual(response.status_code, 404)
        response = self.follow_redirect_until_not(response, r'linkedin.com')

        if not self.is_redirect(response.status_code):
            self.display_error(response, "Error Condition")
            return

        args = get_arguments_from_redirect(response)
        auth = yield self.service.finish_authorization(
            client_name='testing',
            args=args,
        )
        oauth_token = auth.token
        user_id = auth.user_id
        oauth_secret = auth.secret

        self.assertEqual(AUTHN_TEST_USER['user_id'], user_id)
        yield self.set_authorization(
            user_id=user_id,
            token=oauth_token,
            secret=oauth_secret
        )

        # Method tests against our actual user.
        profile = yield self.call_method('profile')

        expected_profile = dict(
            bio=None,
            email=None,
            first_name=AUTHN_TEST_USER['firstName'],
            headline=AUTHN_TEST_USER['headline'],
            last_name=AUTHN_TEST_USER['lastName'],
            maiden_name=AUTHN_TEST_USER['maidenName'],
            name='%s %s' % (AUTHN_TEST_USER['firstName'], AUTHN_TEST_USER['lastName']),
            profile_link=AUTHN_TEST_USER['profile_link'],
            profile_picture_link=AUTHN_TEST_USER['profile_picture_link'],
            username=None,
        )
        self._test_method_result_keys('profile', profile, expected_profile)

        work = yield self.call_method('work')
        expected_work = {'data': [dict(
            end_date_month=None,
            end_date_year=None,
            is_current=True,
            organization_name='Inflection',
            start_date_month=None,
            start_date_year=2011,
            title='Engineering',
            work_id=303007820
        )]}
        self._test_method_result_keys('work', work['data'][0], expected_work['data'][0])

        self._test_method_result_keys('education', education['data'][0], expected_education['data'][0])

        contact = yield self.call_method('contact')
        expected_contact = dict(
            country_code="us",
            phone_numbers=[
                {'phone_number': u'5615551234'}
            ],
            region="San Francisco Bay Area",
        )
        self._test_method_result_keys('contact', contact, expected_contact)

    def test_methods(self):
        self.assertEqual(self.service.methods(), {
            'GET': {
                'profile': "Returns this user's profile.",
                'work': "Returns this user's work information",
                'contact': "Returns this user's contact information",
            },
            'POST': {}
        })

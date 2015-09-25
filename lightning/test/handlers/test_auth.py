from __future__ import absolute_import

from .base import TestHandler
from lightning.error import error_format
from twisted.internet import defer


class TestAuthHandler(TestHandler):
    def test_get_no_service(self):
        return self.get_and_verify(
            path='/auth',
            response_code=400,
            result=error_format("Missing argument 'service'"),
        )

    def test_get_bad_service(self):
        return self.get_and_verify(
            path='/auth?service=foo&redirect_uri=asdf',
            response_code=404,
            result=error_format("Service 'foo' unknown"),
        )

    def test_post_no_service(self):
        return self.post_and_verify(
            path='/auth',
            response_code=400,
            result=error_format("Missing argument 'service'"),
        )

    def test_post_bad_service(self):
        return self.post_and_verify(
            path='/auth?service=foo&redirect_uri=asdf',
            response_code=404,
            result=error_format("Service 'foo' unknown"),
        )

    def test_start_authorize_failure(self):
        return self.get_and_verify(
            path='/auth',
            args=dict(
                service='loopback',
            ),
            response_code=400,
            result=error_format("Missing arguments: 'redirect_uri', 'username'", code=400),
        )

    def test_finish_authorize_failure(self):
        return self.post_and_verify(
            path='/auth',
            args=dict(
                service='loopback',
                redirect_uri='asdf',
            ),
            response_code=400,
            result=error_format("Missing arguments: 'username'", code=400),
        )

    @defer.inlineCallbacks
    def test_authorize_loopback(self):
        self.skip_me("Skipped until null uuid and loopback issue is resolved")
        user_id = 'joe'
        yield self.assertNoAuthorization(user_id=user_id)

        # This can be anything, but it needs to be a URI of some sort.
        redir_uri = 'https://localhost/id/authn/loopback'
        response = yield self.get_and_verify(
            path='/auth',
            args=dict(
                service='loopback',
                redirect_uri=redir_uri,
                username=user_id,
            ),
            response_code=200,
        )
        result = response.body
        self.assertURIEqual(
            result['redirect'],
            redir_uri + '?username=' + user_id + '&redirect_uri=' + redir_uri,
        )
        response = yield self.post_and_verify(
            path='/auth',
            args=dict(
                service='loopback',
                redirect_uri=redir_uri,
                username=user_id,
            ),
            response_code=201,
            response_location='/auth/.{32}',
        )
        result = response.body
        self.assertRegexpMatches(result['guid'], r'.{32}')
        joe_guid = result['guid']

        # This confirms that when we finish an authorization, we do an initial
        # enqueueing of the daemon.
        # HOW DO I VERIFY THERE'S AN ENQUEUED JOB?

        yield self.assertHasAuthorization(user_id=user_id)
        response = yield self.post_and_verify(
            path='/auth',
            args=dict(
                service='loopback',
                redirect_uri=redir_uri,
                username=user_id,
            ),
            response_code=201,
            response_location='/auth/.{32}',
        )
        self.assertEqual(response.body['guid'], joe_guid)

        other_user_id = 'jane'
        yield self.assertNoAuthorization(user_id=other_user_id)

        response = yield self.post_and_verify(
            path='/auth',
            args=dict(
                service='loopback',
                redirect_uri=redir_uri,
                username=other_user_id,
            ),
            response_code=201,
            response_location='/auth/.{32}',
        )
        result = response.body
        self.assertRegexpMatches(result['guid'], r'.{32}')
        jane_guid = result['guid']

        yield self.assertHasAuthorization(user_id=other_user_id)

        self.assertNotEqual(joe_guid, jane_guid)

        response = yield self.post_and_verify(
            path='/auth',
            args=dict(
                service='loopback',
                redirect_uri=redir_uri,
                username=other_user_id,
            ),
            response_code=201,
            response_location='/auth/.{32}',
        )
        self.assertEqual(response.body['guid'], jane_guid)

        yield self.delete_and_verify(
            path='/auth/' + joe_guid,
            response_code=200,
            result={'success': "Revocation successful"},
        )

        yield self.assertNoAuthorization(user_id=user_id)
        yield self.assertHasAuthorization(user_id=other_user_id)

    def test_put(self):
        return self.verify_not_supported(path='/auth', method='PUT')

    def test_delete(self):
        return self.verify_not_supported(path='/auth', method='DELETE')


class TestAuthOneHandler(TestHandler):
    @defer.inlineCallbacks
    def test_get_authz_info(self):
        yield self.set_authorization(
            client_name='testing', service_name='loopback',
            user_id='1234', token='some token',
        )

        yield self.get_and_verify(
            path='/auth/' + self.uuid,
            response_code=200,
            result={
                'service_name': 'loopback',
                'user_id': '1234',
                'guid': self.uuid,
                'account_created_timestamp': None,
            },
        )

    def test_get_bad_guid(self):
        return self.get_and_verify(
            path='/auth/no_guid_here',
            response_code=404,
        )

    def test_post_all(self):
        return self.post_and_verify(
            path='/auth/loopback',
            response_code=400,
            result=error_format("Missing argument 'signed_request'"),
        )

    def test_delete_not_found(self):
        # Confirm that attempting to delete
        return self.delete_and_verify(
            path='/auth/not_found',
            response_code=404,
            result=error_format("guid 'not_found' not found"),
        )

    def test_put_all(self):
        return self.verify_not_supported(path='/auth/1234', method='PUT')

#class TestAuthActivateHandler(TestHandler):
#    def test_get_bad_guid(self):
#        return self.get_and_verify(
#            path='/auth/no_guid_here/actviate',
#            response_code=404,
#        )

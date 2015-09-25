"""
This is where all the error classes for Lightning are defined.
"""

from __future__ import absolute_import
from lightning.utils import enum
import logging
from pyodbc import Error as SQLError

# Define Service Errors
Error = enum(
    BAD_PARAMETERS='Bad Parameters',
    DUPLICATE_POST='Duplicate post',
    INSUFFICIENT_PERMISSIONS='Insufficient permissions granted',
    INVALID_REDIRECT='Invalid redirect_uri',
    INVALID_TOKEN='Invalid access_token',
    NOT_FOUND='Not found',
    OVER_CAPACITY='Service over capacity',
    RATE_LIMITED='Rate limited',
    REFRESH_TOKEN='Refreshed access_token',
    UNKNOWN_RESPONSE='Unknown response',
)


def error_format(message, **kwargs):
    """Format an error response for the client"""
    kwargs['message'] = message or "Unknown error"
    for x in kwargs.keys():
        if not kwargs[x]:
            del kwargs[x]
    return {'error': kwargs}


class LightningError(Exception):
    """Base class for all Lightning errors"""
    def __init__(self, message, **kwargs):
        super(LightningError, self).__init__(message)
        # Response codes according to Errors.tracwiki
        error_codes = {
            Error.BAD_PARAMETERS: 400,
            Error.DUPLICATE_POST: 400,
            Error.INSUFFICIENT_PERMISSIONS: 403,
            Error.INVALID_REDIRECT: 406,
            Error.INVALID_TOKEN: 401,
            Error.NOT_FOUND: 404,
            Error.OVER_CAPACITY: 502,
            Error.RATE_LIMITED: 503,
            Error.REFRESH_TOKEN: 408,
            Error.UNKNOWN_RESPONSE: 502,
        }
        # Default to 502
        if isinstance(message, str):
            self.code = error_codes.get(message, 502)
        else:
            self.code = 502
        self.retry_at = kwargs.get('retry_at', None)
        self.service = kwargs.get('service', None)

    def log(self, msg):
        "Log our error to STDERR"
        logging.error(msg)

    @property
    def error_msg(self):
        return error_format(
            self.message,
            code=self.code,
            retry_at=self.retry_at,
            service=self.service,
        )


class ApiMethodError(LightningError):
    """The error class for exceptions within the services"""
    pass


class DatastoreError(LightningError):
    """The error class for errors in the datastore"""
    pass


class MissingArgumentError(LightningError):
    """Error when handlers are missing arguments"""
    def __init__(self, message, **kwargs):
        super(MissingArgumentError, self).__init__(message, **kwargs)
        self.code = 400


class ServiceError(LightningError):
    """Base class for all service-related errors"""
    pass


class AuthError(ServiceError):
    """Unable to complete the auth process"""
    pass

class InsufficientPermissionsError(ServiceError):
    """Unable to return data due to insufficient permissions"""
    def __init__(self, message, **kwargs):
        super(InsufficientPermissionsError, self).__init__(message, **kwargs)
        self.code = 403

class InvalidTokenError(ServiceError):
    """Provided token has expired or is invalid"""
    pass


class InvalidRedirectError(ServiceError):
    """Invalid redirect_uri passed to service"""
    pass


class OverCapacityError(ServiceError):
    """Service is over capacity"""
    pass


class RateLimitError(ServiceError):
    """Rate limited"""
    pass


class RefreshTokenError(ServiceError):
    """Rate limited"""
    pass


class RequestError(ServiceError):
    """The error class for a generic problem with a request"""
    def __init__(self, resp=None, msg='Bad Response'):
        """Initialize a new RequestError when given a response and message."""
        super(RequestError, self).__init__(resp, msg)
        err_cls = self.__class__.__name__
        # Log our error.
        if resp:
            self.log(
                '%s (%s): %s\nURL: %s\n%s' %
                (err_cls, resp.code, msg, resp.effective_url, resp.body)
            )
        else:
            self.log(
                '%s: %s' %
                (err_cls, msg)
            )

"Generic docstring A"
from __future__ import absolute_import

from .error import ErrorHandler

from twisted.web.resource import Resource
from .base import HandlerBase
from .api import ApiHandler, ApiOneHandler, ApiMethHandler
from .auth import AuthHandler, AuthOneHandler#, AuthActivateHandler
from .data import DataHandler
from .stream import StreamHandler
from .status import StatusHandler
from .view import ViewHandler, ViewOneHandler, ApplyViewHandler

def resource_tree(application):
    root = HandlerBase(application)
    root.putChild('api', ApiHandler(application));
    root.putChild('view', ViewHandler(application))
    root.putChild('auth', AuthHandler(application))
    root.putChild('stream', StreamHandler(application))
    root.putChild('status', StatusHandler(application))
    root.putChild('data', DataHandler(application))

    return root

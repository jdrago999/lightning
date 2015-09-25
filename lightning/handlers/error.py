"""
This is where the Error handlers live.
"""

from __future__ import absolute_import

from .base import HandlerBase
from cyclone.web import HTTPError


class ErrorHandler(HandlerBase):
    """Error handler for Handler classes."""
    def __init__(self, application, request, status_code):
        """Register our error handler."""
        super(ErrorHandler, self).__init__(application, request)
        self.set_status(status_code)

    def prepare(self):
        """Prepare the error."""
        raise HTTPError(self._status_code)

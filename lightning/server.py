"""
Override/Monkeypatch certian twisted.web stuff
"""
from twisted.web import server

# System Imports

import string
import types
import json

# Twisted Imports
from twisted.web import  http
from twisted.web.server import supportedMethods, NOT_DONE_YET
from twisted.python import log, reflect
from twisted.web import util as webutil, resource
from twisted.web.microdom import escape
from twisted.web.error import UnsupportedMethod

class JsonErrorPage(resource.ErrorPage):
    def render(self, request):
        request.setResponseCode(self.code)
        request.setHeader("content-type", "application/json")
        error = {'error': {'message': self.detail}}        
        return json.dumps(error, ensure_ascii=True) 

class Request(server.Request):
    def render(self, resrc):
        """
        Ask a resource to render itself. Monkeypatches the origianl render method to throw a 405 on unknown
        methods instead of a 501.  Also makes responses JSON style

        @param resrc: a L{twisted.web.resource.IResource}.
        """
        try:
            body = resrc.render(self)
        except UnsupportedMethod, e:
            allowedMethods = e.allowedMethods
            if (self.method == "HEAD") and ("GET" in allowedMethods):
                # We must support HEAD (RFC 2616, 5.1.1).  If the
                # resource doesn't, fake it by giving the resource
                # a 'GET' request and then return only the headers,
                # not the body.
                log.msg("Using GET to fake a HEAD request for %s" %
                        (resrc,))
                self.method = "GET"
                self._inFakeHead = True
                body = resrc.render(self)

                if body is NOT_DONE_YET:
                    log.msg("Tried to fake a HEAD request for %s, but "
                            "it got away from me." % resrc)
                    # Oh well, I guess we won't include the content length.
                else:
                    self.setHeader('content-length', str(len(body)))

                self._inFakeHead = False
                self.method = "HEAD"
                self.write('')
                self.finish()
                return

            if self.method in (supportedMethods):
                # We MUST include an Allow header
                # (RFC 2616, 10.4.6 and 14.7)
                self.setHeader('Allow', ', '.join(allowedMethods))
                s = ("""'%(method)s' not supported for '%(URI)s'""" % {
                    'URI': escape(self.uri),
                    'method': self.method,
                    'plural': ((len(allowedMethods) > 1) and 's') or '',
                    'allowed': string.join(allowedMethods, ', ')
                    })
                epage = JsonErrorPage(http.NOT_ALLOWED,
                                           "Method Not Allowed", s)
                body = epage.render(self)
            else:
                epage = JsonErrorPage(
                    http.NOT_ALLOWED, "Huh?",
                    "'%s' not supported for '%s'" %
                    (escape(self.method), escape(self.uri),))
                body = epage.render(self)
        # end except UnsupportedMethod

        if body == NOT_DONE_YET:
            return
        if type(body) is not types.StringType:
            body = JsonErrorPage(
                http.INTERNAL_SERVER_ERROR,
                "Request did not return a string",
                "Request: " + html.PRE(reflect.safe_repr(self)) + "<br />" +
                "Resource: " + html.PRE(reflect.safe_repr(resrc)) + "<br />" +
                "Value: " + html.PRE(reflect.safe_repr(body))).render(self)

        if self.method == "HEAD":
            if len(body) > 0:
                # This is a Bad Thing (RFC 2616, 9.4)
                log.msg("Warning: HEAD request %s for resource %s is"
                        " returning a message body."
                        "  I think I'll eat it."
                        % (self, resrc))
                self.setHeader('content-length', str(len(body)))
            self.write('')
        else:
            self.setHeader('content-length', str(len(body)))
            self.write(body)
        self.finish()

from lightning.model import DatastoreModel
from twisted.internet import defer
"""The Authorization object."""


class Authz(DatastoreModel):
    """Class used to model data for an authorization."""
    TABLENAME = "[Authorization]"

    @defer.inlineCallbacks
    def get_token(self, datastore):
        """Get the token from the datastore."""
        authz = yield datastore.get_oauth_token(**self.to_dict())
        defer.returnValue(authz)

    @defer.inlineCallbacks
    def set_token(self, datastore):
        """Set the token in the datastore."""
        authz = yield datastore.set_oauth_token(**self.to_dict())
        defer.returnValue(authz)
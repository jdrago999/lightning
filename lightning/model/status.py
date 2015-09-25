from lightning.model import LimitedDict
from lightning.utils import enum

# Define Status Codes
StatusCode = enum(
    OK=200,
    NOT_FOUND=404,
    UNKNOWN=502
)
# Define Status Messages
StatusMessage = enum(
    OK="OK",
    NOT_FOUND="GUID not found",
)
# Note: All other Status responses come from lightning.error


class Status(LimitedDict):
    """Status class.
    Represents a Status.
    """
    def __init__(self, *args, **kwargs):
        keys = [
            'code',
            'guid',
            'is_refreshable',
            'message',
            'service_name',
        ]
        super(Status, self).__init__(keys, **kwargs)
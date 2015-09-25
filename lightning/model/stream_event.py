from lightning.model import LimitedDict
from lightning.utils import enum

# Define Stream Types
StreamType = enum(
    ARTICLE='article',
    PHOTO='photo',
    STATUS='status',
    TRANSACTION='transaction',
    VIDEO='video',
    VIDEO_EMBED='video_embed',
)

def get_type(event):
    """Given a StreamEvent, determine its proper type."""
    # Default to STATUS
    stream_type = StreamType.STATUS

    if event['name'] and event['description']:
        stream_type = StreamType.ARTICLE
    elif event['video_id']:
        stream_type = StreamType.VIDEO_EMBED
    elif event['video_link']:
        stream_type = StreamType.VIDEO
    elif event['picture_link']:
        stream_type = StreamType.PHOTO
    return stream_type


class StreamEvent(LimitedDict):
    """StreamEvent class.
    Represents a single StreamEvent.
    """
    def __init__(self, *args, **kwargs):
        keys = [
            'metadata',
            'author',
            'activity',
        ]
        super(StreamEvent, self).__init__(keys, **kwargs)

        # Set up our child objects
        self['metadata'] = StreamMetadata(**self['metadata'])
        self['author'] = StreamUser(**self['author'])
        self['activity'] = StreamActivity(**self['activity'])

class StreamMetadata(LimitedDict):
    """StreamMetadata class.
    Represents metadata of a StreamEvent.
    """
    def __init__(self, *args, **kwargs):
        keys = [
            'is_echo',
            'is_private',
            'post_id',
            'service',
            'timestamp',
        ]
        super(StreamMetadata, self).__init__(keys, **kwargs)


class StreamUser(LimitedDict):
    """StreamUser class.
    Represents a user within a StreamEvent. Used for author and any
    additional_users in a StreamEvent.
    """
    def __init__(self, *args, **kwargs):
        keys = [
            'name',
            'profile_link',
            'profile_picture_link',
            'user_id',
            'username',
        ]
        super(StreamUser, self).__init__(keys, **kwargs)


class StreamLocation(LimitedDict):
    """StreamLocation class.
    Represents a location within a StreamEvent.
    """
    def __init__(self, *args, **kwargs):
        keys = [
            'latitude',
            'longitude',
            'name',
        ]
        super(StreamLocation, self).__init__(keys, **kwargs)


class StreamActivity(LimitedDict):
    """StreamActivity class.
    Represents an activity within a StreamEvent.
    """
    def __init__(self, *args, **kwargs):
        keys = [
            'activity_link',
            'additional_users',
            'caption',
            'description',
            'location',
            'name',
            'picture_link',
            'story',
            'thumbnail_link',
            'type',
            'video_id',
            'video_link',
        ]
        super(StreamActivity, self).__init__(keys, **kwargs)
        if self['additional_users']:
            additional_users = []
            for user in self['additional_users']:
                additional_users.append(StreamUser(**user))
            self['additional_users'] = additional_users
        if self['location']:
            self['location'] = StreamLocation(**self['location'])
        if not self['type']:
            self['type'] = get_type(self)
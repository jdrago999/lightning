"Generic docstring A"
from __future__ import absolute_import

from .blogger import BloggerWeb
from .etsy import EtsyWeb
from .facebook import FacebookWeb
from .flickr import FlickrWeb
from .foursquare import FoursquareWeb
from .github import GitHubWeb
from .googleplus import GooglePlusWeb
from .instagram import InstagramWeb
from .linkedin import LinkedInWeb
from .reddit import RedditWeb
from .runkeeper import RunKeeperWeb
from .soundcloud import SoundCloudWeb
from .twitter import TwitterWeb
from .vimeo import VimeoWeb
from .wordpress import WordPressWeb
from .youtube import YoutubeWeb

# For testing purposes
from .loopback import LoopbackWeb, Loopback2Web

WEB_MODULES = [
    BloggerWeb,
    EtsyWeb,
    FacebookWeb,
    FlickrWeb,
    FoursquareWeb,
    GitHubWeb,
    GooglePlusWeb,
    InstagramWeb,
    LinkedInWeb,
    RedditWeb,
    RunKeeperWeb,
    SoundCloudWeb,
    TwitterWeb,
    VimeoWeb,
    WordPressWeb,
    YoutubeWeb,

    # For testing purposes
    LoopbackWeb,
    Loopback2Web,
]

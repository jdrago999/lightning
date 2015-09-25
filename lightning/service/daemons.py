"Generic docstring A"
from __future__ import absolute_import

from .blogger import BloggerDaemon
from .etsy import EtsyDaemon
from .facebook import FacebookDaemon
from .flickr import FlickrDaemon
from .foursquare import FoursquareDaemon
from .github import GitHubDaemon
from .googleplus import GooglePlusDaemon
from .instagram import InstagramDaemon
#from .linkedin import LinkedInDaemon # LinkedIn has no daemon implementation due to data storage rules in TOS
from .reddit import RedditDaemon
from .runkeeper import RunKeeperDaemon
from .soundcloud import SoundCloudDaemon
from .twitter import TwitterDaemon
from .wordpress import WordPressDaemon
from .vimeo import VimeoDaemon
from .youtube import YoutubeDaemon

# For testing purposes
from .loopback import LoopbackDaemon

DAEMONS = dict(
    BloggerDaemon=BloggerDaemon,
    EtsyDaemon=EtsyDaemon,
    FacebookDaemon=FacebookDaemon,
    FlickrDaemon=FlickrDaemon,
    FoursquareDaemon=FoursquareDaemon,
    GitHubDaemon=GitHubDaemon,
    GooglePlusDaemon=GooglePlusDaemon,
    InstagramDaemon=InstagramDaemon,
    RedditDaemon=RedditDaemon,
    RunKeeperDaemon=RunKeeperDaemon,
    SoundCloudDaemon=SoundCloudDaemon,
    TwitterDaemon=TwitterDaemon,
    VimeoDaemon=VimeoDaemon,
    WordPressDaemon=WordPressDaemon,
    YoutubeDaemon=YoutubeDaemon,

    # Testing daemons
    LoopbackDaemon=LoopbackDaemon,
)

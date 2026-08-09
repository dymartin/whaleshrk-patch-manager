"""Device-state-to-repo direction: turning card drift into reviewable PRs.

`rig.pull.reverse` maps an observed preset back into edits on an *existing*
song's document; `rig.pull.runner.pull` is the orchestrator that reads the
card, matches presets to songs by recorded directory name, and drives the
result through `rig.pull.gitio`'s branch/commit/PR seam. See
`docs/workflows/pull.md`.
"""

from .errors import PullError
from .gitio import GhClient, GhError, GitError, GitRepo, SubprocessGhClient
from .reverse import FieldChange, ReverseMapError, reverse_map_song
from .runner import PullResult, pull

__all__ = [
    "PullError",
    "GhClient",
    "GhError",
    "GitError",
    "GitRepo",
    "SubprocessGhClient",
    "FieldChange",
    "ReverseMapError",
    "reverse_map_song",
    "PullResult",
    "pull",
]

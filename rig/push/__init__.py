"""Push: make the card match the repo. See docs/workflows/push.md.

`push()` is the phase's entry point; everything else here is the public
surface later phases (Task 7's pull, Task 8's CLI) build on -- state
readers to compute drift baselines, and the error types every refusal
raises.
"""

from .errors import PushError
from .media import MediaGroup, MediaPlan, build_media_plan
from .modules import (
    ModuleInstall,
    ModuleReconcilePlan,
    ModuleSource,
    ModuleSourceUnavailable,
    OrhackIntegrityError,
    installed_content_hash,
    module_install_dir,
    plan_module_reconciliation,
    verify_orhack_manifest,
    verify_orhack_structure,
)
from .archive_source import StoredArchiveModuleSource
from .plan import (
    Classification,
    ChainRenameSuspect,
    chain_rename_message,
    classify_card_presets,
    detect_chain_rename,
    gap_programs,
    is_placeholder_directory,
)
from .runner import PushResult, push
from .state import LastPushedMeta, read_all_meta, read_meta, read_params
from .transact import PushTransactionError

__all__ = [
    "PushError",
    "MediaGroup",
    "MediaPlan",
    "build_media_plan",
    "ModuleInstall",
    "ModuleReconcilePlan",
    "ModuleSource",
    "ModuleSourceUnavailable",
    "OrhackIntegrityError",
    "installed_content_hash",
    "module_install_dir",
    "plan_module_reconciliation",
    "verify_orhack_manifest",
    "verify_orhack_structure",
    "StoredArchiveModuleSource",
    "Classification",
    "ChainRenameSuspect",
    "chain_rename_message",
    "classify_card_presets",
    "detect_chain_rename",
    "gap_programs",
    "is_placeholder_directory",
    "PushResult",
    "push",
    "LastPushedMeta",
    "read_all_meta",
    "read_meta",
    "read_params",
    "PushTransactionError",
]

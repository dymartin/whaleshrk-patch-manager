"""Song model -> on-device preset compiler.

`compile_song` is the phase's main entry point; `build_placeholder` and
`format_program_prefix` are the two pieces push (Task 5) needs that the
compiler owns the *shape* of but does not decide when to use -- see
docs/workflows/push.md and `rig.compile.compiler`'s module docstring.
"""

from .compiler import CompiledPreset, build_placeholder, compile_song, format_program_prefix
from .errors import CompileError
from .samples import ResolvedSample, SampleCompileError, resolve_sample, scan_wav_folder, scan_wav_names
from .sidecars import UnverifiedStatefulModuleError, sidecar_files_for_slot

__all__ = [
    "CompiledPreset",
    "build_placeholder",
    "compile_song",
    "format_program_prefix",
    "CompileError",
    "ResolvedSample",
    "SampleCompileError",
    "resolve_sample",
    "scan_wav_folder",
    "scan_wav_names",
    "UnverifiedStatefulModuleError",
    "sidecar_files_for_slot",
]

"""Song model to on-device preset compiler."""

from .compiler import CompiledPreset, build_placeholder, compile_song, format_program_prefix
from .errors import CompileError
from .samples import ResolvedSample, SampleCompileError, resolve_sample, scan_wav_folder, scan_wav_names
from .sidecars import UnverifiedStatefulModuleError, sidecar_files_for_slot

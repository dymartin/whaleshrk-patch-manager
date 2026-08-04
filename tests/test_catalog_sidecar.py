"""Preset-sidecar detection -- docs/catalog.md "Detecting preset sidecars".

Resolved-pattern cases are taken verbatim from real module source: morpher's
own convention (mod-sources/morpher/morpher.pd) and a real community
sequencer (candidate 113470, "sequencers-bpm") whose suffix does not match
any of the five built-ins yet still resolves under the same `$1/presets/$2/`
convention -- see rig/catalog/sidecar.py for why that is correct.
"""

from rig.catalog.sidecar import scan_module_sidecars, scan_pd_text


def test_morpher_pattern_resolves():
    text = r"#X msg 357 322 write \$1/presets/\$2/\$4.txt cr;"
    result = scan_pd_text(text)
    assert result.is_modelled
    assert result.resolved == [r"\$1/presets/\$2/\$4.txt"]


def test_polystep_style_pattern_resolves():
    text = r"#X msg 1025 274 write \$1/presets/\$2/\$3-notes.txt;"
    result = scan_pd_text(text)
    assert result.is_modelled


def test_novel_suffix_from_a_real_community_module_still_resolves():
    # sequencers-bpm's Punchy module -- suffix "punchy-seqvel" matches none
    # of the five built-in templates, but the $1/presets/$2/ convention with
    # a literal suffix is still mechanically reproducible by the compiler.
    text = r"#X msg 1095 595 read \$1/presets/\$2/\$3-punchy-seqvel.txt;"
    result = scan_pd_text(text)
    assert result.is_modelled


def test_missing_preset_name_substitution_is_unresolved():
    # A hardcoded preset name instead of $2 -- not framework-injected, so the
    # compiler cannot regenerate it for an arbitrary preset.
    text = r"#X msg 100 100 write \$1/presets/myfixedname/\$3-data.txt;"
    result = scan_pd_text(text)
    assert not result.is_modelled
    assert result.unresolved


def test_additional_dollar_tokens_still_resolve():
    # $5 (or any $N) is still just another framework-style substitution --
    # the compiler can synthesize it once slot/index values are known.
    text = r"#X msg 100 100 write \$1/presets/\$2/\$3-\$5-name.txt;"
    result = scan_pd_text(text)
    assert result.is_modelled


def test_non_dollar_dynamic_fragment_is_unresolved():
    # Anything that is not a literal filename character or a $N token --
    # here a bracketed expression -- cannot be a fixed template.
    text = r"#X msg 100 100 write \$1/presets/\$2/[something(].txt;"
    result = scan_pd_text(text)
    assert not result.is_modelled


def test_non_presets_read_write_is_ignored():
    text = r"#X msg 100 100 read \$1/data/\$2/other.txt;"
    result = scan_pd_text(text)
    assert result.resolved == []
    assert result.unresolved == []


def test_canvas_names_containing_presets_are_not_matched():
    # False positives seen in real candidates: a canvas/subpatch literally
    # named "presets" or "czz_presets" is not a read/write message.
    text = "#N canvas 19 50 1164 887 czz_presets 0;"
    result = scan_pd_text(text)
    assert result.resolved == []
    assert result.unresolved == []


def test_receive_object_named_presets_is_not_matched():
    # `r presets` is Pd's `receive` object, unrelated to file I/O -- seen
    # verbatim in candidate 169898 ("faustsdx7").
    text = "#X obj 74 14 r presets;"
    result = scan_pd_text(text)
    assert result.resolved == []
    assert result.unresolved == []


def test_text_comment_mentioning_presets_is_not_matched():
    text = "#X text 35 94 Store presets;"
    result = scan_pd_text(text)
    assert result.resolved == []
    assert result.unresolved == []


def test_module_with_no_sidecar_message_is_stateless_and_passes():
    result = scan_module_sidecars({"module.pd": "#X obj 10 10 osc~ 440;"})
    assert result.is_modelled
    assert result.resolved == []


def test_scan_module_sidecars_aggregates_across_files():
    pd_files = {
        "a.pd": r"#X msg 1 1 read \$1/presets/\$2/\$3-a.txt;",
        "b.pd": r"#X msg 1 1 write \$1/presets/\$2/\$3-b.txt;",
    }
    result = scan_module_sidecars(pd_files)
    assert len(result.resolved) == 2

"""Every section label the analyzer can emit has sequencing config."""

from xlights_mcp.audio.sections import SECTION_LABELS
from xlights_mcp.sequencer.engine import SECTION_TYPE_CONFIG


def test_every_section_label_has_engine_config():
    assert set(SECTION_LABELS) <= set(SECTION_TYPE_CONFIG)

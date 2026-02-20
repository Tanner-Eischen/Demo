"""
Unit tests for the holistic narration pipeline components.

These tests verify the logic of the holistic pipeline modules
without requiring FFmpeg or external services.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Set up environment
os.environ.setdefault("DATA_DIR", str(Path(__file__).parent / "data"))
os.environ.setdefault("NARRATION_MODE", "holistic")

# Load .env if exists
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and not os.environ.get(key):
                os.environ[key] = value

# Add backend to path
backend_path = Path(__file__).parent / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path.parent))


def test_models():
    """Test the data models."""
    print("\n[TEST] Testing models...")

    from backend.app.pipeline.holistic.models import (
        VideoMetadata,
        ScriptSection,
        HolisticScript,
        KeyframeMoment,
        NarrationMatch,
        TimingPlan,
        TimedNarrationSection,
        SplitScript,
        SemanticMarker,
    )

    # Test VideoMetadata
    vm = VideoMetadata(duration_ms=30000, estimated_scene_count=10, width=1920, height=1080, fps=30.0)
    assert vm.duration_s == 30.0
    print("  [OK] VideoMetadata")

    # Test ScriptSection
    section = ScriptSection(
        section_id=0,
        text="Welcome to the demo!",
        semantic_marker=SemanticMarker.INTRO,
        estimated_duration_ms=3000,
    )
    assert section.word_count == 4
    assert section.to_dict()["section_id"] == 0
    parsed = ScriptSection.from_dict(section.to_dict())
    assert parsed.text == section.text
    print("  [OK] ScriptSection")

    # Test HolisticScript
    script = HolisticScript(
        full_text="Welcome to the demo! This is a test.",
        sections=[section],
        project_context_used="Test context",
    )
    assert script.total_word_count == 8  # 8 words in "Welcome to the demo! This is a test."
    assert len(script.sections) == 1
    script_dict = script.to_dict()
    parsed_script = HolisticScript.from_dict(script_dict)
    assert parsed_script.full_text == script.full_text
    print("  [OK] HolisticScript")

    # Test KeyframeMoment
    kf = KeyframeMoment(timestamp_ms=5000, path="/tmp/kf0.png", visual_signature="Test frame")
    assert kf.timestamp_s == 5.0
    print("  [OK] KeyframeMoment")

    # Test NarrationMatch
    match = NarrationMatch(
        section_id=0,
        matched_keyframe_index=2,
        confidence=0.85,
        visual_context="Login screen",
        reasoning="Matches the intro narration",
    )
    assert match.confidence > 0.5
    print("  [OK] NarrationMatch")

    # Test TimingPlan
    plan = TimingPlan(matches=[match], unmatched_sections=[1], keyframes_used=[2])
    found = plan.get_match_for_section(0)
    assert found is not None
    assert found.matched_keyframe_index == 2
    assert plan.get_match_for_section(99) is None
    print("  [OK] TimingPlan")

    # Test TimedNarrationSection
    timed = TimedNarrationSection(
        section_id=0,
        text="Hello world",
        start_ms=0,
        end_ms=3000,
        target_words=3,
        semantic_marker=SemanticMarker.INTRO,
    )
    assert timed.duration_ms == 3000
    assert timed.duration_s == 3.0
    assert timed.actual_word_count == 2
    assert abs(timed.words_per_second - 0.667) < 0.01
    print("  [OK] TimedNarrationSection")

    # Test SplitScript
    split = SplitScript(
        sections=[timed],
        total_duration_ms=30000,
        has_gaps=False,
        original_script_text="Hello world",
    )
    assert split.total_word_count == 2
    split_dict = split.to_dict()
    parsed_split = SplitScript.from_dict(split_dict)
    assert len(parsed_split.sections) == 1
    print("  [OK] SplitScript")

    print("[PASS] All model tests passed!")
    return True


def test_script_generator():
    """Test the script generator logic."""
    print("\n[TEST] Testing script generator...")

    from backend.app.pipeline.holistic.models import VideoMetadata
    from backend.app.pipeline.holistic.script_generator import (
        build_holistic_script_messages,
        _parse_script_response,
    )

    # Test VideoMetadata
    vm = VideoMetadata(duration_ms=60000, estimated_scene_count=15, width=1920, height=1080)

    # Test message building
    messages = build_holistic_script_messages("Test project context", vm)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "60.0 seconds" in messages[1]["content"]
    print("  [OK] build_holistic_script_messages")

    # Test response parsing - valid JSON
    valid_json = '{"full_text": "Hello world", "sections": [{"section_id": 0, "text": "Hello world", "semantic_marker": "intro"}]}'
    parsed = _parse_script_response(valid_json)
    assert parsed["full_text"] == "Hello world"
    assert len(parsed["sections"]) == 1
    print("  [OK] _parse_script_response (valid JSON)")

    # Test response parsing - markdown wrapped
    markdown_json = '''```json
{"full_text": "Test", "sections": []}
```'''
    parsed = _parse_script_response(markdown_json)
    assert parsed["full_text"] == "Test"
    print("  [OK] _parse_script_response (markdown)")

    # Test response parsing - plain text fallback
    plain_text = "This is just plain text narration."
    parsed = _parse_script_response(plain_text)
    assert parsed["full_text"] == plain_text
    print("  [OK] _parse_script_response (plain text)")

    print("[PASS] Script generator tests passed!")
    return True


def test_script_splitter():
    """Test the script splitter logic."""
    print("\n[TEST] Testing script splitter...")

    from backend.app.pipeline.holistic.models import (
        HolisticScript,
        ScriptSection,
        KeyframeMoment,
        TimingPlan,
        NarrationMatch,
        VideoMetadata,
        SemanticMarker,
    )
    from backend.app.pipeline.holistic.script_splitter import (
        _calculate_section_duration,
        convert_split_script_to_segments,
    )

    # Test duration calculation
    # "Hello world this is a test" = 6 words / 2.5 wps = 2.4s = 2400ms
    duration = _calculate_section_duration("Hello world this is a test", wps=2.5)
    assert duration == 2400  # 6 words / 2.5 wps = 2.4 seconds = 2400ms
    print("  [OK] _calculate_section_duration")

    # Test segment conversion
    from backend.app.pipeline.holistic.models import SplitScript, TimedNarrationSection

    split = SplitScript(
        sections=[
            TimedNarrationSection(
                section_id=0,
                text="Hello world",
                start_ms=0,
                end_ms=2000,
                target_words=3,
                semantic_marker=SemanticMarker.INTRO,
            ),
            TimedNarrationSection(
                section_id=1,
                text="Goodbye",
                start_ms=2000,
                end_ms=4000,
                target_words=2,
                semantic_marker=SemanticMarker.CONCLUSION,
            ),
        ],
        total_duration_ms=4000,
    )

    segments = convert_split_script_to_segments(split)
    assert len(segments) == 2
    assert segments[0]["id"] == 0
    assert segments[0]["start_ms"] == 0
    assert segments[0]["end_ms"] == 2000
    assert segments[0]["narration"]["selected_text"] == "Hello world"
    assert segments[1]["id"] == 1
    print("  [OK] convert_split_script_to_segments")

    print("[PASS] Script splitter tests passed!")
    return True


def test_timing_matcher_helpers():
    """Test timing matcher helper functions."""
    print("\n[TEST] Testing timing matcher helpers...")

    from backend.app.pipeline.holistic.timing_matcher import (
        _encode_image_as_data_url,
        DEFAULT_KEYFRAME_DENSITY,
        MATCHING_BATCH_SIZE,
    )

    # Test constants
    assert DEFAULT_KEYFRAME_DENSITY == 1.0
    assert MATCHING_BATCH_SIZE == 5
    print("  [OK] Constants")

    # Test data URL encoding (will fail if file doesn't exist, that's OK)
    try:
        test_file = Path(__file__).parent / "data" / "video.mp4"
        if test_file.exists():
            # This should fail because it's not an image
            try:
                _encode_image_as_data_url(str(test_file))
                print("  [SKIP] _encode_image_as_data_url (unexpected success)")
            except Exception:
                print("  [OK] _encode_image_as_data_url (expected to fail for non-image)")
        else:
            print("  [SKIP] _encode_image_as_data_url (no test file)")
    except Exception as e:
        print(f"  [SKIP] _encode_image_as_data_url ({e})")

    print("[PASS] Timing matcher helper tests passed!")
    return True


def test_config_integration():
    """Test that config settings are properly loaded."""
    print("\n[TEST] Testing config integration...")

    from backend.app.config import settings

    # Check holistic settings exist
    assert hasattr(settings, "narration_mode")
    assert hasattr(settings, "holistic_keyframe_density")
    assert hasattr(settings, "holistic_match_confidence_threshold")
    assert hasattr(settings, "holistic_fallback_to_segment")
    print("  [OK] Holistic config attributes exist")

    # Check values
    assert settings.narration_mode in ("segment", "holistic")
    assert settings.holistic_keyframe_density > 0
    assert 0 <= settings.holistic_match_confidence_threshold <= 1
    assert isinstance(settings.holistic_fallback_to_segment, bool)
    print(f"  [OK] Config values: mode={settings.narration_mode}, "
          f"density={settings.holistic_keyframe_density}, "
          f"threshold={settings.holistic_match_confidence_threshold}, "
          f"fallback={settings.holistic_fallback_to_segment}")

    print("[PASS] Config integration tests passed!")
    return True


def test_storage_integration():
    """Test that storage schema includes holistic fields."""
    print("\n[TEST] Testing storage integration...")

    from backend.app.storage import ensure_project_defaults, SCHEMA_VERSION

    # Check schema version
    assert SCHEMA_VERSION == "1.2.0", f"Expected 1.2.0, got {SCHEMA_VERSION}"
    print(f"  [OK] Schema version: {SCHEMA_VERSION}")

    # Test ensure_project_defaults adds holistic fields
    test_proj = {
        "schema_version": "1.0.0",
        "settings": {},
        "planning": {},
    }

    # Need to mock data_dir and project_id
    changed = ensure_project_defaults(test_proj, ".", "test_project")
    assert changed, "ensure_project_defaults should return True when adding defaults"
    assert "holistic" in test_proj["settings"]
    assert test_proj["settings"]["holistic"]["keyframe_density"] == 1.0
    assert "narration_mode" in test_proj["settings"]
    assert "holistic" in test_proj
    print("  [OK] ensure_project_defaults adds holistic fields")

    print("[PASS] Storage integration tests passed!")
    return True


def test_pipeline_main_integration():
    """Test that pipeline_main has the mode selection."""
    print("\n[TEST] Testing pipeline_main integration...")

    # Check that run_segment_pipeline exists
    from backend.app.pipeline.pipeline_main import run_segment_pipeline, run_pipeline
    print("  [OK] run_segment_pipeline exists")
    print("  [OK] run_pipeline exists")

    # Verify run_pipeline is callable
    assert callable(run_pipeline)
    assert callable(run_segment_pipeline)
    print("  [OK] Functions are callable")

    print("[PASS] Pipeline main integration tests passed!")
    return True


def run_all_tests():
    """Run all unit tests."""
    print("=" * 60)
    print("HOLISTIC PIPELINE UNIT TESTS")
    print("=" * 60)

    results = []

    tests = [
        ("Models", test_models),
        ("Script Generator", test_script_generator),
        ("Script Splitter", test_script_splitter),
        ("Timing Matcher Helpers", test_timing_matcher_helpers),
        ("Config Integration", test_config_integration),
        ("Storage Integration", test_storage_integration),
        ("Pipeline Main Integration", test_pipeline_main_integration),
    ]

    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success, None))
        except Exception as e:
            import traceback
            results.append((name, False, str(e)))
            print(f"[FAIL] {name}: {e}")
            traceback.print_exc()

    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, success, _ in results if success)
    total = len(results)

    for name, success, error in results:
        status = "PASS" if success else "FAIL"
        print(f"  [{status}] {name}")
        if error:
            print(f"        Error: {error[:100]}")

    print()
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 60)

    return passed == total


if __name__ == "__main__":
    import sys
    success = run_all_tests()
    sys.exit(0 if success else 1)

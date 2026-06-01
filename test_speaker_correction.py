#!/usr/bin/env python3
"""
Test speaker name frequency counting and self-correction detection.
This validates the fix for the speaker diarization self-correction issue.
"""

import re
import json


def extract_speaker_names_v2(transcript_utterances):
    """NEW: Name frequency counter approach"""
    speaker_names = {}
    speaker_name_counts = {}

    for segment in transcript_utterances:
        speaker_id = getattr(segment, 'speaker', None) or "Unknown"
        if speaker_id not in speaker_name_counts:
            speaker_name_counts[speaker_id] = {}

        # Find all name mentions
        text = getattr(segment, 'text', '')
        matches = re.finditer(r"[Ii](?:'m| am) ([A-Z][a-z]+)", text)
        for match in matches:
            name = match.group(1)
            speaker_name_counts[speaker_id][name] = speaker_name_counts[speaker_id].get(name, 0) + 1

    # Choose most frequent name
    for speaker_id, names_dict in speaker_name_counts.items():
        if names_dict:
            speaker_names[speaker_id] = max(names_dict, key=names_dict.get)

    return speaker_names, speaker_name_counts


class MockSegment:
    """Mock AssemblyAI segment for testing"""
    def __init__(self, speaker, text, start=0, end=1):
        self.speaker = speaker
        self.text = text
        self.start = start
        self.end = end
        self.confidence = 0.9


def test_case_1_self_correction():
    """Test Case 1: Self-Correction (I'm James → I'm Lanes)"""
    print("\n" + "="*70)
    print("TEST CASE 1: Self-Correction")
    print("="*70)
    print("Scenario: Speaker A says 'I'm James' then 'I'm Lanes'")
    print("Expected: Should use 'Lanes' (mentioned 2x) as final name")

    utterances = [
        MockSegment("A", "I'm James and I'm here to discuss..."),
        MockSegment("A", "Actually I'm Lanes, sorry about that"),
        MockSegment("A", "I'm Lanes and I work at..."),
    ]

    names, counts = extract_speaker_names_v2(utterances)

    print(f"\nResults:")
    print(f"  Speaker A name: {names.get('A')}")
    print(f"  Name mentions: {counts.get('A', {})}")

    assert names.get('A') == 'Lanes', f"Expected 'Lanes' but got {names.get('A')}"
    assert counts['A']['Lanes'] == 2, f"Expected Lanes count=2 but got {counts['A'].get('Lanes')}"
    print("✅ PASS")


def test_case_2_no_correction():
    """Test Case 2: No Correction (clean self-introduction)"""
    print("\n" + "="*70)
    print("TEST CASE 2: No Correction")
    print("="*70)
    print("Scenario: Speaker B clearly introduces as 'John' once")
    print("Expected: Should use 'John' as name, no correction flag")

    utterances = [
        MockSegment("B", "Hi I'm John, nice to meet you"),
        MockSegment("B", "Today I want to talk about..."),
        MockSegment("B", "Thanks for listening to me"),
    ]

    names, counts = extract_speaker_names_v2(utterances)

    print(f"\nResults:")
    print(f"  Speaker B name: {names.get('B')}")
    print(f"  Name mentions: {counts.get('B', {})}")

    assert names.get('B') == 'John', f"Expected 'John' but got {names.get('B')}"
    assert len(counts.get('B', {})) == 1, "Should only have one name"
    print("✅ PASS")


def test_case_3_ambiguous():
    """Test Case 3: Multiple Names (Ambiguous Case)"""
    print("\n" + "="*70)
    print("TEST CASE 3: Multiple Different Names")
    print("="*70)
    print("Scenario: Speaker C says 'I'm James', then 'actually Michael', then 'I'm James'")
    print("Expected: Should use 'James' (mentioned 2x, most frequent)")

    utterances = [
        MockSegment("C", "I'm James, let me start"),
        MockSegment("C", "Wait, actually I'm Michael"),
        MockSegment("C", "No sorry I'm James, that was confusing"),
    ]

    names, counts = extract_speaker_names_v2(utterances)

    print(f"\nResults:")
    print(f"  Speaker C name: {names.get('C')}")
    print(f"  Name mentions: {counts.get('C', {})}")

    assert names.get('C') == 'James', f"Expected 'James' (most frequent) but got {names.get('C')}"
    assert counts['C']['James'] == 2, "Expected James count=2"
    assert counts['C']['Michael'] == 1, "Expected Michael count=1"
    print("✅ PASS")


def test_case_4_multiple_speakers():
    """Test Case 4: Multiple Speakers (No Cross-Contamination)"""
    print("\n" + "="*70)
    print("TEST CASE 4: Multiple Speakers")
    print("="*70)
    print("Scenario: Two speakers introduce themselves")
    print("Expected: Each speaker has their own name, no mixing")

    utterances = [
        MockSegment("A", "Hi I'm John"),
        MockSegment("B", "Hi I'm Sarah"),
        MockSegment("A", "John here again"),
        MockSegment("B", "Sarah speaking"),
    ]

    names, counts = extract_speaker_names_v2(utterances)

    print(f"\nResults:")
    print(f"  Speaker A name: {names.get('A')}")
    print(f"  Speaker B name: {names.get('B')}")
    print(f"  Speaker A mentions: {counts.get('A', {})}")
    print(f"  Speaker B mentions: {counts.get('B', {})}")

    assert names.get('A') == 'John', f"Expected Speaker A='John' but got {names.get('A')}"
    assert names.get('B') == 'Sarah', f"Expected Speaker B='Sarah' but got {names.get('B')}"
    print("✅ PASS")


def test_case_5_unknown_speaker():
    """Test Case 5: Speaker with No Name Intro"""
    print("\n" + "="*70)
    print("TEST CASE 5: Speaker with No Introduction")
    print("="*70)
    print("Scenario: Speaker D never introduces themselves by name")
    print("Expected: No name in speaker dict, stays as None")

    utterances = [
        MockSegment("D", "Let me tell you about this"),
        MockSegment("D", "This is really interesting"),
    ]

    names, counts = extract_speaker_names_v2(utterances)

    print(f"\nResults:")
    print(f"  Speaker D name: {names.get('D')}")
    print(f"  Name mentions: {counts.get('D', {})}")

    assert 'D' not in names, "Speaker D should not have an extracted name"
    assert len(counts.get('D', {})) == 0, "Speaker D should have no name mentions"
    print("✅ PASS")


def test_metadata_generation():
    """Test generating correction metadata for JSON output"""
    print("\n" + "="*70)
    print("TEST: Correction Metadata Generation")
    print("="*70)
    print("Testing the metadata that would be added to JSON output")

    speaker_name_counts = {
        "A": {"James": 1, "Lanes": 2},  # Self-correction
        "B": {"John": 1},  # No correction
        "C": {"Michael": 2, "James": 1}  # Correction
    }

    speaker_names = {
        "A": "Lanes",  # Most frequent
        "B": "John",
        "C": "Michael"
    }

    # Build metadata for each speaker
    metadata = {}
    for speaker_id in speaker_name_counts:
        name_counts = speaker_name_counts[speaker_id]
        final_name = speaker_names.get(speaker_id)

        metadata[speaker_id] = {
            "name": final_name,
            "name_mentions": name_counts
        }

        # Flag corrections if multiple names
        if len(name_counts) > 1 and final_name:
            corrected_from = [n for n in name_counts.keys() if n != final_name]
            metadata[speaker_id]["corrected_from"] = corrected_from

    print(f"\nGenerated metadata:")
    print(json.dumps(metadata, indent=2))

    # Validate
    assert metadata["A"]["corrected_from"] == ["James"], "Speaker A should have James correction"
    assert "corrected_from" not in metadata["B"], "Speaker B should have no corrections"
    assert metadata["C"]["corrected_from"] == ["James"], "Speaker C should have James correction"
    print("✅ PASS")


if __name__ == "__main__":
    print("\n" + "🧪 TESTING SPEAKER DIARIZATION SELF-CORRECTION FIX")
    print("=" * 70)

    test_case_1_self_correction()
    test_case_2_no_correction()
    test_case_3_ambiguous()
    test_case_4_multiple_speakers()
    test_case_5_unknown_speaker()
    test_metadata_generation()

    print("\n" + "=" * 70)
    print("✅ ALL TESTS PASSED!")
    print("=" * 70)
    print("\nSummary:")
    print("- Name frequency counting handles self-corrections correctly")
    print("- Multiple speakers don't interfere with each other")
    print("- Metadata tracks corrections for narration context")
    print("- Speakers without introductions are handled gracefully")

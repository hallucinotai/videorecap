"""Sample AssemblyAI enhanced transcript for enrichment tests."""

SAMPLE_ASSEMBLYAI = {
    "metadata": {
        "provider": "assemblyai",
        "speaker_diarization_enabled": True,
        "language_code": "en",
    },
    "speakers": {
        "A": {
            "speaker_id": "A",
            "name": "James",
            "total_words": 10,
            "total_duration_seconds": 12.0,
            "avg_confidence": 0.94,
        },
        "B": {
            "speaker_id": "B",
            "name": None,
            "total_words": 15,
            "total_duration_seconds": 18.0,
            "avg_confidence": 0.91,
        },
    },
    "segments": {
        "0": {
            "text": "Hey, you made it.",
            "start": 4.2,
            "end": 7.1,
            "speaker": "A",
            "speaker_confidence": 0.94,
            "speaker_name": "James",
        },
        "1": {
            "text": "I'm Sarah, sorry about the traffic.",
            "start": 7.4,
            "end": 10.8,
            "speaker": "B",
            "speaker_confidence": 0.92,
        },
        "2": {
            "text": "I'm James, nice to meet you.",
            "start": 12.1,
            "end": 15.6,
            "speaker": "A",
            "speaker_confidence": 0.95,
            "speaker_name": "James",
        },
        "3": {
            "text": "Sarah, this is a big decision.",
            "start": 34.0,
            "end": 39.2,
            "speaker": "A",
            "speaker_confidence": 0.70,
        },
    },
}

WHISPER_LIST = [
    {"start": 0.0, "end": 5.0, "text": "Hello world"},
]

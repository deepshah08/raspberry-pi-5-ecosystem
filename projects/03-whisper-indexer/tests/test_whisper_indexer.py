import pytest
from unittest.mock import MagicMock, patch
import chromadb

import sys
import os

# Add parent directory to sys.path to allow importing transcribe and indexer
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from transcribe import transcribe_audio
from indexer import index_segments, query_segments

# --- Tests for transcribe.py ---

class MockSegment:
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text

@patch("transcribe.os.path.exists")
@patch("transcribe.WhisperModel")
def test_transcribe_audio(mock_whisper_model, mock_exists):
    # Setup mock
    mock_exists.return_value = True
    mock_model_instance = MagicMock()
    mock_whisper_model.return_value = mock_model_instance
    
    mock_segments = [
        MockSegment(0.0, 5.0, "Hello world"),
        MockSegment(5.0, 10.0, "Testing whisper")
    ]
    mock_info = MagicMock()
    mock_model_instance.transcribe.return_value = (mock_segments, mock_info)
    
    # Call function
    result = transcribe_audio("fake_path.mp3")
    
    # Verify results
    assert len(result) == 2
    assert result[0] == {"start": 0.0, "end": 5.0, "text": "Hello world"}
    assert result[1] == {"start": 5.0, "end": 10.0, "text": "Testing whisper"}
    
    # Verify WhisperModel was called correctly
    mock_whisper_model.assert_called_once_with("tiny", device="cpu", compute_type="int8")
    mock_model_instance.transcribe.assert_called_once_with("fake_path.mp3", beam_size=5)

@patch("transcribe.os.path.exists")
def test_transcribe_audio_file_not_found(mock_exists):
    mock_exists.return_value = False
    with pytest.raises(FileNotFoundError):
        transcribe_audio("nonexistent_file.mp3")


# --- Tests for indexer.py ---

@pytest.fixture
def memory_collection():
    client = chromadb.Client()
    collection = client.create_collection(name="test_collection")
    yield collection
    client.delete_collection(name="test_collection")

def test_index_and_query_segments(memory_collection):
    segments = [
        {"start": 0.0, "end": 5.0, "text": "This is the first segment"},
        {"start": 5.0, "end": 10.0, "text": "And this is the second segment"},
        {"start": 10.0, "end": 15.0, "text": "Finally, the third segment is here"}
    ]
    
    # Index segments
    index_segments(memory_collection, segments)
    
    assert memory_collection.count() == 3
    
    # Query without time filter
    results = query_segments(memory_collection, "second segment", n_results=1)
    assert len(results["ids"][0]) == 1
    assert "second" in results["documents"][0][0]

def test_query_segments_with_time_filter(memory_collection):
    segments = [
        {"start": 0.0, "end": 5.0, "text": "Keyword apple"},
        {"start": 5.0, "end": 10.0, "text": "Keyword banana"},
        {"start": 10.0, "end": 15.0, "text": "Keyword cherry"}
    ]
    index_segments(memory_collection, segments)
    
    # Query with start_time filter (start >= 5.0)
    results = query_segments(memory_collection, "Keyword", start_time=5.0)
    assert len(results["ids"][0]) == 2
    for meta in results["metadatas"][0]:
        assert meta["start"] >= 5.0

    # Query with end_time filter (end <= 10.0)
    results = query_segments(memory_collection, "Keyword", end_time=10.0)
    assert len(results["ids"][0]) == 2
    for meta in results["metadatas"][0]:
        assert meta["end"] <= 10.0
        
    # Query with both filters (start >= 5.0 AND end <= 10.0)
    results = query_segments(memory_collection, "Keyword", start_time=5.0, end_time=10.0)
    assert len(results["ids"][0]) == 1
    assert results["metadatas"][0][0]["start"] == 5.0
    assert results["documents"][0][0] == "Keyword banana"

def test_index_segments_with_id_prefix(memory_collection):
    segments = [
        {"start": 0.0, "end": 5.0, "text": "Segment audio 1"}
    ]
    index_segments(memory_collection, segments, id_prefix="track_01")
    
    assert memory_collection.count() == 1
    results = memory_collection.get(ids=["track_01_segment_0"])
    assert len(results["ids"]) == 1
    assert results["metadatas"][0]["audio_id"] == "track_01"

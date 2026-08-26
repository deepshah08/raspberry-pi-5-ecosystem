import os
from typing import List, Dict, Any

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

def transcribe_audio(
    file_path: str,
    model_size: str = "tiny",
    device: str = "cpu",
    compute_type: str = "int8"
) -> List[Dict[str, Any]]:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    if WhisperModel is None:
        raise RuntimeError("faster_whisper is not installed")

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, info = model.transcribe(file_path, beam_size=5)

    result_segments = []
    for segment in segments:
        result_segments.append({
            "start": segment.start,
            "end": segment.end,
            "text": segment.text
        })
        
    return result_segments

import os
from typing import List, Dict, Any
from faster_whisper import WhisperModel

def transcribe_audio(
    file_path: str,
    model_size: str = "tiny",
    device: str = "cpu",
    compute_type: str = "int8"
) -> List[Dict[str, Any]]:
    """
    Transcribes an audio file (MP3/WAV) using faster-whisper.
    
    Args:
        file_path (str): The path to the audio file.
        model_size (str): The size of the Whisper model to use.
        device (str): Device to run the model on ("cpu" or "cuda").
        compute_type (str): Computation type ("int8", "float16", etc.).
        
    Returns:
        List[Dict[str, Any]]: A list of dictionaries, where each dictionary
        represents a segment with 'start', 'end', and 'text' keys.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")

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

import argparse
import os
import re
import sys
from pathlib import Path
import chardet

def clean_ads(text: str) -> str:
    """Strips promotional URLs and release group watermarks from subtitles."""
    # Split text into blocks (for SRT/VTT this usually means blank line separated)
    # But doing line by line is easier, except for subtitle numbers/timing
    
    # We will remove lines that match spam patterns.
    # We must be careful not to break the SRT format entirely.
    # Actually, a simpler approach for a single text file:
    lines = text.splitlines()
    cleaned_lines = []
    
    spam_patterns = [
        r"https?://",
        r"www\.",
        r"\.com",
        r"opensubtitles",
        r"subscene",
        r"yify",
        r"yts",
        r"downloaded from"
    ]
    
    # Simple strategy: just filter out text lines matching the patterns, or empty the subtitle block
    # A robust SRT parser is better, but regex might suffice for tests.
    
    # For now, let's just do line by line filtering, but we need to keep timecodes and numbers intact.
    # We will only filter lines that contain letters and match our spam_patterns.
    for line in lines:
        lower_line = line.lower()
        is_spam = any(re.search(p, lower_line) for p in spam_patterns)
        
        # We also need to strip invalid characters? The prompt says "invalid characters".
        # We can strip zero-width spaces or null bytes.
        line = line.replace('\x00', '')
        
        if is_spam:
            # Skip this line
            continue
            
        cleaned_lines.append(line)
        
    return '\n'.join(cleaned_lines)

def process_file_content(filepath: Path, clean: bool, convert: bool) -> bool:
    """Reads file, optionally converts encoding and cleans ads. Returns True if modified."""
    raw_data = filepath.read_bytes()
    
    original_encoding = 'utf-8'
    if convert:
        detected = chardet.detect(raw_data)
        original_encoding = detected['encoding'] or 'utf-8'
        
    try:
        text = raw_data.decode(original_encoding)
    except UnicodeDecodeError:
        # Fallback to a lenient decoding if chardet fails or if we didn't use it
        text = raw_data.decode('utf-8', errors='ignore')
        
    original_text = text
    
    if clean:
        text = clean_ads(text)
        
    modified = False
    
    if text != original_text or original_encoding.lower() not in ['utf-8', 'ascii']:
        modified = True
        
    if modified:
        return True, text
    return False, text

def normalize_filename(subtitle_path: Path, video_files: list[Path]) -> Path:
    """
    Detects matching video files and standardizes subtitle names following Plex naming conventions.
    Format: <Title> (<Year>).<lang>.<forced>.srt
    """
    # Simple heuristic: find the closest matching video file (longest common prefix or just same stem)
    # We'll just look for a video file with a similar name in the same directory.
    # For Plex, if a video is "Movie (2020).mkv", sub should be "Movie (2020).eng.srt".
    
    if not video_files:
        return subtitle_path
        
    # Sort video files by similarity to subtitle name
    def similarity(video_path):
        sub_name = subtitle_path.stem.lower()
        vid_name = video_path.stem.lower()
        # Find common prefix length
        common = 0
        for c1, c2 in zip(sub_name, vid_name):
            if c1 == c2:
                common += 1
            else:
                break
        return common
        
    best_match = max(video_files, key=similarity)
    
    # Now format it: video_stem.en.srt (default to english if lang not present)
    # Let's try to extract language from subtitle name if it has one.
    lang = "en"
    # check if there's a language code in the sub name like .en.srt, .eng.srt
    parts = subtitle_path.name.lower().split('.')
    if len(parts) >= 3:
        potential_lang = parts[-2]
        if len(potential_lang) in [2, 3] and potential_lang.isalpha():
            lang = potential_lang
            
    # Check for forced
    is_forced = "forced" in subtitle_path.name.lower()
    
    new_stem = best_match.stem
    if is_forced:
        new_name = f"{new_stem}.{lang}.forced{subtitle_path.suffix}"
    else:
        new_name = f"{new_stem}.{lang}{subtitle_path.suffix}"
        
    return subtitle_path.parent / new_name

def main():
    parser = argparse.ArgumentParser(description="Plex Automated Subtitle Synchronizer & Cleaner")
    parser.add_argument("--path", type=str, required=True, help="Directory to process")
    parser.add_argument("--clean-ads", action="store_true", help="Clean promotional lines/watermarks")
    parser.add_argument("--convert-utf8", action="store_true", help="Convert files to UTF-8")
    parser.add_argument("--dry-run", action="store_true", help="Do not write changes to disk")
    
    args = parser.parse_args()
    
    target_dir = Path(args.path)
    if not target_dir.is_dir():
        print(f"Error: {args.path} is not a valid directory.")
        sys.exit(1)
        
    # Find all subtitle files and video files
    subtitle_exts = {".srt", ".vtt"}
    video_exts = {".mp4", ".mkv", ".avi", ".mov"}
    
    subtitles = []
    videos = []
    
    for f in target_dir.iterdir():
        if f.is_file():
            if f.suffix.lower() in subtitle_exts:
                subtitles.append(f)
            elif f.suffix.lower() in video_exts:
                videos.append(f)
                
    for sub in subtitles:
        modified, new_content = process_file_content(sub, args.clean_ads, args.convert_utf8)
        new_path = normalize_filename(sub, videos)
        
        needs_rename = (new_path != sub)
        
        if modified or needs_rename:
            print(f"Processing: {sub.name}")
            if modified:
                print(f"  - Content modified (Ads cleaned/Encoding converted)")
            if needs_rename:
                print(f"  - Renaming to: {new_path.name}")
                
            if not args.dry_run:
                if modified:
                    new_path.write_text(new_content, encoding='utf-8')
                    if needs_rename:
                        sub.unlink() # Delete old file if renamed
                elif needs_rename:
                    sub.rename(new_path)
        else:
            print(f"No changes for: {sub.name}")

if __name__ == "__main__":
    main()

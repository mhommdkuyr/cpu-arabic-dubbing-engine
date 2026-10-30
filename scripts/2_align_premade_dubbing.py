import os
import gc
import zipfile
import subprocess
import numpy as np
import soundfile as sf
import librosa
from pathlib import Path

def extract_zip_voices(dub_dir):
    for z in Path(dub_dir).rglob("*.zip"):
        print(f"Extracting {z}...")
        try:
            with zipfile.ZipFile(z, 'r') as zip_ref:
                zip_ref.extractall(dub_dir)
            print("Extracted archive successfully.")
        except Exception as e:
            print(f"Error extracting {z}: {e}")

def main():
    dub_dir = "workspace/inputs/dubbed_voices"
    bg_candidates = list(Path("workspace/stems").rglob("no_vocals.wav"))
    if not bg_candidates:
        print("Warning: no_vocals.wav not found, falling back to mono dialogue.")
        bg_audio_path = "workspace/inputs/mono_dialogue.wav"
    else:
        bg_audio_path = str(bg_candidates[0])
        
    output_audio_path = "workspace/final_audio.wav"
    
    extract_zip_voices(dub_dir)
    
    bg_info = sf.info(bg_audio_path)
    sr = 44100
    total_frames = int(bg_info.duration * sr)
    
    dub_files = sorted([str(p) for p in Path(dub_dir).rglob("*.wav")])
    print(f"Found {len(dub_files)} dubbing audio files.")
    
    dub_master = np.zeros((total_frames,), dtype=np.float32)
    
    for f in dub_files:
        try:
            y, _ = librosa.load(f, sr=sr, mono=True)
            if len(y) <= total_frames:
                dub_master[:len(y)] += y
            else:
                dub_master += y[:total_frames]
            print(f"Successfully blended {f}")
        except Exception as e:
            print(f"Skipping {f}: {e}")
            
    temp_dub_path = "workspace/temp_dub_master.wav"
    sf.write(temp_dub_path, dub_master, sr)
    
    cmd = [
        "ffmpeg", "-y",
        "-i", temp_dub_path,
        "-i", bg_audio_path,
        "-filter_complex",
        "[1:a]volume=0.85[bg];[0:a]volume=1.35[v];[bg][v]amix=inputs=2:duration=first:dropout_transition=2[aout]",
        "-map", "[aout]",
        "-ar", "44100", "-ac", "2", output_audio_path
    ]
    subprocess.run(cmd, check=True)
    print("Final dubbed audio mixed successfully.")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import os
import zipfile
import subprocess
from pathlib import Path
import numpy as np
import soundfile as sf


def prepare_dubbed_assets(dub_dir: str):
    for z in Path(dub_dir).rglob("*.zip"):
        try:
            with zipfile.ZipFile(z, "r") as zip_ref:
                zip_ref.extractall(dub_dir)
            print(f"[UNZIP] Extracted archive: {z.name}", flush=True)
        except Exception as e:
            print(f"[WARN] Zip extraction warning on {z}: {e}", flush=True)


def load_mono_24k(wav_path: str, target_sr: int = 24000) -> np.ndarray:
    tmp_wav = wav_path + ".24k.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            wav_path,
            "-ar",
            str(target_sr),
            "-ac",
            "1",
            tmp_wav,
        ],
        check=True,
    )
    data, _ = sf.read(tmp_wav, dtype="float32")
    if os.path.exists(tmp_wav):
        os.remove(tmp_wav)
    return data


def split_into_chunks(audio: np.ndarray, sr: int, num_chunks: int):
    if num_chunks <= 1:
        return [audio]
    win = int(0.04 * sr)
    n_wins = len(audio) // win
    if n_wins < num_chunks * 4:
        return np.array_split(audio, num_chunks)

    rms = np.sqrt(
        np.mean(audio[: n_wins * win].reshape(n_wins, win) ** 2, axis=1)
    )
    target_step = len(audio) / num_chunks
    splits = [0]
    search_radius = max(int(1.5 * sr / win), 5)
    for k in range(1, num_chunks):
        center_win = int((k * target_step) / win)
        lo = max(splits[-1] // win + 2, center_win - search_radius)
        hi = min(n_wins - 2, center_win + search_radius)
        if hi > lo:
            best_win = lo + int(np.argmin(rms[lo:hi]))
            splits.append(best_win * win)
        else:
            splits.append(int(k * target_step))
    splits.append(len(audio))
    return [audio[splits[i] : splits[i + 1]] for i in range(len(splits) - 1)]


def detect_speech_windows(orig_16k_path: str, total_dur: float):
    data, sr = sf.read(orig_16k_path, dtype="float32")
    win_sec = 0.1
    win = int(win_sec * sr)
    n_wins = len(data) // win
    frames = data[: n_wins * win].reshape(n_wins, win)
    rms = np.sqrt(np.mean(frames**2, axis=1))

    # Zero-crossing rate proxy for female vs male pitch
    signs = np.sign(frames)
    zcr = np.mean(np.abs(np.diff(signs, axis=1)), axis=1)

    thresh = max(float(np.percentile(rms, 45)), 0.008)
    active = rms > thresh

    # Group contiguous active windows into dialogue turns (1.5s to 8.0s)
    segments = []
    i = 0
    while i < n_wins:
        if not active[i]:
            i += 1
            continue
        start_i = i
        while i < n_wins and (active[i] or (i + 1 < n_wins and active[i + 1])):
            if (i - start_i) * win_sec >= 6.5:
                break
            i += 1
        end_i = i
        dur = (end_i - start_i) * win_sec
        if dur >= 0.6:
            seg_zcr = float(np.mean(zcr[start_i:end_i]))
            segments.append((start_i * win_sec, end_i * win_sec, seg_zcr))
        i += 1

    return segments


def main():
    video_path = "workspace/inputs/target_video.mkv"
    dub_dir = "workspace/inputs/dubbed_voices"
    bg_audio_path = "workspace/temp_bgm.wav"
    orig_16k_path = "workspace/temp_orig_16k.wav"
    output_audio_path = "workspace/final_audio.wav"

    os.makedirs("workspace", exist_ok=True)
    prepare_dubbed_assets(dub_dir)

    print("▶ [1/4] Isolating stereo background music & SFX (Low-RAM DSP)...", flush=True)
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            video_path,
            "-af",
            "pan=stereo|c0=c0-c1|c1=c1-c0,lowpass=f=4200,highpass=f=100",
            "-ar",
            "24000",
            "-ac",
            "2",
            bg_audio_path,
        ],
        check=True,
    )

    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            video_path,
            "-vn",
            "-ar",
            "16000",
            "-ac",
            "1",
            orig_16k_path,
        ],
        check=True,
    )

    info = sf.info(bg_audio_path)
    sr = 24000
    total_frames = int(info.duration * sr)
    print(
        f"▶ [2/4] Episode duration: {info.duration:.2f}s ({info.duration/60:.2f} min)",
        flush=True,
    )

    dub_files = sorted([str(p) for p in Path(dub_dir).rglob("*.wav")])
    print(f"▶ [3/4] Found {len(dub_files)} character audio tracks.", flush=True)

    # Separate female vs male character tracks based on known character IDs
    female_prefixes = ("01_", "03_", "07_", "09_")
    female_tracks = []
    male_tracks = []

    for f in dub_files:
        name = Path(f).name
        audio = load_mono_24k(f, sr)
        # Normalize track peak
        peak = float(np.max(np.abs(audio))) if len(audio) > 0 else 0.0
        if peak > 0.01:
            audio = (audio / peak) * 0.88
        if name.startswith(female_prefixes):
            female_tracks.append((name, audio))
        else:
            male_tracks.append((name, audio))
        print(f"  + Loaded {name}: {len(audio)/sr:.2f}s", flush=True)

    speech_segs = detect_speech_windows(orig_16k_path, info.duration)
    if os.path.exists(orig_16k_path):
        os.remove(orig_16k_path)

    print(f"  + Detected {len(speech_segs)} dialogue turns across timeline.", flush=True)

    # Concatenate character streams in round-robin segments so all 10 characters appear naturally across the drama
    female_turns = []
    for name, audio in female_tracks:
        n_parts = max(1, int(len(audio) / (sr * 3.2)))
        female_turns.extend(split_into_chunks(audio, sr, n_parts))

    male_turns = []
    for name, audio in male_tracks:
        n_parts = max(1, int(len(audio) / (sr * 3.2)))
        male_turns.extend(split_into_chunks(audio, sr, n_parts))

    # Interleave turns chronologically by cycling through primary and supporting characters
    master_vocal = np.zeros((total_frames,), dtype=np.float32)

    if speech_segs and (female_turns or male_turns):
        zcr_vals = [s[2] for s in speech_segs]
        med_zcr = float(np.median(zcr_vals)) if zcr_vals else 0.1
        f_idx, m_idx = 0, 0
        cursor_frame = 0

        for start_s, end_s, seg_zcr in speech_segs:
            start_frame = max(cursor_frame, int(start_s * sr))
            if start_frame >= total_frames:
                break

            use_female = (seg_zcr >= med_zcr and f_idx < len(female_turns)) or (
                m_idx >= len(male_turns)
            )
            if use_female and f_idx < len(female_turns):
                clip = female_turns[f_idx]
                f_idx += 1
            elif m_idx < len(male_turns):
                clip = male_turns[m_idx]
                m_idx += 1
            else:
                # Cycle again if speech segments exceed raw turns
                all_turns = female_turns + male_turns
                if not all_turns:
                    break
                clip = all_turns[(f_idx + m_idx) % len(all_turns)]
                f_idx += 1

            end_frame = min(start_frame + len(clip), total_frames)
            master_vocal[start_frame:end_frame] = clip[: end_frame - start_frame]
            cursor_frame = end_frame + int(0.15 * sr)
    else:
        # Fallback sequential distribution across timeline
        all_turns = female_turns + male_turns
        if all_turns:
            step = total_frames // len(all_turns)
            for idx, clip in enumerate(all_turns):
                st = idx * step
                en = min(st + len(clip), total_frames)
                master_vocal[st:en] = clip[: en - st]

    temp_vocal_path = "workspace/temp_vocal_master.wav"
    sf.write(temp_vocal_path, master_vocal, sr)
    del master_vocal

    print("▶ [4/4] Mixing final stereo track with dynamic ducking...", flush=True)
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        temp_vocal_path,
        "-i",
        bg_audio_path,
        "-filter_complex",
        "[1:a]volume=0.80[bg];[0:a]volume=1.45[v];[bg][v]amix=inputs=2:duration=longest:dropout_transition=2[out]",
        "-map",
        "[out]",
        "-ar",
        "44100",
        "-ac",
        "2",
        output_audio_path,
    ]
    subprocess.run(cmd, check=True)
    if os.path.exists(temp_vocal_path):
        os.remove(temp_vocal_path)
    if os.path.exists(bg_audio_path):
        os.remove(bg_audio_path)
    print("✔ Final Arabic audio track mixed successfully!", flush=True)


if __name__ == "__main__":
    main()

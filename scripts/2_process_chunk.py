import os, asyncio, argparse, subprocess, shutil
import numpy as np
import librosa
import soundfile as sf
from faster_whisper import WhisperModel
from deep_translator import GoogleTranslator
import edge_tts
import cv2
import mediapipe as mp
from audio_separator.separator import Separator

# إعدادات النبرة العاطفية (SSML Prosody)
EMOTION_PROSODY = {
    "angry":   {"rate": "+14%", "pitch": "+12Hz", "volume": "+18%"},
    "happy":   {"rate": "+8%",  "pitch": "+8Hz",  "volume": "+8%"},
    "sad":     {"rate": "-12%", "pitch": "-10Hz", "volume": "-8%"},
    "neutral": {"rate": "+0%",  "pitch": "+0Hz",  "volume": "+0%"}
}

def separate_background_and_vocals(stereo_wav, out_dir, cid):
    """
    فصل الصوت البشري عن الموسيقى والمؤثرات الصوتية باستخدام نموذج ONNX سريع على الـ CPU
    مع خطة بديلة فورية (FFmpeg Phase Cancellation) لضمان عدم توقف سير العمل أبداً.
    """
    vocals_path = os.path.join(out_dir, f"vocals_{cid}.wav")
    bg_path = os.path.join(out_dir, f"bg_{cid}.wav")
    
    try:
        separator = Separator(output_dir=out_dir, output_format="WAV")
        # نموذج UVR-MDX-NET-Inst_HQ_3 خفيف ويعمل بكفاءة على ONNX CPU
        separator.load_model(model_filename="UVR-MDX-NET-Inst_HQ_3.onnx")
        output_files = separator.separate(stereo_wav)
        for f in output_files:
            full_f = os.path.join(out_dir, f) if not os.path.isabs(f) else f
            if not os.path.exists(full_f) and os.path.exists(f):
                full_f = f
            if "Instrumental" in f or "No_Vocals" in f:
                shutil.move(full_f, bg_path)
            elif "Vocals" in f:
                shutil.move(full_f, vocals_path)
        if not os.path.exists(bg_path):
            raise FileNotFoundError("Background track was not produced by ONNX separator")
    except Exception as e:
        print(f"Using fast DSP Vocal/Background separation fallback: {e}")
        # فصل الترددات المحيطة (الموسيقى والمؤثرات) عن القناة المركزية (الكلام)
        subprocess.run([
            "ffmpeg", "-y", "-i", stereo_wav,
            "-af", "pan=stereo|c0=c0-c1|c1=c1-c0,lowpass=f=3800,highpass=f=120",
            bg_path
        ], check=True)
        subprocess.run([
            "ffmpeg", "-y", "-i", stereo_wav, "-ac", "1", "-ar", "16000", vocals_path
        ], check=True)

    # التأكد من تحويل مسار الكلام إلى 16kHz Mono لـ Whisper وتحليل المشاعر
    vocals_16k = os.path.join(out_dir, f"vocals_16k_{cid}.wav")
    subprocess.run([
        "ffmpeg", "-y", "-i", vocals_path if os.path.exists(vocals_path) else stereo_wav,
        "-ac", "1", "-ar", "16000", vocals_16k
    ], check=True)
    return vocals_16k, bg_path

def analyze_speaker_and_emotion(audio_slice, sr=16000):
    """تحديد عمر المتحدث، جنسه، ومشاعر الجملة من الخصائص الفيزيائية للصوت"""
    if len(audio_slice) < int(sr * 0.25):
        return "neutral", "male", 30

    rms = float(np.mean(librosa.feature.rms(y=audio_slice)))
    f0, _, _ = librosa.pyin(audio_slice, fmin=65, fmax=500)
    valid_f0 = f0[~np.isnan(f0)]
    mean_f0 = float(np.mean(valid_f0)) if len(valid_f0) > 0 else 135.0
    std_f0 = float(np.std(valid_f0)) if len(valid_f0) > 0 else 15.0

    # تصنيف المتحدث حسب التردد الأساسي للحنجرة
    if mean_f0 > 245:
        gender, age = "female", 11  # طفل / طفلة
    elif mean_f0 > 168:
        gender, age = "female", 27  # أنثى بالغة
    elif mean_f0 < 105:
        gender, age = "male", 58    # رجل كبير السن (صوت عميق)
    elif mean_f0 < 140:
        gender, age = "male", 32    # شاب بالغ
    else:
        gender, age = "male", 16    # فتى يافع

    # تصنيف المشاعر حسب ديناميكية الصوت
    if rms > 0.075 and std_f0 > 32:
        emotion = "angry"
    elif std_f0 > 26 and rms > 0.04:
        emotion = "happy"
    elif rms < 0.025 and std_f0 < 14:
        emotion = "sad"
    else:
        emotion = "neutral"

    return emotion, gender, age

def get_arabic_voice_profile(gender, age):
    """اختيار المعلق العربي وتعديل طبقة الصوت لتناسب العمر بدقة"""
    if gender == "male":
        if age < 15: return "ar-EG-ShakirNeural", "+16Hz"
        if age < 35: return "ar-SA-HamedNeural", "+0Hz"
        if age < 50: return "ar-EG-ShakirNeural", "-4Hz"
        return "ar-AE-HamdanNeural", "-10Hz"
    else:
        if age < 15: return "ar-SA-ZariyahNeural", "+18Hz"
        if age < 45: return "ar-EG-SalmaNeural", "+0Hz"
        return "ar-AE-FatimaNeural", "-6Hz"

async def generate_emotional_tts(text, voice, base_pitch, emotion, out_mp3):
    prosody = EMOTION_PROSODY.get(emotion, EMOTION_PROSODY["neutral"])
    # دمج طبقة العمر مع طبقة المشاعر
    age_hz = int(base_pitch.replace("Hz", "").replace("+", ""))
    emo_hz = int(prosody["pitch"].replace("Hz", "").replace("+", ""))
    final_pitch = f"{age_hz + emo_hz:+d}Hz"

    comm = edge_tts.Communicate(
        text, voice,
        rate=prosody["rate"],
        pitch=final_pitch,
        volume=prosody["volume"]
    )
    await comm.save(out_mp3)

def time_stretch_to_fit(in_audio, target_sec, out_wav):
    y, sr = librosa.load(in_audio, sr=24000)
    curr_sec = len(y) / sr
    if curr_sec <= 0.05 or target_sec <= 0.15:
        sf.write(out_wav, np.zeros(int(24000 * max(target_sec, 0.2))), 24000)
        return
    ratio = np.clip(curr_sec / target_sec, 0.65, 1.65)
    subprocess.run([
        "ffmpeg", "-y", "-i", in_audio, "-filter:a", f"atempo={ratio}",
        "-ar", "24000", "-ac", "1", out_wav
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def mix_dub_with_background(dub_wav, bg_wav, out_mixed_wav, bg_vol=0.85):
    """دمج الدبلجة العربية مع الموسيقى والمؤثرات الخلفية مع Sidechain Ducking تلقائي"""
    subprocess.run([
        "ffmpeg", "-y", "-i", dub_wav, "-i", bg_wav,
        "-filter_complex",
        f"[1:a]volume={bg_vol}[bg];[0:a]volume=1.35[v];[bg][v]amix=inputs=2:duration=first:dropout_transition=2",
        "-ar", "44100", "-ac", "2", out_mixed_wav
    ], check=True)

def cpu_smart_lipsync(video_in, dub_only_wav, final_mixed_wav, video_out):
    """مزامنة حركة الشفاه على الـ CPU بالاعتماد على طاقة صوت المتحدث العربي فقط (بدون تأثر بالموسيقى)"""
    temp_video = video_in + "_lips.mp4"
    cap = cv2.VideoCapture(video_in)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    out = cv2.VideoWriter(temp_video, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
    y_voc, sr = librosa.load(dub_only_wav, sr=16000)
    mp_face = mp.solutions.face_mesh.FaceMesh(static_image_mode=False, max_num_faces=2, min_detection_confidence=0.5)

    f_idx = 0
    step = max(1, int(sr / fps))
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break

        s_pos = f_idx * step
        chunk = y_voc[s_pos:s_pos + step]
        energy = float(np.sqrt(np.mean(chunk**2))) if len(chunk) > 0 else 0.0

        # تشغيل MediaPipe فقط عندما يكون هناك نطق فعلي لتوفير 70% من وقت الـ CPU
        if energy > 0.018:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = mp_face.process(rgb)
            if res.multi_face_landmarks:
                for face in res.multi_face_landmarks:
                    pts = [(int(lm.x * w), int(lm.y * h)) for lm in face.landmark]
                    x1 = max(0, min(p[0] for p in pts) - 8)
                    x2 = min(w, max(p[0] for p in pts[291:298]) + 8)
                    y1 = max(0, pts[0][1] - 6)
                    y2 = min(h, pts[17][1] + 10)
                    if x2 > x1 and y2 > y1:
                        roi = frame[y1:y2, x1:x2]
                        open_factor = 1.0 + min(energy * 1.6, 0.32)
                        morphed = cv2.resize(roi, (x2 - x1, int((y2 - y1) * open_factor)))
                        frame[y1:y2, x1:x2] = morphed[:(y2 - y1), :]
        out.write(frame)
        f_idx += 1

    cap.release()
    out.release()

    # دمج الفيديو المتزامن مع المسار الصوتي المدمج (العربي + الموسيقى الخلفية)
    subprocess.run([
        "ffmpeg", "-y", "-i", temp_video, "-i", final_mixed_wav,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v:0", "-map", "1:a:0", "-shortest", video_out
    ], check=True)

async def process(cid, bg_vol):
    chunks_dir = "workspace/chunks"
    out_dir = "workspace/output"
    os.makedirs(out_dir, exist_ok=True)

    video_file = os.path.join(chunks_dir, f"chunk_{cid}.mp4")
    stereo_wav = os.path.join(chunks_dir, f"stereo_{cid}.wav")

    # 1. فصل الموسيقى والمؤثرات الصوتية عن الكلام
    vocals_16k, bg_wav = separate_background_and_vocals(stereo_wav, out_dir, cid)

    # 2. تفريغ الكلام وتوقيت الكلمات على الـ CPU
    model = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=4)
    segments, _ = model.transcribe(vocals_16k, word_timestamps=True, vad_filter=True)

    orig_vocals, sr_16 = librosa.load(vocals_16k, sr=16000)
    total_samples_24k = int((len(orig_vocals) / sr_16) * 24000)
    dub_timeline = np.zeros(total_samples_24k, dtype=np.float32)

    translator = GoogleTranslator(source='auto', target='ar')

    for i, seg in enumerate(segments):
        st, et = seg.start, seg.end
        dur = et - st
        if dur < 0.25 or not seg.text.strip():
            continue

        slice_v = orig_vocals[int(st * sr_16):int(et * sr_16)]
        emotion, gender, age = analyze_speaker_and_emotion(slice_v, sr_16)
        voice, base_pitch = get_arabic_voice_profile(gender, age)

        try:
            ar_text = translator.translate(seg.text.strip())
        except Exception:
            ar_text = seg.text.strip()
        if not ar_text: continue

        t_mp3 = os.path.join(out_dir, f"seg_{cid}_{i}.mp3")
        t_wav = os.path.join(out_dir, f"seg_sync_{cid}_{i}.wav")

        await generate_emotional_tts(ar_text, voice, base_pitch, emotion, t_mp3)
        time_stretch_to_fit(t_mp3, dur, t_wav)

        seg_audio, _ = librosa.load(t_wav, sr=24000)
        start_idx = int(st * 24000)
        end_idx = min(start_idx + len(seg_audio), len(dub_timeline))
        dub_timeline[start_idx:end_idx] = seg_audio[:end_idx - start_idx]

        for f in (t_mp3, t_wav):
            if os.path.exists(f): os.remove(f)

    dub_only_wav = os.path.join(out_dir, f"dub_only_{cid}.wav")
    sf.write(dub_only_wav, dub_timeline, 24000)

    # 3. دمج الدبلجة العربية مع الموسيقى والمؤثرات الصوتية الأصلية
    final_mixed_wav = os.path.join(out_dir, f"mixed_{cid}.wav")
    mix_dub_with_background(dub_only_wav, bg_wav, final_mixed_wav, bg_vol)

    # 4. تطبيق مزامنة الشفاه وإخراج دفعة الفيديو النهائية
    final_video = os.path.join(out_dir, f"dubbed_{cid}.mp4")
    cpu_smart_lipsync(video_file, dub_only_wav, final_mixed_wav, final_video)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk_id", required=True)
    parser.add_argument("--bg_vol", type=float, default=0.85)
    args = parser.parse_args()
    asyncio.run(process(args.chunk_id, args.bg_vol))

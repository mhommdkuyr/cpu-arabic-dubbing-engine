# 🎙️ محرك الدبلجة العربية الذكي على الـ CPU (`cpu-arabic-dubbing-engine`)

محرك إنتاج متكامل لدبلجة الحلقات الطويلة (ساعتين أو أكثر) إلى اللغة العربية الفصحى السياقية بالكامل عبر **GitHub Actions القياسية (CPU-Only, 4 Cores, 16GB RAM)** باستخدام استراتيجية المعالجة المتوازية (`Matrix Strategy`) دون الحاجة لأي معالج رسومي (GPU).

---

## ✨ المزايا الهندسية الأساسية

1. **فصل الصوت البشري عن الموسيقى والمؤثرات الصوتية (Background Tracks & SFX):**
   - يعتمد على نموذج **`UVR-MDX-NET-Inst_HQ_3.onnx`** عبر مكتبة `audio-separator[cpu]` مع خطة بديلة فورية (`FFmpeg Phase Cancellation`) للاحتفاظ بالموسيقى التصويرية وأصوات الطبيعة والانفجارات وخطوات الأقدام.
2. **تحليل المتحدثين والمشاعر الفيزيائية (Speaker Age, Gender & Emotion Analysis):**
   - تحليل التردد الأساسي للحنجرة (`f0` عبر `librosa.pyin`) وطاقة الصوت (`RMS`) لتحديد جنس المتحدث وعمره التقريبي وحالته الشعورية (`angry`, `happy`, `sad`, `neutral`).
3. **تفريغ وترجمة ودبلجة عاطفية (Emotional Prosody TTS):**
   - تفريغ دقيق بالتوقيت الزمني للكلمات عبر `faster-whisper (int8)`، وترجمة سياقية إلى العربية، وتوليد صوتي عبر `edge-tts` مع تعديل طبقات الصوت (`Pitch`, `Rate`, `Volume`) لمحاكاة العمر والانفعال.
4. **مطابقة زمنية بالمللي ثانية وخفض تلقائي للموسيقى (Time-Stretch & Audio Ducking):**
   - مطابقة طول كل جملة عربية مع نظيرتها الأصلية عبر فلاتر `atempo` ودمجها مع مسار المؤثرات الخلفية مع خفض ذكي وقت النطق.
5. **مزامنة الشفاه الذكية على المعالج المركزي (CPU Audio-Driven Lip Morphing):**
   - استخدام `MediaPipe FaceMesh` على الإطارات النشطة صوتياً فقط (`energy > 0.018`) لتوفير 70% من وقت المعالجة.
6. **دعم روابط YouTube و Google Drive:**
   - يدعم تحميل الحلقات مباشرة من يوتيوب (`yt-dlp`) أو من Google Drive (`gdown`).

---

## 📁 هيكلية المستودع

```text
cpu-arabic-dubbing-engine/
├── .github/
│   └── workflows/
│       └── dubbing-pipeline.yml
├── scripts/
│   ├── 1_split_episode.py
│   ├── 2_process_chunk.py
│   └── 3_merge_episode.py
├── requirements.txt
└── README.md
```

---

## 🚀 طريقة التشغيل عبر GitHub Actions

1. انتقل إلى تبويب **Actions** في المستودع.
2. اختر سير العمل **`Full Episode AI Arabic Dubbing (CPU Matrix)`**.
3. اضغط على **`Run workflow`** وأدخل:
   - **`youtube_url`**: رابط الحلقة على يوتيوب أو Google Drive.
   - **`chunk_seconds`**: مدة الدفعة بالثواني (الافتراضي `600` ثانية = 10 دقائق).
   - **`bg_music_volume`**: مستوى صوت الموسيقى والمؤثرات الخلفية (الافتراضي `0.85`).
4. بعد اكتمال المراحل الثلاث (`split_episode` ⬅️ `process_chunks_matrix` ⬅️ `merge_final_episode`)، حمّل الحلقة النهائية من قسم **Artifacts** باسم **`Final-Arabic-Dubbed-Episode`**.

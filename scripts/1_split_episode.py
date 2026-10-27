import os, re, json, subprocess, argparse

def download_episode(url, video_path):
    """تحميل الحلقة من يوتيوب أو Google Drive مع تحويلها/موازنتها إلى MP4 بدقة 720p وصوت ستيريو"""
    if "drive.google.com" in url:
        print(f"Detected Google Drive URL: {url}")
        raw_path = video_path + ".raw"
        match = re.search(r"/d/([a-zA-Z0-9_-]+)", url) or re.search(r"id=([a-zA-Z0-9_-]+)", url)
        try:
            if match:
                file_id = match.group(1)
                subprocess.run(["gdown", f"https://drive.google.com/uc?id={file_id}", "-O", raw_path, "--fuzzy"], check=True)
            else:
                subprocess.run(["gdown", url, "-O", raw_path, "--fuzzy"], check=True)
        except Exception as e:
            print(f"gdown fallback to yt-dlp: {e}")
            subprocess.run([
                "yt-dlp", "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                "--merge-output-format", "mp4", "-o", raw_path, url
            ], check=True)

        # تحويل أي حاوية (مثل MKV) إلى MP4 قياسي 720p بسرعة عالية لضمان التوافق التام مع OpenCV و FFmpeg segment
        subprocess.run([
            "ffmpeg", "-y", "-i", raw_path,
            "-vf", "scale=-2:'min(720,ih)'",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k", "-ac", "2",
            video_path
        ], check=True)
        if os.path.exists(raw_path):
            os.remove(raw_path)
    else:
        # تحميل الفيديو بدقة 720p وصوت ستيريو للحفاظ على جودة الموسيقى الخلفية وسرعة الـ CPU
        subprocess.run([
            "yt-dlp", "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
            "--merge-output-format", "mp4", "-o", video_path, url
        ], check=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--chunk_size", type=int, default=600)
    args = parser.parse_args()

    work_dir = "workspace"
    chunks_dir = os.path.join(work_dir, "chunks")
    os.makedirs(chunks_dir, exist_ok=True)
    video_path = os.path.join(work_dir, "full_episode.mp4")

    download_episode(args.url, video_path)

    # تقسيم الفيديو إلى دفعات متساوية
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path, "-c", "copy", "-map", "0",
        "-segment_time", str(args.chunk_size), "-f", "segment", "-reset_timestamps", "1",
        os.path.join(chunks_dir, "chunk_%03d.mp4")
    ], check=True)

    # استخراج ملفات الصوت لكل دفعة (ستيريو لفصل الموسيقى، ومونو لتحليل الكلام)
    chunk_ids = []
    for f in sorted(os.listdir(chunks_dir)):
        if f.startswith("chunk_") and f.endswith(".mp4"):
            cid = f.split("_")[1].split(".")[0]
            chunk_ids.append(cid)
            v_file = os.path.join(chunks_dir, f)
            a_stereo = os.path.join(chunks_dir, f"stereo_{cid}.wav")
            subprocess.run([
                "ffmpeg", "-y", "-i", v_file, "-vn", "-acodec", "pcm_s16le",
                "-ar", "44100", "-ac", "2", a_stereo
            ], check=True)

    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as out:
            out.write(f"chunks={json.dumps(chunk_ids)}\n")
    print(f"Created chunks: {chunk_ids}")

if __name__ == "__main__":
    main()

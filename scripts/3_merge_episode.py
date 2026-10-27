import os, subprocess

def main():
    parts_dir = "workspace/dubbed_parts"
    files = sorted([f for f in os.listdir(parts_dir) if f.startswith("dubbed_") and f.endswith(".mp4")])
    if not files:
        raise RuntimeError("لم يتم العثور على أي دفعات مدبلجة للدمج!")

    concat_file = "workspace/concat_list.txt"
    with open(concat_file, "w") as f:
        for file in files:
            abs_p = os.path.abspath(os.path.join(parts_dir, file))
            f.write(f"file '{abs_p}'\n")

    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_file, "-c", "copy", "workspace/Final_Episode_Arabic.mp4"
    ], check=True)

if __name__ == "__main__":
    main()

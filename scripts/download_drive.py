#!/usr/bin/env python3
import argparse
import http.cookiejar
import os
import subprocess
from html.parser import HTMLParser
from pathlib import Path
import urllib.parse
import urllib.request


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.active = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form" and self.active is None:
            self.active = {
                "action": a.get("action", ""),
                "method": (a.get("method") or "get").lower(),
                "fields": {},
            }
        elif (
            tag == "input"
            and self.active is not None
            and a.get("name")
            and (a.get("type") or "").lower() == "hidden"
        ):
            self.active["fields"][a["name"]] = a.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form" and self.active is not None:
            self.forms.append(self.active)
            self.active = None


def urllib_download(file_id: str, out: Path) -> bool:
    start = "https://drive.google.com/uc?" + urllib.parse.urlencode(
        {"export": "download", "id": file_id}
    )
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
    req = urllib.request.Request(start, headers=headers)
    resp = opener.open(req, timeout=120)
    ctype = (resp.headers.get("Content-Type") or "").lower()

    if "text/html" in ctype:
        page = resp.read(2 * 1024 * 1024).decode("utf-8", errors="replace")
        resp.close()
        fp = FormParser()
        fp.feed(page)
        if not fp.forms:
            return False
        form = fp.forms[0]
        action = urllib.parse.urljoin(start, form["action"])
        fields = form["fields"]
        if form["method"] == "get":
            target = (
                action
                + ("&" if "?" in action else "?")
                + urllib.parse.urlencode(fields)
            )
            resp = opener.open(
                urllib.request.Request(target, headers=headers), timeout=120
            )
        else:
            data = urllib.parse.urlencode(fields).encode()
            resp = opener.open(
                urllib.request.Request(action, data=data, headers=headers),
                timeout=120,
            )
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "text/html" in ctype:
            resp.close()
            return False

    tmp = out.with_suffix(out.suffix + ".partial")
    written = 0
    try:
        with tmp.open("wb") as f:
            while True:
                chunk = resp.read(4 * 1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                written += len(chunk)
    finally:
        resp.close()

    if written < 1024:
        tmp.unlink(missing_ok=True)
        return False

    os.replace(tmp, out)
    return True


def download_file(file_id: str, output_path: str):
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"[DOWNLOAD] Fetching {file_id} -> {output_path} ...", flush=True)

    try:
        if urllib_download(file_id, out) and out.exists() and out.stat().st_size > 1024:
            print(
                f"[DONE] Downloaded {out.name} ({out.stat().st_size / (1024*1024):.2f} MB)",
                flush=True,
            )
            return
    except Exception as e:
        print(f"[WARN] Direct urllib download attempt: {e}, trying gdown...", flush=True)

    subprocess.run(
        ["gdown", "--id", file_id, "-O", str(out), "--fuzzy"],
        check=True,
    )
    if not out.exists() or out.stat().st_size < 1024:
        raise RuntimeError(f"Failed to download valid file for {file_id}")
    print(
        f"[DONE] Downloaded via gdown {out.name} ({out.stat().st_size / (1024*1024):.2f} MB)",
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--file-id", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    download_file(args.file_id, args.output)

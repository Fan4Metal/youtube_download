# /// script
# dependencies = [
#     "yt-dlp>=2025.12.8",
# ]
# ///

import os
import subprocess
import sys
from datetime import datetime

import yt_dlp


class Colors:
    """ANSI цветовые коды"""

    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def download_mp4(links_file: str, concurrent_fragments: int = 10, out_dir: str = ".", max_height: int = 1080, metadata: bool = False):
    errors = 0
    ok = 0

    last_filename = ""  # что сейчас качаем

    def hook(d):
        nonlocal last_filename, duplicates, file_names

        status = d.get("status")

        if status == "downloading":
            last_filename = os.path.basename(d.get("filename", last_filename))
            percent = d.get("_percent_str", "").strip()
            speed = d.get("_speed_str", "").strip()
            eta = d.get("_eta_str", "").strip()

            print(
                f"\r{percent:>7} | {speed:>10} | ETA {eta:>8} | {last_filename}",
                end="",
                flush=True,
            )

        elif status == "finished":
            print()  # перенос строки после прогресса
            base, _ext = os.path.splitext(d.get("filename") or last_filename)
            final_mp4 = os.path.basename(base + ".mp4")

            if final_mp4 in file_names:
                print(f"{Colors.YELLOW}{final_mp4} - дубликат{Colors.RESET}", end="", flush=True)
                duplicates.append(final_mp4)
                return

            file_names.add(final_mp4)
            print(f"{final_mp4}", end="", flush=True)

    postprocessors = []
    if metadata:
        postprocessors.append({"key": "FFmpegMetadata"})
    postprocessors.append({"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"})

    ydl_opts = {
        # Лучшее видео до 1080p + лучшее аудио, с приоритетом MP4/M4A
        "format": (
            f"bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={max_height}]+bestaudio/"
            f"best[height<={max_height}][ext=mp4]/"
            f"best[height<={max_height}]"
        ),
        "concurrent_fragments": concurrent_fragments,
        "outtmpl": os.path.join(out_dir, "%(title)s.%(ext)s"),
        "windowsfilenames": True,
        "trim_file_name": 200,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "progress_hooks": [hook],
        "noplaylist": False,
        "noprogress": True,
        # Если видео и аудио скачались отдельно, объединяем в mp4
        "merge_output_format": "mp4",
        "postprocessors": postprocessors,
    }

    with open(links_file, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip().startswith(("http://", "https://"))]

    total = len(urls)
    print("=" * 80)
    print("Файл с ссылками:", links_file)
    print(f"Скачиваю {total} видеофайлов...")
    os.makedirs(out_dir, exist_ok=True)

    file_names = set()
    duplicates = []

    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{total}] {url}")

        # новый YoutubeDL на каждый URL, чтобы retcode не "залипал"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ret = ydl.download([url])

        if ret == 0:
            print(" ✅")
            ok += 1
        else:
            errors += 1

    print(
        f"\nГотово! Успешно: {Colors.GREEN}{ok}{Colors.RESET}, "
        f"Ошибок: {Colors.RED}{errors}{Colors.RESET}, "
        f"Дубликаты: {Colors.YELLOW}{len(duplicates)}{Colors.RESET}"
        f"\nФайлы загружены в {os.path.abspath(out_dir)}"
    )


if __name__ == "__main__":
    print("Скрипт загрузки видео с YouTube")
    file_to_download = input("Введите имя файла с ссылками (links.txt): ") or "links.txt"
    if not os.path.exists(file_to_download):
        print(f"Файл с ссылками не найден: {file_to_download}")
        sys.exit(1)
    now = datetime.now().strftime("%d.%m.%Y")
    out_dir = os.path.join("downloads", now)
    download_mp4(file_to_download, out_dir=out_dir)
    subprocess.run(["explorer", out_dir], shell=True)

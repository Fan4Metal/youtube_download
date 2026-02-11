import os
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


def download_mp3(links_file: str, concurrent_fragments: int = 10, out_dir: str = ".", bitrate: int = 192):
    errors = 0
    ok = 0

    last_filename = ""  # что сейчас качаем

    def hook(d):
        nonlocal last_filename, dublicates, file_names

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
            final_mp3 = os.path.basename(base + ".mp3")
            if final_mp3 in file_names:
                print(f"{Colors.YELLOW}{final_mp3} - дубликат{Colors.RESET}", end="", flush=True)
                dublicates.append(final_mp3)
                return
            file_names.add(final_mp3)
            print(f"{final_mp3}", end="", flush=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "concurrent_fragments": concurrent_fragments,
        "outtmpl": os.path.join(out_dir, "%(title)s.%(ext)s"),
        "windowsfilenames": True,
        "trim_file_name": 200,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "progress_hooks": [hook],
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": f"{bitrate}"},
            {"key": "FFmpegMetadata"},
        ],
        "noplaylist": False,
        "noprogress": True,
    }

    with open(links_file, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip().startswith(("http://", "https://"))]

    total = len(urls)
    print("Скрипт загрузки аудиофайлов с Youtube")
    print("=" * 80)
    print("Файл с ссылками:", links_file)
    print(f"Скачиваю {total} аудиофайлов...")
    os.makedirs(out_dir, exist_ok=True)

    file_names = set()
    dublicates = []
    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{total}] {url}")

        # КЛЮЧЕВОЕ: новый YoutubeDL на каждый URL, чтобы retcode не "залипал"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ret = ydl.download([url])

        if ret == 0:
            print(" ✅")
            ok += 1
        else:
            errors += 1

    print(
        f"\nГотово! Успешно: {Colors.GREEN}{ok}{Colors.RESET}, Ошибок: {Colors.RED}{errors}{Colors.RESET}, Дубликаты: {Colors.YELLOW}{len(dublicates)}{Colors.RESET}"
        f"\nФайлы загружены в {os.path.abspath(out_dir)}"
    )


if __name__ == "__main__":
    file_to_download = "links_copy.txt"
    if not os.path.exists(file_to_download):
        print(f"Файл с ссылками не найден: {file_to_download}")
        sys.exit(1)
    now = datetime.now().strftime("%d.%m.%Y")
    download_mp3(file_to_download, out_dir=os.path.join("downloads", now), bitrate=192)

import os
import yt_dlp
from datetime import datetime


def download_mp3(links_file: str, concurrent_fragments: int = 10, out_dir: str = "."):
    total = 0
    done = 0
    errors = 0

    last_filename = ""  # что сейчас качаем
    final_mp3 = ""  # что получилось после конвертации

    def hook(d):
        nonlocal errors, last_filename, final_mp3

        status = d.get("status")

        if status == "downloading":
            # имя файла, куда yt-dlp пишет прямо сейчас
            last_filename = os.path.basename(d.get("filename", last_filename))
            percent = d.get("_percent_str", "").strip()
            speed = d.get("_speed_str", "").strip()
            eta = d.get("_eta_str", "").strip()

            print(f"\r{percent:>7} | {speed:>10} | ETA {eta:>8} | {last_filename}", end="")

        elif status == "finished":
            # finished = файл скачан (ещё до postprocessor mp3)
            dl_file = os.path.basename(d.get("filename") or last_filename)
            print()  # перенос строки после прогресса

        elif status == "error":
            errors += 1
            print("\n[ERROR]", d.get("filename") or d.get("info_dict", {}).get("title", ""))

        # Иногда yt-dlp прокидывает postprocessor события с ключами 'postprocessor'/'info_dict'
        # Надёжный способ показать mp3 — вычислить его из имени скачанного файла:
        # если скачали xxx.webm/m4a -> после FFmpegExtractAudio будет xxx.mp3
        # (если включён FFmpegExtractAudio preferredcodec=mp3)
        if status == "finished":
            base, _ext = os.path.splitext(d.get("filename") or last_filename)
            final_mp3 = os.path.basename(base + ".mp3")
            print(f"✅ {final_mp3}")

    ydl_opts = {
        "format": "bestaudio/best",
        "concurrent_fragments": concurrent_fragments,
        # "outtmpl": os.path.join(out_dir, "%(title).200B [%(id)s].%(ext)s"),
        "outtmpl": os.path.join(out_dir, "%(title)s.%(ext)s"),
        "windowsfilenames": True,
        "trim_file_name": 200,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "progress_hooks": [hook],
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
            {"key": "FFmpegMetadata"},
        ],
        "noplaylist": False,
        "noprogress": True,
    }

    with open(links_file, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip().startswith(("http://", "https://"))]

    total = len(urls)
    print(f"Скачиваю {total} аудиофайлов...")
    os.makedirs(out_dir, exist_ok=True)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for i, url in enumerate(urls, 1):
            print(f"\n[{i}/{total}] {url}")
            ydl.download([url])
            done += 1

    print(f"\nГотово! Успешно: {done - errors}, Ошибок: {errors}")


if __name__ == "__main__":
    file_to_download = "links copy.txt"
    now = datetime.now().strftime("%d.%m.%Y")
    download_mp3(file_to_download, out_dir=os.path.join("downloads", now))

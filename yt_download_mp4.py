# Скрипт загрузки видео/аудио с YouTube, Vk Video и других сайтов
# Для запуска из powershell добавить в $PROFILE:
# function dl { uv run --upgrade "<полный путь до файла скрипта>" $args }

# /// script
# dependencies = [
#     "yt-dlp>=2025.12.8",
# ]
# ///

import argparse
import os
import re
import shutil
import sys
from datetime import datetime
from urllib.parse import parse_qs, urlparse

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


URL_RE = re.compile(r'https?://[^\s<>"\'\]\)]+', re.IGNORECASE)


def normalize_video_url(url: str) -> str:
    url = url.strip().rstrip(".,;!?)")

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path
    query = parse_qs(parsed.query)

    # youtu.be/<video_id> -> оставить только ID
    if "youtu.be" in host:
        video_id = path.strip("/").split("/")[0] if path.strip("/") else ""
        if video_id:
            return f"https://youtu.be/{video_id}"
        return url

    # youtube.com/watch?v=ID -> оставить только v
    if "youtube.com" in host or "www.youtube.com" in host or "m.youtube.com" in host:
        if path == "/watch":
            video_id = query.get("v", [""])[0]
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"
            return url

        # shorts/<id>
        if path.startswith("/shorts/"):
            video_id = path.split("/shorts/", 1)[1].split("/", 1)[0]
            if video_id:
                return f"https://www.youtube.com/shorts/{video_id}"
            return url

        # live/<id>
        if path.startswith("/live/"):
            video_id = path.split("/live/", 1)[1].split("/", 1)[0]
            if video_id:
                return f"https://www.youtube.com/live/{video_id}"
            return url

    return url


def extract_urls_from_file(source_file: str) -> list[str]:
    urls = []
    seen = set()

    with open(source_file, "r", encoding="utf-8") as f:
        for line in f:
            found = URL_RE.findall(line)
            for raw_url in found:
                clean_url = normalize_video_url(raw_url)
                if clean_url not in seen:
                    seen.add(clean_url)
                    urls.append(clean_url)

    return urls


def download_video(
    source: str,
    *,
    concurrent_fragments: int = 10,
    out_dir: str = ".",
    max_height: int = 1080,
    metadata: bool = False,
    prefer_avc_only: bool = False,  # True = если AVC нет, считать это ошибкой и не качать
    use_nvenc: bool = False,  # True = h264_nvenc, иначе libx264
    prefer_avc: bool = False,  # True = выбирать AVC-видео первым, а затем при необходимости перекодировать в mp4
    audio_only: bool = False,
    audio_bitrate: str = "192",
):
    errors = 0
    ok = 0
    skipped = 0

    last_filename = ""
    file_names = set()
    duplicates = []
    ffmpeg_available = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

    def is_avc_codec(vcodec: str) -> bool:
        v = (vcodec or "").lower()
        return v.startswith("avc1") or v.startswith("h264")

    def safe_get_selected_video_codec(info: dict) -> str:
        requested = info.get("requested_formats") or []
        for fmt in requested:
            vcodec = (fmt.get("vcodec") or "").strip()
            if vcodec and vcodec != "none":
                return vcodec

        vcodec = (info.get("vcodec") or "").strip()
        return vcodec

    def safe_get_selected_ext(info: dict) -> str:
        requested = info.get("requested_formats") or []
        for fmt in requested:
            ext = (fmt.get("ext") or "").strip()
            vcodec = (fmt.get("vcodec") or "").strip()
            if vcodec and vcodec != "none":
                return ext

        requested_audio = info.get("requested_formats") or []
        for fmt in requested_audio:
            acodec = (fmt.get("acodec") or "").strip()
            ext = (fmt.get("ext") or "").strip()
            if acodec and acodec != "none":
                return ext

        return (info.get("ext") or "").strip()

    def sanitize_final_name(info: dict, audio_only: bool = False, final_ext: str | None = None) -> str:
        title = info.get("title") or "video"
        title = re.sub(r'[\\/*?:"<>|]', "_", title).strip()
        if len(title) > 200:
            title = title[:200].rstrip()
        if final_ext:
            return f"{title}.{final_ext}"
        return f"{title}.mp3" if audio_only else f"{title}.mp4"

    def hook(d):
        nonlocal last_filename

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
            print()

    _pp_stage_printed = set()

    def postprocessor_hook(d):
        status = d.get("status")
        pp = d.get("postprocessor", "unknown")
        info = d.get("info_dict") or {}
        video_id = info.get("id") or ""

        if pp == "Merger":
            key = (video_id, pp)
            if status == "started" and key not in _pp_stage_printed:
                _pp_stage_printed.add(key)
                print("Подготовка...")

    def build_postprocessors(
        *,
        audio_only: bool,
        audio_bitrate: str,
        needs_recode: bool,
        needs_remux: bool,
        metadata: bool,
    ):
        postprocessors = []

        if audio_only:
            postprocessors.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": str(audio_bitrate),
            })
            if metadata:
                postprocessors.append({"key": "FFmpegMetadata"})
            return postprocessors

        if metadata:
            postprocessors.append({"key": "FFmpegMetadata"})

        if needs_recode:
            postprocessors.append({
                "key": "FFmpegVideoConvertor",
                "preferedformat": "mp4",
            })
        elif needs_remux:
            postprocessors.append({
                "key": "FFmpegVideoRemuxer",
                "preferedformat": "mp4",
            })

        return postprocessors

    def build_postprocessor_args(needs_recode: bool, use_nvenc: bool):
        if not needs_recode:
            return []

        if use_nvenc:
            return [
                "-c:v",
                "h264_nvenc",
                "-preset",
                "p4",
                "-cq",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
            ]

        return [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
        ]

    os.makedirs(out_dir, exist_ok=True)

    if re.match(r"^https?://", source, re.IGNORECASE):
        urls = [normalize_video_url(source)]
        source_label = f"Одна ссылка: {urls[0]}"
    else:
        urls = extract_urls_from_file(source)
        source_label = f"Файл с ссылками: {source}"

    total = len(urls)

    print("=" * 80)
    print(source_label)
    print(f"Скачиваю {total} {'аудио' if audio_only else 'видео'}...")
    print(f"FFmpeg: {'доступен' if ffmpeg_available else 'не найден'}")
    if audio_only:
        if ffmpeg_available:
            print(f"Режим: только аудио (mp3 {audio_bitrate}k)")
        else:
            print("Режим: только аудио без конвертации (исходный формат)")
    else:
        if prefer_avc:
            print("Режим: приоритет AVC (без конвертации)")
        print(f"Максимальное разрешение: {max_height}")
        print(f"Режим AVC only: {'Да' if prefer_avc_only else 'Нет'}")
        if ffmpeg_available:
            print(f"Энкодер: {'h264_nvenc' if use_nvenc else 'libx264'}")
        else:
            print("Постобработка отключена: будет скачан готовый файл без merge и конвертации")

    if ffmpeg_available:
        if audio_only:
            format_sort = []
            fmt = "bestaudio/best"
        else:
            if prefer_avc or prefer_avc_only:
                format_sort = [
                    "+codec:avc:m4a",
                    f"res:{max_height}",
                    "fps",
                    "br",
                    "size",
                ]
            else:
                format_sort = [
                    f"+res:{max_height}",
                    "br",
                    "fps",
                    "size",
                ]

            if prefer_avc_only:
                fmt = "bv*[vcodec^=avc]+ba[acodec^=mp4a]/b"
            else:
                fmt = "bv*+ba[acodec^=mp4a]/b"
    else:
        format_sort = []
        if audio_only:
            fmt = "bestaudio/best"
        elif prefer_avc_only:
            fmt = f"best[ext=mp4][vcodec^=avc][height<={max_height}]/best[vcodec^=avc][height<={max_height}]"
        elif prefer_avc:
            fmt = f"best[ext=mp4][vcodec^=avc][height<={max_height}]/best[height<={max_height}]"
        else:
            fmt = f"best[ext=mp4][height<={max_height}]/best[height<={max_height}]"

    base_ydl_opts = {
        "format": fmt,
        "format_sort": [] if audio_only else format_sort,
        "concurrent_fragments": concurrent_fragments,
        "outtmpl": os.path.join(out_dir, "%(title)s.%(ext)s"),
        "windowsfilenames": True,
        "trim_file_name": 200,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "progress_hooks": [hook],
        "postprocessor_hooks": [postprocessor_hook],
        "noplaylist": True,
        "noprogress": True,
    }
    if ffmpeg_available:
        base_ydl_opts["merge_output_format"] = "mp4"

    for i, url in enumerate(urls, 1):
        _pp_stage_printed.clear()
        print(f"\n[{i}/{total}] {url}")

        try:
            with yt_dlp.YoutubeDL(base_ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if not info:
                print(" ❌ Не удалось получить информацию о видео")
                errors += 1
                continue

            if audio_only:
                selected_ext = safe_get_selected_ext(info)
                ydl_opts = dict(base_ydl_opts)
                if ffmpeg_available:
                    final_name = sanitize_final_name(info, audio_only=True)
                else:
                    final_name = sanitize_final_name(
                        info,
                        audio_only=False,
                        final_ext=(selected_ext or "m4a"),
                    )

                if final_name in file_names:
                    print(f"{Colors.YELLOW}{final_name} - дубликат{Colors.RESET}")
                    duplicates.append(final_name)
                    continue

                if ffmpeg_available:
                    print(f"Выбран режим: только аудио | источник: {selected_ext or 'unknown'} -> mp3 {audio_bitrate}k")
                    postprocessors = build_postprocessors(
                        audio_only=True,
                        audio_bitrate=audio_bitrate,
                        needs_recode=False,
                        needs_remux=False,
                        metadata=metadata,
                    )
                    ydl_opts["postprocessors"] = postprocessors
                else:
                    print(f"Выбран режим: только аудио | источник: {selected_ext or 'unknown'} | без конвертации")

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ret = ydl.download([url])

                if ret == 0:
                    file_names.add(final_name)
                    print(f"{final_name} ✅")
                    ok += 1
                else:
                    print(" ❌")
                    errors += 1

                continue

            selected_vcodec = safe_get_selected_video_codec(info)
            selected_ext = safe_get_selected_ext(info)

            already_avc = is_avc_codec(selected_vcodec)
            needs_recode = not already_avc
            needs_remux = already_avc and selected_ext.lower() != "mp4"
            final_ext = "mp4" if ffmpeg_available else (selected_ext or "mp4")
            final_name = sanitize_final_name(info, audio_only=False, final_ext=final_ext)

            if final_name in file_names:
                print(f"{Colors.YELLOW}{final_name} - дубликат{Colors.RESET}")
                duplicates.append(final_name)
                continue

            if ffmpeg_available:
                action_label = "конвертация в AVC" if needs_recode else ("remux в mp4" if needs_remux else "без конвертации")
            else:
                action_label = "прямая загрузка без постобработки"

            print(f"Выбран кодек: {selected_vcodec or 'unknown'} | контейнер: {selected_ext or 'unknown'} | {action_label}")

            if prefer_avc_only and not already_avc:
                print(f"{Colors.RED}AVC-формат недоступен, пропускаю{Colors.RESET}")
                skipped += 1
                continue

            ydl_opts = dict(base_ydl_opts)
            if ffmpeg_available:
                postprocessors = build_postprocessors(
                    audio_only=False,
                    audio_bitrate=audio_bitrate,
                    needs_recode=needs_recode,
                    needs_remux=needs_remux,
                    metadata=metadata,
                )
                ydl_opts["postprocessors"] = postprocessors

                ppa = build_postprocessor_args(
                    needs_recode=needs_recode,
                    use_nvenc=use_nvenc,
                )
                if ppa:
                    ydl_opts["postprocessor_args"] = ppa

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ret = ydl.download([url])

            if ret == 0:
                file_names.add(final_name)
                print(f"{final_name} ✅")
                ok += 1
            else:
                print(" ❌")
                errors += 1

        except Exception as e:
            print(f" ❌ {e}")
            errors += 1

    print(
        f"\nГотово!"
        f"\nУспешно: {Colors.GREEN}{ok}{Colors.RESET}, "
        f"Ошибок: {Colors.RED}{errors}{Colors.RESET}, "
        f"Пропущено (AVC only): {Colors.YELLOW}{skipped}{Colors.RESET}, "
        f"Дубликаты: {Colors.YELLOW}{len(duplicates)}{Colors.RESET}"
        f"\nФайлы загружены в: {os.path.abspath(out_dir)}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Скрипт загрузки видео/аудио с YouTube")
    parser.add_argument(
        "source",
        nargs="?",
        default="links.txt",
        help="Либо URL одного видео, либо файл со списком ссылок (по умолчанию: links.txt)",
    )
    parser.add_argument(
        "-r",
        "--max-height",
        type=int,
        default=1080,
        help="Максимальная высота видео (по умолчанию: 1080)",
    )
    parser.add_argument(
        "--cpu",
        action="store_true",
        help="Использовать libx264 вместо h264_nvenc",
    )
    parser.add_argument(
        "--avc-only",
        action="store_true",
        help="Скачивать только AVC-видео; если AVC нет — пропускать",
    )
    parser.add_argument(
        "-m",
        "--metadata",
        action="store_true",
        help="Добавлять метаданные через FFmpegMetadata",
    )
    parser.add_argument(
        "-o",
        "--out-dir",
        default=None,
        help="Папка для сохранения файлов (по умолчанию: downloads/дата)",
    )
    parser.add_argument(
        "-q",
        "--prefer-avc",
        action="store_true",
        help="Выбирать AVC-видео в приоритете (быстрее, но разрешение может быть ниже заявленного)",
    )
    parser.add_argument(
        "-a",
        "--audio-only",
        action="store_true",
        help="Скачивать только аудио и конвертировать в mp3",
    )
    parser.add_argument(
        "-b",
        "--audio-bitrate",
        default="192",
        help="Битрейт mp3 в режиме --audio-only (по умолчанию: 192)",
    )

    args = parser.parse_args()
    source = args.source

    if not re.match(r"^https?://", source, re.IGNORECASE) and not os.path.exists(source):
        print(f"Файл с ссылками не найден: {source}")
        sys.exit(1)

    now = datetime.now().strftime("%d.%m.%Y")
    out_dir = args.out_dir or os.path.join("downloads", now)

    download_video(
        source=source,
        out_dir=out_dir,
        max_height=args.max_height,
        metadata=args.metadata,
        prefer_avc_only=args.avc_only,
        use_nvenc=not args.cpu,
        prefer_avc=args.prefer_avc,
        audio_only=args.audio_only,
        audio_bitrate=args.audio_bitrate,
    )
    os.startfile(os.path.abspath(out_dir))

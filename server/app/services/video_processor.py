import json
import hashlib
import shutil
import subprocess
import uuid
from functools import lru_cache
from pathlib import Path

from fastapi import UploadFile

from app.core.paths import EXPORTS_DIR, MATERIALS_DIR, TMP_DIR, ensure_data_dirs
from app.services.material_store import add_material, get_material, get_materials_by_ids, update_material_timing


class VideoProcessingError(RuntimeError):
    pass


TRIM_START_GUARD_SECONDS = 0.06
TRIM_AUDIO_END_BUFFER_SECONDS = 0.12
TRIM_VIDEO_END_GUARD_SECONDS = 0.02
SCHEME_END_GUARD_SECONDS = 0.02


def clean_ffmpeg_error(message: str) -> str:
    """Keep the actionable FFmpeg failure and drop version/configuration noise."""
    lines = [line.strip() for line in (message or "").splitlines() if line.strip()]
    if not lines:
        return "FFmpeg 处理失败。"

    noise_prefixes = (
        "ffmpeg version",
        "ffprobe version",
        "built with",
        "configuration:",
        "libavutil",
        "libavcodec",
        "libavformat",
        "libavdevice",
        "libavfilter",
        "libswscale",
        "libswresample",
        "libpostproc",
    )
    meaningful = [line for line in lines if not line.lower().startswith(noise_prefixes)]
    if not meaningful:
        return "FFmpeg 处理失败，请检查视频文件是否完整或格式是否受支持。"

    important_markers = ("error", "invalid", "failed", "not found", "no such", "could not", "unsupported", "moov atom")
    important = [line for line in meaningful if any(marker in line.lower() for marker in important_markers)]
    selected = important[-3:] if important else meaningful[-3:]
    cleaned = "；".join(selected)
    return cleaned[:500]


def _quiet_command(command: list[str]) -> list[str]:
    if not command:
        return command
    executable = Path(command[0]).name
    if executable in {"ffmpeg", "ffprobe"} and "-hide_banner" not in command:
        return [command[0], "-hide_banner", *command[1:]]
    return command


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(_quiet_command(command), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise VideoProcessingError(clean_ffmpeg_error(result.stderr.strip() or result.stdout.strip() or "FFmpeg command failed."))
    return result


@lru_cache(maxsize=16)
def _ffmpeg_filter_available(filter_name: str) -> bool:
    result = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return False
    return any(line.split()[1:2] == [filter_name] for line in result.stdout.splitlines())


def probe_duration(video_path: Path) -> float:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(video_path),
        ]
    )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def has_audio_stream(video_path: Path) -> bool:
    try:
        result = _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=index",
                "-of",
                "json",
                str(video_path),
            ]
        )
    except VideoProcessingError:
        return False
    data = json.loads(result.stdout or "{}")
    return bool(data.get("streams"))


def analyze_audio_loudness(media_path: Path, target_lufs: float = -14.0) -> dict[str, object]:
    if not media_path.exists():
        raise VideoProcessingError("音频素材文件不存在。")
    if not has_audio_stream(media_path):
        raise VideoProcessingError("素材没有可分析的音频流。")

    duration = 0.0
    try:
        duration = probe_duration(media_path)
    except VideoProcessingError:
        duration = 0.0

    result = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(media_path),
            "-af",
            f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ]
    )
    output = result.stderr or result.stdout
    json_start = output.rfind("{")
    json_end = output.rfind("}")
    if json_start < 0 or json_end <= json_start:
        raise VideoProcessingError("响度分析失败：FFmpeg 未返回 loudnorm 数据。")
    try:
        loudnorm = json.loads(output[json_start : json_end + 1])
    except json.JSONDecodeError as exc:
        raise VideoProcessingError("响度分析失败：loudnorm 数据解析失败。") from exc

    return {
        "duration_seconds": duration,
        "target_lufs": target_lufs,
        "input_i": loudnorm.get("input_i"),
        "input_tp": loudnorm.get("input_tp"),
        "input_lra": loudnorm.get("input_lra"),
        "input_thresh": loudnorm.get("input_thresh"),
        "output_i": loudnorm.get("output_i"),
        "output_tp": loudnorm.get("output_tp"),
        "output_lra": loudnorm.get("output_lra"),
        "output_thresh": loudnorm.get("output_thresh"),
        "normalization_type": loudnorm.get("normalization_type"),
        "target_offset": loudnorm.get("target_offset"),
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def segment_av_signature(segment: dict[str, object]) -> str:
    source_path = Path(str(segment["video_path"]))
    if not source_path.exists():
        raise VideoProcessingError(f"Source video is missing: {source_path}")
    start_seconds = float(segment["start_seconds"])
    duration = float(segment["end_seconds"]) - start_seconds
    if duration <= 0:
        raise VideoProcessingError("Invalid segment timing.")
    trim_start = start_seconds + min(0.15, duration / 4)
    trim_duration = max(0.25, duration - min(0.3, duration / 2))
    video_hash = _decoded_stream_hash(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{trim_start:.3f}",
            "-i",
            str(source_path),
            "-t",
            f"{trim_duration:.3f}",
            "-an",
            "-vf",
            "fps=3,scale=160:90,format=gray",
            "-f",
            "rawvideo",
            "-",
        ]
    )
    audio_hash = _decoded_stream_hash(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{trim_start:.3f}",
            "-i",
            str(source_path),
            "-t",
            f"{trim_duration:.3f}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "s16le",
            "-",
        ]
    )
    duration_bucket = round(trim_duration, 1)
    return f"{duration_bucket}:{video_hash}:{audio_hash}"


def _decoded_stream_hash(command: list[str]) -> str:
    result = subprocess.run(_quiet_command(command), capture_output=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="ignore").strip()
        raise VideoProcessingError(clean_ffmpeg_error(stderr or "FFmpeg fingerprint failed."))
    return hashlib.sha256(result.stdout).hexdigest()


def probe_video(video_path: Path) -> dict[str, object]:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(video_path),
        ]
    )
    data = json.loads(result.stdout)
    stream = (data.get("streams") or [{}])[0]
    rate = str(stream.get("r_frame_rate") or "0/1")
    numerator, _, denominator = rate.partition("/")
    fps = 0.0
    if denominator and float(denominator) != 0:
        fps = float(numerator) / float(denominator)
    return {
        "duration_seconds": float(data.get("format", {}).get("duration") or 0),
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "fps": fps,
    }


def create_thumbnail(video_path: Path, target_path: Path, *, seconds: float = 0.1) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{max(0, seconds):.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            "scale=360:-1",
            str(target_path),
        ]
    )
    return target_path


def extract_representative_frames(video_path: Path, target_dir: Path, *, start_seconds: float = 0.0, end_seconds: float | None = None, count: int = 3) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        duration = probe_duration(video_path)
    except VideoProcessingError:
        duration = 0.0
    start = max(0.0, start_seconds)
    end = min(duration, end_seconds if end_seconds is not None else duration) if duration > 0 else max(start + 0.1, end_seconds or start + 1.0)
    if end <= start:
        end = start + max(0.1, duration or 1.0)
    ratios = [0.2, 0.5, 0.8][: max(1, count)]
    if count == 1:
        ratios = [0.5]
    frames: list[Path] = []
    for index, ratio in enumerate(ratios, start=1):
        timestamp = start + (end - start) * ratio
        frame_path = target_dir / f"frame_{index:02d}.jpg"
        create_thumbnail(video_path, frame_path, seconds=timestamp)
        frames.append(frame_path)
    return frames


def extract_audio_for_whisper(video_path: Path, target_path: Path) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "64k",
            str(target_path),
        ]
    )
    return target_path


def extract_pcm_16k(video_path: Path, target_path: Path) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "s16le",
            str(target_path),
        ]
    )
    return target_path


def extract_wav_16k(video_path: Path, target_path: Path) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(target_path),
        ]
    )
    return target_path


def create_segment_preview(segment: dict[str, object]) -> Path:
    source_path = Path(str(segment["video_path"]))
    if not source_path.exists():
        raise VideoProcessingError("Source video is missing.")
    start_seconds, video_end_seconds, audio_end_seconds = _clip_bounds(segment)
    if video_end_seconds <= start_seconds:
        raise VideoProcessingError("Invalid segment timing.")

    preview_dir = TMP_DIR / "segment_previews" / str(segment["id"])
    preview_dir.mkdir(parents=True, exist_ok=True)
    target_path = preview_dir / f"preview_exact_v3_{int(start_seconds * 1000)}_{int(video_end_seconds * 1000)}_{int(audio_end_seconds * 1000)}.mp4"
    if target_path.exists():
        return target_path

    _encode_precise_clip(
        source_path,
        target_path,
        start_seconds=start_seconds,
        video_end_seconds=video_end_seconds,
        audio_end_seconds=audio_end_seconds,
        preset="ultrafast",
        crf="28",
        faststart=True,
    )
    return target_path


def create_segment_range_preview(segment: dict[str, object], *, start_seconds: float, end_seconds: float) -> Path:
    source_path = Path(str(segment["video_path"]))
    if not source_path.exists():
        raise VideoProcessingError("Source video is missing.")
    raw_start = float(segment["start_seconds"])
    raw_end = float(segment["end_seconds"])
    if start_seconds < raw_start or end_seconds > raw_end:
        raise VideoProcessingError("Preview range must stay inside the segment.")
    preview_segment = {**segment, "start_seconds": start_seconds, "end_seconds": end_seconds}
    start_seconds, video_end_seconds, audio_end_seconds = _clip_bounds(preview_segment)
    if video_end_seconds <= start_seconds:
        raise VideoProcessingError("Invalid segment timing.")

    preview_dir = TMP_DIR / "segment_range_previews" / str(segment["id"])
    preview_dir.mkdir(parents=True, exist_ok=True)
    target_path = preview_dir / f"range_v1_{int(start_seconds * 1000)}_{int(video_end_seconds * 1000)}_{int(audio_end_seconds * 1000)}.mp4"
    if target_path.exists():
        return target_path

    _encode_precise_clip(
        source_path,
        target_path,
        start_seconds=start_seconds,
        video_end_seconds=video_end_seconds,
        audio_end_seconds=audio_end_seconds,
        preset="ultrafast",
        crf="28",
        faststart=True,
    )
    return target_path


def export_segments(segments: list[dict[str, object]], output_dir: Path | None = None) -> Path:
    ensure_data_dirs()
    if not segments:
        raise VideoProcessingError("No segments selected for export.")

    export_id = uuid.uuid4().hex
    normalized_dir = TMP_DIR / f"scheme_export_{export_id}"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    concat_list_path = normalized_dir / "concat.txt"
    normalized_paths: list[Path] = []
    export_clips = _prepare_export_clips(segments, for_scheme=True)

    for index, clip in enumerate(export_clips):
        source_path = Path(str(clip["video_path"]))
        if not source_path.exists():
            raise VideoProcessingError(f"Source video is missing: {source_path}")
        normalized_path = normalized_dir / f"clip_{index:03d}.mp4"
        _encode_precise_clip(
            source_path,
            normalized_path,
            start_seconds=float(clip["start_seconds"]),
            video_end_seconds=float(clip["video_end_seconds"]),
            audio_end_seconds=float(clip["audio_end_seconds"]),
            preset="veryfast",
            crf="23",
            faststart=False,
        )
        normalized_paths.append(normalized_path)

    concat_list_path.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in normalized_paths),
        encoding="utf-8",
    )
    target_dir = output_dir or EXPORTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    export_path = target_dir / f"scheme_{export_id}.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-c",
            "copy",
            str(export_path),
        ]
    )
    return export_path


def export_timeline(timeline: dict[str, object], output_dir: Path | None = None) -> Path:
    ensure_data_dirs()
    clips = list(timeline.get("clips", []))
    if not clips:
        raise VideoProcessingError("时间线里还没有片段。")

    export_id = uuid.uuid4().hex
    normalized_dir = TMP_DIR / f"timeline_export_{export_id}"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    concat_list_path = normalized_dir / "concat.txt"
    normalized_paths: list[Path] = []

    for index, clip in enumerate(clips):
        source_path = Path(str(clip["source_path"]))
        if not source_path.exists():
            raise VideoProcessingError(f"源视频文件不存在：{source_path}")
        source_in = float(clip["source_in"])
        source_out = float(clip["source_out"])
        if source_out <= source_in:
            raise VideoProcessingError("时间线片段时间无效。")
        normalized_path = normalized_dir / f"clip_{index:03d}.mp4"
        _encode_precise_clip(
            source_path,
            normalized_path,
            start_seconds=source_in,
            video_end_seconds=source_out,
            audio_end_seconds=source_out,
            preset="veryfast",
            crf="23",
            faststart=False,
            include_audio=str(timeline.get("audio_policy") or "keep_original") not in {"remove_original", "replace_with_voice"},
        )
        normalized_paths.append(normalized_path)

    concat_list_path.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in normalized_paths),
        encoding="utf-8",
    )
    target_dir = output_dir or EXPORTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    timeline_id = timeline.get("id") or timeline.get("timeline_id") or "timeline"
    raw_export_path = normalized_dir / "timeline_concat.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-c",
            "copy",
            str(raw_export_path),
        ]
    )
    export_path = target_dir / f"material_mix_{timeline_id}_{export_id}.mp4"
    _finalize_timeline_export(raw_export_path, export_path, timeline, normalized_dir)
    return export_path


def create_timeline_preview(timeline: dict[str, object]) -> Path:
    clips = list(timeline.get("clips", []))
    if not clips:
        raise VideoProcessingError("时间线里还没有片段。")
    timeline_id = timeline.get("id") or timeline.get("timeline_id") or "timeline"
    signature = hashlib.sha256(
        ("timeline_v1|" + "|".join(
            (
                f"{clip.get('clip_id')}:{clip.get('segment_id')}:{clip.get('position')}:"
                f"{float(clip['source_in']):.3f}:{float(clip['source_out']):.3f}"
            )
            for clip in clips
        )).encode("utf-8")
    ).hexdigest()[:16]
    preview_dir = TMP_DIR / "material_mix_previews" / str(timeline_id)
    preview_dir.mkdir(parents=True, exist_ok=True)
    target_path = preview_dir / f"preview_{signature}.mp4"
    if target_path.exists():
        return target_path
    for old_path in preview_dir.glob("preview_*.mp4"):
        old_path.unlink(missing_ok=True)
    generated_path = export_timeline(timeline, output_dir=preview_dir)
    generated_path.rename(target_path)
    return target_path


def create_timeline_clip_preview(clip: dict[str, object]) -> Path:
    source_path = Path(str(clip["source_path"]))
    if not source_path.exists():
        raise VideoProcessingError(f"源视频文件不存在：{source_path}")
    source_in = float(clip["source_in"])
    source_out = float(clip["source_out"])
    try:
        source_duration = probe_duration(source_path)
        source_out = min(source_out, source_duration)
        source_in = min(source_in, max(0.0, source_duration - 0.3))
    except VideoProcessingError:
        pass
    if source_out - source_in < 0.3:
        raise VideoProcessingError("时间线片段至少保留 0.3 秒。")
    signature = hashlib.sha256(
        (
            f"timeline_clip_v1|{clip.get('clip_id')}:{clip.get('segment_id')}:"
            f"{source_in:.3f}:{source_out:.3f}:{source_path}"
        ).encode("utf-8")
    ).hexdigest()[:16]
    preview_dir = TMP_DIR / "material_mix_clip_previews" / str(clip.get("timeline_id") or "timeline")
    preview_dir.mkdir(parents=True, exist_ok=True)
    target_path = preview_dir / f"clip_{clip.get('clip_id')}_{signature}.mp4"
    if target_path.exists():
        return target_path
    for old_path in preview_dir.glob(f"clip_{clip.get('clip_id')}_*.mp4"):
        old_path.unlink(missing_ok=True)
    _encode_precise_clip(
        source_path,
        target_path,
        start_seconds=source_in,
        video_end_seconds=source_out,
        audio_end_seconds=source_out,
        preset="ultrafast",
        crf="28",
        faststart=True,
    )
    return target_path


def _encode_precise_clip(
    source_path: Path,
    target_path: Path,
    *,
    start_seconds: float,
    video_end_seconds: float,
    audio_end_seconds: float,
    preset: str,
    crf: str,
    faststart: bool,
    include_audio: bool = True,
) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-avoid_negative_ts",
        "make_zero",
    ]
    if include_audio and has_audio_stream(source_path):
        command.extend(
            [
                "-filter_complex",
                (
                    f"[0:v:0]trim=start={start_seconds:.3f}:end={video_end_seconds:.3f},setpts=PTS-STARTPTS,"
                    "scale=trunc(iw/2)*2:trunc(ih/2)*2[v];"
                    f"[0:a:0]atrim=start={start_seconds:.3f}:end={audio_end_seconds:.3f},asetpts=PTS-STARTPTS[a]"
                ),
                "-map",
                "[v]",
                "-map",
                "[a]",
                "-c:a",
                "aac",
                "-ar",
                "44100",
                "-ac",
                "2",
            ]
        )
    else:
        command.extend(
            [
                "-vf",
                f"trim=start={start_seconds:.3f}:end={video_end_seconds:.3f},setpts=PTS-STARTPTS,scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-an",
            ]
        )
    command.extend(["-c:v", "libx264", "-preset", preset, "-crf", crf])
    if faststart:
        command.extend(["-movflags", "+faststart"])
    command.append(str(target_path))
    _run(command)


def _finalize_timeline_export(source_path: Path, export_path: Path, timeline: dict[str, object], work_dir: Path) -> None:
    audio_policy = str(timeline.get("audio_policy") or "keep_original")
    normalize_loudness = bool(int(timeline.get("normalize_loudness") or 0))
    target_lufs = float(timeline.get("target_lufs") or -14)
    bgm_path = _asset_path_from_timeline(timeline, "bgm_asset")
    voice_path = _asset_path_from_timeline(timeline, "voice_asset")
    burn_subtitles = bool(int(timeline.get("burn_subtitles") or 0)) and _ffmpeg_filter_available("subtitles")
    subtitle_path = _write_timeline_subtitles(timeline, work_dir) if burn_subtitles else None

    needs_processing = (
        normalize_loudness
        or burn_subtitles
        or bool(bgm_path)
        or bool(voice_path)
        or audio_policy in {"remove_original", "replace_with_voice"}
    )
    if not needs_processing:
        shutil.copy2(source_path, export_path)
        return

    command = ["ffmpeg", "-y", "-i", str(source_path)]
    input_audio_labels: list[str] = []
    next_input_index = 1
    has_original_audio = has_audio_stream(source_path)
    if voice_path and voice_path.exists():
        command.extend(["-i", str(voice_path)])
        input_audio_labels.append(f"[{next_input_index}:a]volume=1.0[voice]")
        voice_label = "[voice]"
        next_input_index += 1
    else:
        voice_label = ""
    if bgm_path and bgm_path.exists():
        command.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
        input_audio_labels.append(f"[{next_input_index}:a]volume=0.18[bgm]")
        bgm_label = "[bgm]"
        next_input_index += 1
    else:
        bgm_label = ""

    filters: list[str] = []
    video_label = "0:v"
    if subtitle_path:
        filters.append(f"[0:v]subtitles=filename='{_escape_filter_path(subtitle_path)}'[vout]")
        video_label = "vout"

    audio_sources: list[str] = []
    if has_original_audio and audio_policy not in {"remove_original", "replace_with_voice"}:
        audio_sources.append("[0:a]")
    if voice_label:
        filters.extend(input_audio_labels[:1])
        audio_sources.append(voice_label)
    if bgm_label:
        filters.extend(input_audio_labels[1:] if voice_label else input_audio_labels[:1])
        audio_sources.append(bgm_label)

    audio_label = ""
    if audio_sources:
        if len(audio_sources) == 1:
            if normalize_loudness:
                filters.append(f"{audio_sources[0]}loudnorm=I={target_lufs:.1f}:TP=-1.5:LRA=11[aout]")
                audio_label = "aout"
            else:
                audio_label = audio_sources[0].strip("[]")
        else:
            mixed = "".join(audio_sources)
            loudnorm = f",loudnorm=I={target_lufs:.1f}:TP=-1.5:LRA=11" if normalize_loudness else ""
            filters.append(f"{mixed}amix=inputs={len(audio_sources)}:duration=first:dropout_transition=0{loudnorm}[aout]")
            audio_label = "aout"

    if filters:
        command.extend(["-filter_complex", ";".join(filters)])
    command.extend(["-map", f"[{video_label}]" if video_label == "vout" else "0:v"])
    if audio_label:
        command.extend(["-map", f"[{audio_label}]" if audio_label not in {"0:a"} else "0:a", "-c:a", "aac", "-ar", "44100", "-ac", "2"])
    else:
        command.append("-an")
    command.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-movflags", "+faststart", "-shortest", str(export_path)])
    _run(command)


def _asset_path_from_timeline(timeline: dict[str, object], key: str) -> Path | None:
    asset = timeline.get(key)
    if isinstance(asset, dict) and asset.get("file_path"):
        return Path(str(asset["file_path"]))
    return None


def _write_timeline_subtitles(timeline: dict[str, object], work_dir: Path) -> Path:
    ass_path = work_dir / "timeline_subtitles.ass"
    clips = list(timeline.get("clips", []))
    style = _timeline_subtitle_style(timeline)
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        style,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for clip in clips:
        text = _escape_ass_text(str(clip.get("text") or ""))
        if not text:
            continue
        lines.append(
            f"Dialogue: 0,{_ass_time(float(clip.get('timeline_in') or 0))},{_ass_time(float(clip.get('timeline_out') or 0))},Default,,0,0,0,,{text}"
        )
    ass_path.write_text("\n".join(lines), encoding="utf-8")
    return ass_path


def _timeline_subtitle_style(timeline: dict[str, object]) -> str:
    preset = timeline.get("subtitle_preset")
    if not isinstance(preset, dict):
        return _ass_style_line({})
    metadata = preset.get("metadata")
    if isinstance(metadata, dict):
        style_data = metadata.get("subtitle_style")
        if isinstance(style_data, dict):
            return _ass_style_line(style_data)
    preset_path = Path(str(preset.get("file_path") or ""))
    if not preset_path.exists():
        return _ass_style_line({})
    if preset_path.suffix.lower() == ".ass":
        try:
            return _extract_ass_default_style(preset_path) or _ass_style_line({})
        except UnicodeDecodeError:
            return _ass_style_line({})
    if preset_path.suffix.lower() == ".json":
        try:
            data = json.loads(preset_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _ass_style_line({})
        return _ass_style_line(data if isinstance(data, dict) else {})
    return _ass_style_line({})


def _extract_ass_default_style(path: Path) -> str:
    content = path.read_text(encoding="utf-8-sig")
    first_style = ""
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith("style:"):
            continue
        if not first_style:
            first_style = stripped
        name = stripped.split(":", 1)[1].split(",", 1)[0].strip().lower()
        if name == "default":
            return stripped
    return first_style


def _ass_style_line(data: dict[str, object]) -> str:
    font = str(data.get("font") or data.get("fontname") or "Arial")
    size = int(float(data.get("size") or data.get("font_size") or 64))
    primary = str(data.get("primary_color") or data.get("color") or "&H00FFFFFF")
    outline_color = str(data.get("outline_color") or "&H00111111")
    back_color = str(data.get("back_color") or "&H66000000")
    bold = 1 if data.get("bold", True) else 0
    outline = float(data.get("outline") or 4)
    shadow = float(data.get("shadow") or 1)
    alignment = int(data.get("alignment") or 2)
    margin_v = int(data.get("margin_v") or 150)
    return (
        f"Style: Default,{font},{size},{primary},&H000000FF,{outline_color},{back_color},"
        f"{bold},0,0,0,100,100,0,0,1,{outline:g},{shadow:g},{alignment},72,72,{margin_v},1"
    )


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    whole = int(seconds % 60)
    centiseconds = int(round((seconds - int(seconds)) * 100))
    return f"{hours}:{minutes:02d}:{whole:02d}.{centiseconds:02d}"


def _escape_ass_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def _escape_filter_path(path: Path) -> str:
    return path.as_posix().replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")


def _clip_bounds(segment: dict[str, object], *, pre_roll: float = 0.0, post_roll: float = 0.0) -> tuple[float, float, float]:
    source_path = Path(str(segment["video_path"]))
    raw_start = float(segment["start_seconds"])
    raw_end = float(segment["end_seconds"])
    start_seconds = max(0.0, raw_start - pre_roll + TRIM_START_GUARD_SECONDS)
    video_end_seconds = raw_end + post_roll - TRIM_VIDEO_END_GUARD_SECONDS
    audio_end_seconds = raw_end + post_roll + TRIM_AUDIO_END_BUFFER_SECONDS
    try:
        source_duration = probe_duration(source_path)
    except VideoProcessingError:
        source_duration = audio_end_seconds
    video_end_seconds = min(source_duration, video_end_seconds)
    audio_end_seconds = min(source_duration, audio_end_seconds)
    if video_end_seconds <= start_seconds:
        start_seconds = max(0.0, raw_start - pre_roll)
        video_end_seconds = min(source_duration, max(raw_end + post_roll, start_seconds + 0.3))
        audio_end_seconds = min(source_duration, max(video_end_seconds, audio_end_seconds))
    return start_seconds, video_end_seconds, audio_end_seconds


def _scheme_clip_bounds(segment: dict[str, object]) -> tuple[float, float, float]:
    source_path = Path(str(segment["video_path"]))
    raw_start = float(segment["start_seconds"])
    raw_end = float(segment["end_seconds"])
    start_seconds = max(0.0, raw_start + TRIM_START_GUARD_SECONDS)
    end_seconds = raw_end - SCHEME_END_GUARD_SECONDS
    try:
        source_duration = probe_duration(source_path)
    except VideoProcessingError:
        source_duration = raw_end
    end_seconds = min(source_duration, end_seconds)
    if end_seconds <= start_seconds:
        end_seconds = min(source_duration, max(raw_end, start_seconds + 0.3))
    return start_seconds, end_seconds, end_seconds


def _prepare_export_clips(segments: list[dict[str, object]], *, for_scheme: bool = False) -> list[dict[str, object]]:
    clips: list[dict[str, object]] = []
    for segment in segments:
        source_path = Path(str(segment["video_path"]))
        raw_start = float(segment["start_seconds"])
        raw_end = float(segment["end_seconds"])
        if for_scheme:
            start_seconds, video_end_seconds, audio_end_seconds = _scheme_clip_bounds(segment)
        else:
            start_seconds, video_end_seconds, audio_end_seconds = _clip_bounds(
                segment,
                pre_roll=0,
                post_roll=0,
            )
        clips.append(
            {
                "video_path": str(source_path),
                "start_seconds": start_seconds,
                "end_seconds": audio_end_seconds,
                "video_end_seconds": video_end_seconds,
                "audio_end_seconds": audio_end_seconds,
                "raw_start_seconds": raw_start,
                "raw_end_seconds": raw_end,
            }
        )
    return clips


def create_scheme_preview(scheme_id: int, segments: list[dict[str, object]]) -> Path:
    if not segments:
        raise VideoProcessingError("No segments selected for preview.")
    signature = hashlib.sha256(
        ("v7|" + "|".join(
            f"{item['id']}:{float(item['start_seconds']):.3f}:{float(item['end_seconds']):.3f}"
            for item in segments
        )).encode("utf-8")
    ).hexdigest()[:16]
    preview_dir = TMP_DIR / "scheme_previews" / str(scheme_id)
    preview_dir.mkdir(parents=True, exist_ok=True)
    target_path = preview_dir / f"preview_{signature}.mp4"
    if target_path.exists():
        return target_path
    for old_path in preview_dir.glob("preview_*.mp4"):
        old_path.unlink(missing_ok=True)
    return export_segments(segments, output_dir=preview_dir).rename(target_path)


def _safe_export_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_." else "_" for char in value.strip())
    return cleaned[:80] or "segment"


def _semantic_export_tags(value: object) -> list[str]:
    tags = [_safe_export_name(item) for item in str(value or "过渡").split(",") if item.strip()]
    return tags or ["过渡"]


def export_segment_files(segments: list[dict[str, object]], output_dir: Path | None = None, export_tag: str = "") -> list[Path]:
    ensure_data_dirs()
    if not segments:
        raise VideoProcessingError("No segments selected for export.")
    exported_paths: list[Path] = []

    for index, segment in enumerate(segments, start=1):
        source_path = Path(str(segment["video_path"]))
        if not source_path.exists():
            raise VideoProcessingError(f"Source video is missing: {source_path}")
        start_seconds, video_end_seconds, audio_end_seconds = _clip_bounds(segment)
        if video_end_seconds <= start_seconds:
            raise VideoProcessingError("Invalid segment timing.")
        project_name = _safe_export_name(str(segment.get("project_name") or f"project_{segment.get('project_id', 'unknown')}"))
        project_dir = (output_dir or EXPORTS_DIR) / project_name
        tags = [_safe_export_name(export_tag)] if export_tag.strip() else _semantic_export_tags(segment.get("semantic_type"))
        segment_id = int(segment["id"])
        video_name = _safe_export_name(Path(str(segment.get("video_name") or "video")).stem)
        output_name = f"{index:02d}_{segment_id}_{video_name}_{int(start_seconds * 1000)}_{int(video_end_seconds * 1000)}.mp4"
        primary_dir = project_dir / tags[0]
        primary_dir.mkdir(parents=True, exist_ok=True)
        output_path = primary_dir / output_name
        _encode_precise_clip(
            source_path,
            output_path,
            start_seconds=start_seconds,
            video_end_seconds=video_end_seconds,
            audio_end_seconds=audio_end_seconds,
            preset="veryfast",
            crf="23",
            faststart=True,
        )
        exported_paths.append(output_path)
        for tag in tags[1:]:
            tagged_dir = project_dir / tag
            tagged_dir.mkdir(parents=True, exist_ok=True)
            tagged_path = tagged_dir / output_name
            shutil.copy2(output_path, tagged_path)
            exported_paths.append(tagged_path)
    return exported_paths


async def save_upload(file: UploadFile) -> Path:
    ensure_data_dirs()
    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    target_dir = MATERIALS_DIR / uuid.uuid4().hex
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"source{suffix}"

    with target_path.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            output.write(chunk)

    return target_path


def split_video(video_path: Path, *, segment_seconds: int = 5) -> list[dict[str, object]]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise VideoProcessingError("FFmpeg or ffprobe is not installed or not in PATH.")

    duration = probe_duration(video_path)
    clips_dir = video_path.parent / "clips"
    clips_dir.mkdir(exist_ok=True)
    output_pattern = clips_dir / "clip_%03d.mp4"

    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-map",
            "0",
            "-c",
            "copy",
            "-f",
            "segment",
            "-segment_time",
            str(segment_seconds),
            "-reset_timestamps",
            "1",
            str(output_pattern),
        ]
    )

    clips: list[dict[str, object]] = []
    for index, clip_path in enumerate(sorted(clips_dir.glob("clip_*.mp4"))):
        start_seconds = index * segment_seconds
        clip_duration = probe_duration(clip_path)
        end_seconds = min(start_seconds + clip_duration, duration)
        material_id = add_material(
            source_name=video_path.name,
            file_path=clip_path,
            source_path=video_path,
            kind="video_clip",
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            duration_seconds=clip_duration,
        )
        clips.append(
            {
                "id": material_id,
                "file_path": str(clip_path),
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "duration_seconds": clip_duration,
            }
        )

    if not clips and duration > 0:
        raise VideoProcessingError("No clips were created from the uploaded video.")

    return clips


def trim_material(material_id: int, *, start_seconds: float, end_seconds: float) -> dict[str, object]:
    material = get_material(material_id)
    if material is None:
        raise VideoProcessingError("Material not found.")
    if start_seconds < 0:
        raise VideoProcessingError("Start time cannot be negative.")
    if end_seconds <= start_seconds:
        raise VideoProcessingError("End time must be greater than start time.")

    source_path = Path(material["source_path"])
    if not source_path.exists():
        raise VideoProcessingError("Original source video is missing.")

    source_duration = probe_duration(source_path)
    if end_seconds > source_duration:
        raise VideoProcessingError("End time is beyond the source video duration.")

    old_file_path = Path(material["file_path"])
    trimmed_dir = old_file_path.parent / "trimmed"
    trimmed_dir.mkdir(exist_ok=True)
    target_path = trimmed_dir / f"clip_{material_id}_{int(start_seconds * 1000)}_{int(end_seconds * 1000)}.mp4"
    duration_seconds = end_seconds - start_seconds

    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-ss",
            f"{start_seconds:.3f}",
            "-t",
            f"{duration_seconds:.3f}",
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            str(target_path),
        ]
    )

    actual_duration = probe_duration(target_path)
    return update_material_timing(
        material_id=material_id,
        file_path=target_path,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        duration_seconds=actual_duration,
    )


def create_preview_clip(material_id: int, *, start_seconds: float, end_seconds: float) -> Path:
    material = get_material(material_id)
    if material is None:
        raise VideoProcessingError("Material not found.")
    if start_seconds < 0:
        raise VideoProcessingError("Start time cannot be negative.")
    if end_seconds <= start_seconds:
        raise VideoProcessingError("End time must be greater than start time.")

    source_path = Path(material["source_path"])
    if not source_path.exists():
        raise VideoProcessingError("Original source video is missing.")

    source_duration = probe_duration(source_path)
    if end_seconds > source_duration:
        raise VideoProcessingError("End time is beyond the source video duration.")

    preview_dir = TMP_DIR / "previews" / str(material_id)
    preview_dir.mkdir(parents=True, exist_ok=True)
    target_path = preview_dir / f"preview_{int(start_seconds * 1000)}_{int(end_seconds * 1000)}.mp4"
    if target_path.exists():
        return target_path

    duration_seconds = end_seconds - start_seconds
    preview_segment = {"video_path": str(source_path), "start_seconds": start_seconds, "end_seconds": end_seconds}
    trim_start_seconds, trim_video_end_seconds, trim_audio_end_seconds = _clip_bounds(preview_segment)
    duration_seconds = trim_audio_end_seconds - trim_start_seconds
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-ss",
            f"{trim_start_seconds:.3f}",
            "-t",
            f"{duration_seconds:.3f}",
            "-avoid_negative_ts",
            "make_zero",
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "28",
            "-c:a",
            "aac",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(target_path),
        ]
    )
    return target_path


def trim_materials(items: list[dict[str, float]]) -> list[dict[str, object]]:
    updated: list[dict[str, object]] = []
    for item in items:
        updated.append(
            trim_material(
                int(item["id"]),
                start_seconds=float(item["start_seconds"]),
                end_seconds=float(item["end_seconds"]),
            )
        )
    return updated


def export_materials(material_ids: list[int]) -> Path:
    ensure_data_dirs()
    materials = get_materials_by_ids(material_ids)
    if not materials:
        raise VideoProcessingError("No materials selected for export.")
    if len(materials) != len(material_ids):
        raise VideoProcessingError("Some selected materials were not found.")

    export_id = uuid.uuid4().hex
    normalized_dir = TMP_DIR / f"export_{export_id}"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    concat_list_path = normalized_dir / "concat.txt"
    normalized_paths: list[Path] = []

    for index, material in enumerate(materials):
        source_path = Path(material["file_path"])
        if not source_path.exists():
            raise VideoProcessingError(f"Clip file is missing: {source_path}")
        normalized_path = normalized_dir / f"clip_{index:03d}.mp4"
        _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source_path),
                "-vf",
                "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-ar",
                "44100",
                "-ac",
                "2",
                str(normalized_path),
            ]
        )
        normalized_paths.append(normalized_path)

    concat_list_path.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in normalized_paths),
        encoding="utf-8",
    )
    export_path = EXPORTS_DIR / f"export_{export_id}.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-c",
            "copy",
            str(export_path),
        ]
    )
    return export_path

import json
import hashlib
import shutil
import subprocess
import uuid
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


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise VideoProcessingError(result.stderr.strip() or "FFmpeg command failed.")
    return result


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
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="ignore").strip()
        raise VideoProcessingError(stderr or "FFmpeg fingerprint failed.")
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
        )
        normalized_paths.append(normalized_path)

    concat_list_path.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in normalized_paths),
        encoding="utf-8",
    )
    target_dir = output_dir or EXPORTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    timeline_id = timeline.get("id") or timeline.get("timeline_id") or "timeline"
    export_path = target_dir / f"material_mix_{timeline_id}_{export_id}.mp4"
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
) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-avoid_negative_ts",
        "make_zero",
    ]
    if has_audio_stream(source_path):
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


def export_segment_files(segments: list[dict[str, object]], output_dir: Path | None = None) -> list[Path]:
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
        tags = _semantic_export_tags(segment.get("semantic_type"))
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

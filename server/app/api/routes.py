import asyncio
import json
import mimetypes
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.paths import MATERIALS_DIR, TMP_DIR, ensure_data_dirs
from app.services.deepseek import DeepSeekClient, DeepSeekError
from app.services.material_store import (
    get_material,
    list_materials,
    list_materials_for_matching,
    update_material_section,
    update_material_tag,
)
from app.services.workspace_store import (
    add_video,
    create_project,
    create_scheme_set,
    delete_project,
    delete_segments,
    delete_scheme_segment,
    get_project,
    get_scheme,
    get_segment,
    get_segments_by_ids,
    get_settings,
    get_video,
    init_workspace_db,
    list_projects,
    list_schemes,
    list_segments,
    list_videos,
    move_scheme_segment,
    split_segment,
    update_project,
    update_segment,
    update_scheme_segment,
    update_settings,
)
from app.services import workspace_store
from app.services.providers import (
    ProviderError,
    generate_schemes,
    public_settings,
    recommend_scheme_range,
    segment_transcript,
    test_ai_settings,
    test_asr_settings,
    transcribe_video_with_segments,
)
from app.services.video_processor import (
    VideoProcessingError,
    create_preview_clip,
    create_segment_range_preview,
    create_segment_preview,
    create_scheme_preview,
    create_thumbnail,
    export_segment_files,
    export_segments,
    file_sha256,
    probe_video,
    export_materials,
    save_upload,
    segment_av_signature,
    split_video,
    trim_material,
    trim_materials,
)

router = APIRouter()

ALLOWED_TAGS = {
    "噱头引入",
    "痛点",
    "产品方案",
    "效果展示",
    "信任背书",
    "价格对比",
    "活动福利",
    "行动号召",
    "产品定位",
    "过渡",
}
ALLOWED_SECTIONS = {"片头", "中间段", "结尾"}


class ScriptAnalyzeRequest(BaseModel):
    script: str = Field(min_length=1, description="User script to split into ecommerce video sections.")


class ScriptAnalyzeResponse(BaseModel):
    result: str


class Material(BaseModel):
    id: int
    source_name: str
    file_path: str
    source_path: str
    kind: str
    tag: str
    section: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    created_at: str


class VideoImportResponse(BaseModel):
    source_path: str
    clip_count: int
    clips: list[dict[str, object]]


class MaterialTrimRequest(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)


class MaterialTagRequest(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=10)


class MaterialSectionRequest(BaseModel):
    sections: list[str] = Field(default_factory=list, max_length=3)


class MaterialBatchTrimItem(BaseModel):
    id: int
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)


class MaterialBatchTrimRequest(BaseModel):
    items: list[MaterialBatchTrimItem] = Field(min_length=1)


class ExportRequest(BaseModel):
    material_ids: list[int] = Field(min_length=1)


class ExportResponse(BaseModel):
    export_path: str


class MixRequirement(BaseModel):
    section: str = Field(min_length=1, max_length=20)
    tag: str = Field(min_length=1, max_length=40)


class MixDraftRequest(BaseModel):
    requirement_prompt: str = Field(min_length=1, max_length=1000)


class MixDraftItem(BaseModel):
    section: str
    tag: str
    material_id: int
    source_name: str
    duration_seconds: float


class MixDraftResponse(BaseModel):
    requirements: list[MixDraftItem]


class MixExportRequest(BaseModel):
    material_ids: list[int] | None = None
    requirements: list[MixRequirement] | None = None


class MixExportResponse(BaseModel):
    export_path: str
    material_ids: list[int]


class AppSettingsRequest(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


class SettingsTestRequest(BaseModel):
    target: str = Field(pattern="^(ai|asr)$")


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    custom_prompt: str = Field(default="", max_length=2000)
    category: str = Field(default="默认", max_length=40)


class ProjectPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    custom_prompt: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, min_length=1, max_length=40)


class ManualTranscribeRequest(BaseModel):
    manual_transcript: str = Field(default="", max_length=50000)


class SchemeGenerateRequest(BaseModel):
    target_duration: float = Field(default=30, ge=5, le=180)
    duration_min: float | None = Field(default=None, ge=5, le=180)
    duration_max: float | None = Field(default=None, ge=5, le=180)
    scheme_count: int | None = Field(default=None, ge=1, le=30)
    strategy_count: int | None = Field(default=None, ge=1, le=15)
    outputs_per_strategy: int | None = Field(default=None, ge=1, le=10)
    segment_count: int | None = Field(default=None, ge=1, le=80)
    requirement_prompt: str = Field(default="", max_length=3000)


class SchemeSegmentPatchRequest(BaseModel):
    segment_id: int | None = None
    action: str | None = Field(default=None, pattern="^(move_up|move_down|delete)$")


class SegmentPatchRequest(BaseModel):
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, gt=0)
    text: str | None = None
    semantic_type: str | None = None
    position_type: str | None = None


class SegmentExportRequest(BaseModel):
    segment_ids: list[int] = Field(min_length=1)
    output_dir: str | None = None


class SegmentDeleteRequest(BaseModel):
    segment_ids: list[int] = Field(min_length=1)


class SegmentSplitRequest(BaseModel):
    cut_points: list[float] = Field(min_length=1, max_length=40)


class SchemeExportRequest(BaseModel):
    output_dir: str | None = None


class SegmentDedupeRequest(BaseModel):
    dry_run: bool = False


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/settings")
def read_settings() -> dict[str, str]:
    return public_settings()


@router.patch("/settings")
def save_settings(payload: AppSettingsRequest) -> dict[str, str]:
    return update_settings(payload.values)


@router.post("/settings/test")
async def test_settings(payload: SettingsTestRequest) -> dict[str, str]:
    try:
        if payload.target == "ai":
            return await test_ai_settings()
        return await test_asr_settings()
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects")
def get_projects() -> list[dict[str, object]]:
    return list_projects()


@router.post("/projects")
def post_project(payload: ProjectCreateRequest) -> dict[str, object]:
    return create_project(payload.name.strip(), payload.custom_prompt.strip(), payload.category.strip() or "默认")


@router.get("/projects/{project_id}")
def read_project(project_id: int) -> dict[str, object]:
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    project["videos"] = list_videos(project_id)
    project["segments"] = list_segments(project_id)
    project["schemes"] = list_schemes(project_id)
    return project


@router.patch("/projects/{project_id}")
def patch_project(project_id: int, payload: ProjectPatchRequest) -> dict[str, object]:
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    values = {key: value.strip() if isinstance(value, str) else value for key, value in payload.model_dump(exclude_unset=True).items()}
    if values.get("category") == "":
        values["category"] = "默认"
    updated = update_project(project_id, **values)
    if updated is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return updated


@router.delete("/projects/{project_id}")
def remove_project(project_id: int) -> dict[str, object]:
    if not delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"deleted": True, "project_id": project_id}


async def _save_project_video(project_id: int, file: UploadFile) -> dict[str, object]:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    ensure_data_dirs()
    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    video_dir = MATERIALS_DIR / "projects" / str(project_id) / uuid.uuid4().hex
    video_dir.mkdir(parents=True, exist_ok=True)
    local_path = video_dir / f"source{suffix}"
    with local_path.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            output.write(chunk)
    try:
        metadata = probe_video(local_path)
        thumbnail_path = create_thumbnail(local_path, video_dir / "thumbnail.jpg")
    except VideoProcessingError as exc:
        shutil.rmtree(video_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return add_video(
        project_id,
        {
            "name": file.filename or local_path.name,
            "local_path": str(local_path),
            "content_hash": file_sha256(local_path),
            "thumbnail_path": str(thumbnail_path),
            "duration_seconds": metadata["duration_seconds"],
            "width": metadata["width"],
            "height": metadata["height"],
            "fps": metadata["fps"],
            "status": "imported",
        },
    )


async def _process_video_pipeline(video_id: int) -> None:
    video = get_video(video_id)
    if video is None:
        return
    try:
        workspace_store.update_video(video_id, status="transcribing", error_message="")
        transcription = await transcribe_video_with_segments(Path(str(video["local_path"])), "")
        video = workspace_store.update_video(
            video_id,
            transcript=str(transcription["text"]),
            transcript_segments=json.dumps(transcription.get("segments", []), ensure_ascii=False),
            status="transcribed",
            error_message="",
        )
        workspace_store.update_video(video_id, status="segmenting", error_message="")
        segments = await segment_transcript(video)
        for segment in segments:
            thumbnail = Path(str(video["local_path"])).parent / f"{segment['segment_index']}.jpg"
            try:
                create_thumbnail(Path(str(video["local_path"])), thumbnail, seconds=float(segment["start_seconds"]))
                segment["thumbnail_path"] = str(thumbnail)
            except VideoProcessingError:
                segment["thumbnail_path"] = str(video.get("thumbnail_path") or "")
        workspace_store.replace_video_segments(video_id, segments)
        workspace_store.update_video(video_id, status="segmented", error_message="")
    except ProviderError as exc:
        workspace_store.update_video(video_id, status="failed", error_message=str(exc))
    except Exception as exc:  # noqa: BLE001
        workspace_store.update_video(video_id, status="failed", error_message=str(exc))


@router.post("/projects/{project_id}/videos/import")
async def import_project_video(
    project_id: int,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
) -> list[dict[str, object]]:
    imported: list[dict[str, object]] = []
    for file in files:
        video = await _save_project_video(project_id, file)
        imported.append(video)
        background_tasks.add_task(_process_video_pipeline, int(video["id"]))
    return imported


@router.get("/projects/{project_id}/videos")
def read_project_videos(project_id: int) -> list[dict[str, object]]:
    return list_videos(project_id)


@router.post("/videos/{video_id}/reanalyze")
def reanalyze_project_video(video_id: int, background_tasks: BackgroundTasks) -> dict[str, object]:
    video = get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found.")
    workspace_store.update_video(video_id, status="imported", error_message="")
    background_tasks.add_task(_process_video_pipeline, video_id)
    return workspace_store.update_video(video_id, status="transcribing", error_message="")


@router.post("/videos/{video_id}/transcribe")
async def transcribe_project_video(video_id: int, payload: ManualTranscribeRequest) -> dict[str, object]:
    video = get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found.")
    try:
        transcription = await transcribe_video_with_segments(Path(str(video["local_path"])), payload.manual_transcript)
    except ProviderError as exc:
        workspace_store.update_video(video_id, status="transcribe_failed", error_message=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return workspace_store.update_video(
        video_id,
        transcript=str(transcription["text"]),
        transcript_segments=json.dumps(transcription.get("segments", []), ensure_ascii=False),
        status="transcribed",
        error_message="",
    )


@router.post("/videos/{video_id}/segment")
async def segment_project_video(video_id: int) -> list[dict[str, object]]:
    video = get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found.")
    try:
        segments = await segment_transcript(video)
        for segment in segments:
            thumbnail = Path(str(video["local_path"])).parent / f"{segment['segment_index']}.jpg"
            try:
                create_thumbnail(Path(str(video["local_path"])), thumbnail, seconds=float(segment["start_seconds"]))
                segment["thumbnail_path"] = str(thumbnail)
            except VideoProcessingError:
                segment["thumbnail_path"] = str(video.get("thumbnail_path") or "")
        saved = workspace_store.replace_video_segments(video_id, segments)
        workspace_store.update_video(video_id, status="segmented", error_message="")
        return saved
    except ProviderError as exc:
        workspace_store.update_video(video_id, status="segment_failed", error_message=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/segments")
def read_segments(
    project_id: int,
    semantic_type: str = "",
    position_type: str = "",
    video_id: int | None = None,
) -> list[dict[str, object]]:
    return list_segments(
        project_id,
        semantic_type=semantic_type,
        position_type=position_type,
        video_id=video_id,
    )


@router.get("/segments/{segment_id}/preview")
def preview_segment(segment_id: int) -> FileResponse:
    segment = get_segment(segment_id)
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found.")
    try:
        preview_path = create_segment_preview(segment)
    except VideoProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(preview_path, media_type="video/mp4", filename=preview_path.name)


@router.get("/segments/{segment_id}/range-preview")
def preview_segment_range(
    segment_id: int,
    start_seconds: float = Query(ge=0),
    end_seconds: float = Query(gt=0),
) -> FileResponse:
    segment = get_segment(segment_id)
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found.")
    try:
        preview_path = create_segment_range_preview(segment, start_seconds=start_seconds, end_seconds=end_seconds)
    except VideoProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(preview_path, media_type="video/mp4", filename=preview_path.name)


@router.get("/segments/{segment_id}/thumbnail")
def segment_thumbnail(segment_id: int) -> FileResponse:
    segment = get_segment(segment_id)
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found.")
    thumbnail_path = Path(str(segment.get("thumbnail_path") or ""))
    if not thumbnail_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found.")
    return FileResponse(thumbnail_path, media_type="image/jpeg", filename=thumbnail_path.name)


@router.patch("/segments/{segment_id}")
def patch_segment(segment_id: int, payload: SegmentPatchRequest) -> dict[str, object]:
    segment = get_segment(segment_id)
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found.")
    values = payload.model_dump(exclude_unset=True)
    if "semantic_type" in values:
        invalid_tags = _split_multi_value(values["semantic_type"]) - ALLOWED_TAGS
        if invalid_tags:
            raise HTTPException(status_code=400, detail="Invalid semantic type.")
    if "position_type" in values:
        invalid_positions = _split_multi_value(values["position_type"]) - {"开头", "中间", "结尾"}
        if invalid_positions:
            raise HTTPException(status_code=400, detail="Invalid position type.")
    start = float(values.get("start_seconds", segment["start_seconds"]))
    end = float(values.get("end_seconds", segment["end_seconds"]))
    if end <= start:
        raise HTTPException(status_code=400, detail="End time must be greater than start time.")
    timing_changed = "start_seconds" in values or "end_seconds" in values
    if timing_changed and "text" not in values:
        refreshed_text = _infer_segment_text_for_timing(segment, start, end)
        if refreshed_text:
            values["text"] = refreshed_text
    if timing_changed:
        refreshed_thumbnail = _refresh_segment_thumbnail(segment, start)
        if refreshed_thumbnail:
            values["thumbnail_path"] = refreshed_thumbnail
    updated = update_segment(segment_id, **values)
    if updated is None:
        raise HTTPException(status_code=404, detail="Segment not found.")
    return updated


def _infer_segment_text_for_timing(segment: dict[str, object], start: float, end: float) -> str:
    video = get_video(int(segment["video_id"]))
    transcript_segments = _load_video_transcript_segments(video)
    if transcript_segments:
        selected = []
        for item in transcript_segments:
            item_start = float(item["start_seconds"])
            item_end = float(item["end_seconds"])
            overlap = min(end, item_end) - max(start, item_start)
            if overlap > 0:
                selected.append(str(item["text"]).strip())
        refreshed = "".join(selected).strip(" ，,。.!！?？\n\t")
        if refreshed:
            return refreshed
    transcript = str(video.get("transcript") or "").strip() if video else ""
    duration = float(video.get("duration_seconds") or 0) if video else 0
    if not transcript or duration <= 0:
        return str(segment.get("text") or "")
    start_index = max(0, min(len(transcript), int(len(transcript) * max(0, start) / duration)))
    end_index = max(start_index + 1, min(len(transcript), int(len(transcript) * max(0, end) / duration)))
    text = transcript[start_index:end_index].strip(" ，,。.!！?？\n\t")
    return text or str(segment.get("text") or "")


def _load_video_transcript_segments(video: dict[str, object] | None) -> list[dict[str, object]]:
    if not video:
        return []
    try:
        raw_items = json.loads(str(video.get("transcript_segments") or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(raw_items, list):
        return []
    segments: list[dict[str, object]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        try:
            start = float(raw.get("start_seconds"))
            end = float(raw.get("end_seconds"))
        except (TypeError, ValueError):
            continue
        text = str(raw.get("text") or "").strip()
        if end > start and text:
            segments.append({"start_seconds": start, "end_seconds": end, "text": text})
    return segments


def _refresh_segment_thumbnail(segment: dict[str, object], start: float) -> str:
    video_path = Path(str(segment.get("video_path") or ""))
    if not video_path.exists():
        return ""
    thumbnail = video_path.parent / f"segment_{int(segment['id'])}_{int(max(0, start) * 1000)}.jpg"
    try:
        create_thumbnail(video_path, thumbnail, seconds=max(0, start))
    except VideoProcessingError:
        return ""
    return str(thumbnail)


@router.post("/segments/{segment_id}/split")
def split_existing_segment(segment_id: int, payload: SegmentSplitRequest) -> dict[str, object]:
    segment = get_segment(segment_id)
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found.")
    start = float(segment["start_seconds"])
    end = float(segment["end_seconds"])
    min_duration = 0.3
    cut_points = sorted({round(float(point), 3) for point in payload.cut_points})
    if not cut_points:
        raise HTTPException(status_code=400, detail="请至少添加一个分割点。")
    if cut_points[0] <= start or cut_points[-1] >= end:
        raise HTTPException(status_code=400, detail="分割点必须在当前分镜范围内。")
    bounds = [start, *cut_points, end]
    for left, right in zip(bounds, bounds[1:]):
        if right - left < min_duration:
            raise HTTPException(status_code=400, detail="分割后每个小分镜至少保留 0.3 秒。")

    split_items: list[dict[str, object]] = []
    for index, (left, right) in enumerate(zip(bounds, bounds[1:]), start=1):
        text = _infer_segment_text_for_timing(segment, left, right)
        thumbnail = _refresh_segment_thumbnail(segment, left)
        split_items.append(
            {
                "segment_index": f"{segment['segment_index']}_split_{index:02d}",
                "start_seconds": left,
                "end_seconds": right,
                "text": text,
                "semantic_type": segment["semantic_type"],
                "position_type": segment["position_type"],
                "visual_description": segment.get("visual_description", ""),
                "thumbnail_path": thumbnail or segment.get("thumbnail_path", ""),
            }
        )

    result = split_segment(segment_id, split_items)
    if result is None:
        raise HTTPException(status_code=404, detail="Segment not found.")
    return result


@router.post("/segments/export")
def export_selected_segments(payload: SegmentExportRequest) -> dict[str, object]:
    segments = get_segments_by_ids(payload.segment_ids)
    if len(segments) != len(set(payload.segment_ids)):
        raise HTTPException(status_code=404, detail="Some selected segments were not found.")
    output_dir = Path(payload.output_dir).expanduser() if payload.output_dir else None
    try:
        export_paths = export_segment_files(segments, output_dir)
    except VideoProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "export_paths": [str(path) for path in export_paths],
        "export_root": str(export_paths[0].parents[1]) if export_paths else "",
        "segment_ids": [int(segment["id"]) for segment in segments],
    }


@router.delete("/segments")
def remove_selected_segments(payload: SegmentDeleteRequest) -> dict[str, object]:
    segments = get_segments_by_ids(payload.segment_ids)
    if len(segments) != len(set(payload.segment_ids)):
        raise HTTPException(status_code=404, detail="Some selected segments were not found.")
    removed_count = delete_segments(payload.segment_ids)
    return {"removed_count": removed_count, "segment_ids": payload.segment_ids}


@router.post("/projects/{project_id}/segments/dedupe")
def dedupe_project_segments(project_id: int, payload: SegmentDedupeRequest) -> dict[str, object]:
    segments = list_segments(project_id)
    signatures: dict[str, dict[str, object]] = {}
    duplicates: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    for segment in segments:
        try:
            signature = segment_av_signature(segment)
        except VideoProcessingError as exc:
            errors.append({"segment_id": int(segment["id"]), "error": str(exc)})
            continue
        kept = signatures.get(signature)
        if kept is None:
            signatures[signature] = segment
            continue
        duplicates.append(
            {
                "segment_id": int(segment["id"]),
                "kept_segment_id": int(kept["id"]),
                "video_name": str(segment.get("video_name") or ""),
                "text": str(segment.get("text") or ""),
            }
        )
    removed_ids = [int(item["segment_id"]) for item in duplicates]
    removed_count = 0 if payload.dry_run else delete_segments(removed_ids)
    return {
        "checked_count": len(segments),
        "duplicate_count": len(duplicates),
        "removed_count": removed_count,
        "duplicates": duplicates,
        "errors": errors,
    }


@router.get("/videos/{video_id}/thumbnail")
def video_thumbnail(video_id: int) -> FileResponse:
    video = get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found.")
    thumbnail_path = Path(str(video.get("thumbnail_path") or ""))
    if not thumbnail_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found.")
    return FileResponse(thumbnail_path, media_type="image/jpeg", filename=thumbnail_path.name)


@router.get("/videos/{video_id}/preview")
def video_preview(video_id: int) -> FileResponse:
    video = get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found.")
    video_path = Path(str(video.get("local_path") or ""))
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found.")
    media_type = mimetypes.guess_type(video_path.name)[0] or "video/mp4"
    return FileResponse(video_path, media_type=media_type, filename=video_path.name)


@router.get("/projects/{project_id}/schemes/recommendation")
def scheme_recommendation(project_id: int) -> dict[str, int]:
    videos = list_videos(project_id)
    segments = list_segments(project_id)
    return recommend_scheme_range(len(segments), len(videos))


@router.post("/projects/{project_id}/schemes/generate")
async def generate_project_schemes(project_id: int, payload: SchemeGenerateRequest) -> list[dict[str, object]]:
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    if payload.duration_min is not None and payload.duration_max is not None and payload.duration_max < payload.duration_min:
        raise HTTPException(status_code=400, detail="时长上限不能小于时长下限。")
    segments = list_segments(project_id)
    recommendation = recommend_scheme_range(len(segments), len(list_videos(project_id)))
    strategy_count = payload.strategy_count or recommendation["recommended_strategies"]
    outputs_per_strategy = payload.outputs_per_strategy or recommendation["recommended_outputs_per_strategy"]
    scheme_count = payload.scheme_count or min(30, strategy_count * outputs_per_strategy)
    segment_count = payload.segment_count or recommendation["recommended_segments"]
    try:
        schemes = await generate_schemes(
            project=project,
            segments=segments,
            target_duration=payload.target_duration,
            duration_min=payload.duration_min or 0,
            duration_max=payload.duration_max or 0,
            scheme_count=scheme_count,
            strategy_count=strategy_count,
            outputs_per_strategy=outputs_per_strategy,
            segment_count=segment_count,
            requirement_prompt=payload.requirement_prompt,
        )
        return create_scheme_set(project_id, schemes)
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/schemes")
def read_schemes(project_id: int) -> list[dict[str, object]]:
    return list_schemes(project_id)


@router.get("/schemes/{scheme_id}")
def read_scheme(scheme_id: int) -> dict[str, object]:
    scheme = get_scheme(scheme_id)
    if scheme is None:
        raise HTTPException(status_code=404, detail="Scheme not found.")
    return scheme


@router.get("/schemes/{scheme_id}/preview")
def scheme_preview(scheme_id: int) -> FileResponse:
    scheme = get_scheme(scheme_id)
    if scheme is None:
        raise HTTPException(status_code=404, detail="Scheme not found.")
    try:
        preview_path = create_scheme_preview(scheme_id, scheme["segments"])
    except VideoProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(preview_path, media_type="video/mp4", filename=preview_path.name)


@router.patch("/scheme-segments/{scheme_segment_id}")
def patch_scheme_segment(scheme_segment_id: int, payload: SchemeSegmentPatchRequest) -> dict[str, object]:
    if payload.action == "delete":
        scheme = delete_scheme_segment(scheme_segment_id)
    elif payload.action == "move_up":
        scheme = move_scheme_segment(scheme_segment_id, -1)
    elif payload.action == "move_down":
        scheme = move_scheme_segment(scheme_segment_id, 1)
    elif payload.segment_id:
        if get_segment(payload.segment_id) is None:
            raise HTTPException(status_code=404, detail="Replacement segment not found.")
        scheme = update_scheme_segment(scheme_segment_id, payload.segment_id)
    else:
        raise HTTPException(status_code=400, detail="No update action provided.")
    if scheme is None:
        raise HTTPException(status_code=404, detail="Scheme segment not found.")
    return scheme


@router.post("/schemes/{scheme_id}/export")
def export_scheme(scheme_id: int, payload: SchemeExportRequest | None = None) -> dict[str, object]:
    scheme = get_scheme(scheme_id)
    if scheme is None:
        raise HTTPException(status_code=404, detail="Scheme not found.")
    try:
        output_dir = Path(payload.output_dir).expanduser() if payload and payload.output_dir else None
        export_path = export_segments(scheme["segments"], output_dir=output_dir)
    except VideoProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "export_path": str(export_path),
        "segment_ids": [int(item["id"]) for item in scheme["segments"]],
    }


@router.post("/scripts/analyze", response_model=ScriptAnalyzeResponse)
async def analyze_script(payload: ScriptAnalyzeRequest) -> ScriptAnalyzeResponse:
    client = DeepSeekClient()
    try:
        result = await client.analyze_script(payload.script)
    except DeepSeekError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ScriptAnalyzeResponse(result=result)


@router.get("/materials", response_model=list[Material])
def get_materials() -> list[dict[str, object]]:
    return list_materials()


@router.get("/materials/{material_id}/file")
def preview_material(material_id: int) -> FileResponse:
    material = get_material(material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material not found.")
    file_path = Path(material["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Material file is missing.")
    return FileResponse(file_path, media_type="video/mp4", filename=file_path.name)


@router.get("/materials/{material_id}/source-file")
def preview_material_source(material_id: int) -> FileResponse:
    material = get_material(material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material not found.")
    source_path = Path(material["source_path"])
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Source video file is missing.")
    return FileResponse(source_path, media_type="video/mp4", filename=source_path.name)


@router.get("/materials/{material_id}/preview")
def preview_material_trim(
    material_id: int,
    start_seconds: float = Query(ge=0),
    end_seconds: float = Query(gt=0),
) -> FileResponse:
    try:
        preview_path = create_preview_clip(
            material_id,
            start_seconds=round(start_seconds, 3),
            end_seconds=round(end_seconds, 3),
        )
    except VideoProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(preview_path, media_type="video/mp4", filename=preview_path.name)


@router.patch("/materials/{material_id}/tag", response_model=Material)
def update_material_clip_tag(material_id: int, payload: MaterialTagRequest) -> dict[str, object]:
    material = get_material(material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material not found.")
    clean_tags = [tag.strip() for tag in payload.tags if tag.strip()]
    return update_material_tag(material_id=material_id, tag=",".join(clean_tags))


@router.patch("/materials/{material_id}/section", response_model=Material)
def update_material_clip_section(material_id: int, payload: MaterialSectionRequest) -> dict[str, object]:
    material = get_material(material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material not found.")
    clean_sections = [section.strip() for section in payload.sections if section.strip()]
    if any(section not in {"片头", "中间段", "结尾"} for section in clean_sections):
        raise HTTPException(status_code=400, detail="Invalid section.")
    return update_material_section(material_id=material_id, section=",".join(clean_sections))


@router.patch("/materials/{material_id}/trim", response_model=Material)
def trim_material_clip(material_id: int, payload: MaterialTrimRequest) -> dict[str, object]:
    try:
        return trim_material(
            material_id,
            start_seconds=round(payload.start_seconds, 3),
            end_seconds=round(payload.end_seconds, 3),
        )
    except VideoProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/materials/trim", response_model=list[Material])
def trim_selected_materials(payload: MaterialBatchTrimRequest) -> list[dict[str, object]]:
    try:
        return trim_materials(
            [
                {
                    "id": item.id,
                    "start_seconds": round(item.start_seconds, 3),
                    "end_seconds": round(item.end_seconds, 3),
                }
                for item in payload.items
            ]
        )
    except VideoProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/materials/export", response_model=ExportResponse)
def export_selected_materials(payload: ExportRequest) -> ExportResponse:
    try:
        export_path = export_materials(payload.material_ids)
    except VideoProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ExportResponse(export_path=str(export_path))


@router.post("/mix/draft", response_model=MixDraftResponse)
async def create_mix_draft(payload: MixDraftRequest) -> MixDraftResponse:
    client = DeepSeekClient()
    try:
        requirements = await client.generate_mix_requirements(payload.requirement_prompt)
    except DeepSeekError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    clean_requirements = _validate_mix_requirements(requirements)
    materials = list_materials_for_matching()
    selected_ids: list[int] = []
    draft_items: list[MixDraftItem] = []

    for requirement in clean_requirements:
        match = _find_matching_material(
            materials,
            used_ids=set(selected_ids),
            section=requirement.section,
            tag=requirement.tag,
        )
        if match is None:
            raise HTTPException(
                status_code=400,
                detail=f"没有找到匹配素材：位置={requirement.section}，tag={requirement.tag}",
            )
        material_id = int(match["id"])
        selected_ids.append(material_id)
        draft_items.append(
            MixDraftItem(
                section=requirement.section,
                tag=requirement.tag,
                material_id=material_id,
                source_name=str(match["source_name"]),
                duration_seconds=float(match["duration_seconds"]),
            )
        )

    return MixDraftResponse(requirements=draft_items)


@router.post("/mix/export", response_model=MixExportResponse)
def export_mix(payload: MixExportRequest) -> MixExportResponse:
    if payload.material_ids:
        selected_ids = payload.material_ids
    elif payload.requirements:
        selected_ids = _match_mix_requirements(payload.requirements)
    else:
        raise HTTPException(status_code=400, detail="请选择要导出的混剪片段。")

    try:
        export_path = export_materials(selected_ids)
    except VideoProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return MixExportResponse(export_path=str(export_path), material_ids=selected_ids)


def _match_mix_requirements(requirements: list[MixRequirement]) -> list[int]:
    materials = list_materials_for_matching()
    selected_ids: list[int] = []

    for requirement in requirements:
        match = _find_matching_material(
            materials,
            used_ids=set(selected_ids),
            section=requirement.section,
            tag=requirement.tag,
        )
        if match is None:
            raise HTTPException(
                status_code=400,
                detail=f"没有找到匹配素材：位置={requirement.section}，tag={requirement.tag}",
            )
        selected_ids.append(int(match["id"]))
    return selected_ids


@router.post("/videos/import", response_model=VideoImportResponse)
async def import_video(file: UploadFile = File(...), segment_seconds: int = 5) -> VideoImportResponse:
    if segment_seconds < 1 or segment_seconds > 60:
        raise HTTPException(status_code=400, detail="segment_seconds must be between 1 and 60.")

    try:
        source_path = await save_upload(file)
        clips = split_video(source_path, segment_seconds=segment_seconds)
    except VideoProcessingError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return VideoImportResponse(source_path=str(source_path), clip_count=len(clips), clips=clips)


def _find_matching_material(
    materials: list[dict[str, object]],
    *,
    used_ids: set[int],
    section: str,
    tag: str,
) -> dict[str, object] | None:
    for material in materials:
        material_id = int(material["id"])
        if material_id in used_ids:
            continue
        tags = _split_multi_value(str(material.get("tag", "")))
        sections = _split_multi_value(str(material.get("section", "")))
        if tag in tags and section in sections:
            return material
    return None


def _split_multi_value(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def _validate_mix_requirements(items: list[dict[str, str]]) -> list[MixRequirement]:
    requirements: list[MixRequirement] = []
    for item in items:
        if not isinstance(item, dict):
            raise HTTPException(status_code=502, detail="AI 混剪方案格式不正确，请调整需求后重试。")
        section = str(item.get("section", "")).strip()
        tag = str(item.get("tag", "")).strip()
        if section not in ALLOWED_SECTIONS:
            raise HTTPException(status_code=502, detail=f"AI 返回了无效位置：{section or '空'}")
        if tag not in ALLOWED_TAGS:
            raise HTTPException(status_code=502, detail=f"AI 返回了无效 tag：{tag or '空'}")
        requirements.append(MixRequirement(section=section, tag=tag))

    if not requirements:
        raise HTTPException(status_code=502, detail="AI 没有生成可用的混剪结构。")
    return requirements

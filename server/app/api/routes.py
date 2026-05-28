import asyncio
import json
import mimetypes
import shutil
import subprocess
import uuid
from pathlib import Path

import httpx
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
    add_asset,
    add_video,
    add_script,
    create_project,
    create_scheme_set,
    delete_material_mix_timeline,
    delete_project,
    delete_segments,
    delete_videos,
    delete_scheme_segment,
    duplicate_material_mix_timeline,
    get_project,
    get_asset,
    get_scheme,
    get_script,
    get_segment,
    get_material_mix_timeline,
    get_segments_by_ids,
    get_settings,
    get_video,
    init_workspace_db,
    add_material_mix_clip,
    create_material_mix_timeline,
    delete_material_mix_clip,
    list_projects,
    list_assets,
    list_ai_tasks,
    list_material_mix_timelines,
    list_schemes,
    list_scripts,
    list_segments,
    list_videos,
    move_scheme_segment,
    split_segment,
    update_material_mix_timeline,
    update_material_mix_clip,
    update_project,
    update_segment,
    update_scheme_segment,
    update_script,
    update_settings,
    update_asset,
)
from app.services import workspace_store
from app.services.providers import (
    ProviderError,
    analyze_product_visual,
    fallback_script_lines,
    generate_script_lines,
    generate_schemes,
    public_settings,
    recommend_scheme_range,
    segment_transcript,
    test_ai_settings,
    test_asr_settings,
    test_vision_settings,
    transcribe_video_with_segments,
)
from app.services.video_processor import (
    VideoProcessingError,
    _ffmpeg_filter_available,
    analyze_audio_loudness,
    clean_ffmpeg_error,
    create_preview_clip,
    create_segment_range_preview,
    create_segment_preview,
    create_scheme_preview,
    create_timeline_clip_preview,
    create_timeline_preview,
    create_thumbnail,
    export_segment_files,
    export_segments,
    export_timeline,
    file_sha256,
    probe_duration,
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
    target: str = Field(pattern="^(ai|vision|asr|tts)$")


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    custom_prompt: str = Field(default="", max_length=2000)
    custom_tags: str = Field(default="", max_length=2000)
    category: str = Field(default="默认", max_length=40)


class ProjectPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    custom_prompt: str | None = Field(default=None, max_length=2000)
    custom_tags: str | None = Field(default=None, max_length=2000)
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
    selling_points: str | None = None
    visual_tags: str | None = None
    visual_description: str | None = None
    source_mode: str | None = None
    keep_original_audio: bool | None = None


class SegmentExportRequest(BaseModel):
    segment_ids: list[int] = Field(min_length=1)
    output_dir: str | None = None
    export_tag: str = Field(default="", max_length=80)


class SegmentDeleteRequest(BaseModel):
    segment_ids: list[int] = Field(min_length=1)


class VideoDeleteRequest(BaseModel):
    video_ids: list[int] = Field(min_length=1)


class SegmentSplitRequest(BaseModel):
    cut_points: list[float] = Field(min_length=1, max_length=40)


class SchemeExportRequest(BaseModel):
    output_dir: str | None = None


class SegmentDedupeRequest(BaseModel):
    dry_run: bool = False


class VisualBatchAnalyzeRequest(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    only_missing: bool = True


class MaterialMixTimelineCreateRequest(BaseModel):
    project_id: int
    name: str = Field(default="素材混剪方案 01", min_length=1, max_length=80)


class MaterialMixTimelineGenerateRequest(BaseModel):
    project_id: int
    requirement_prompt: str = Field(default="", max_length=3000)
    target_clip_count: int = Field(default=8, ge=3, le=30)
    prefer_distinct_sources: bool = True


class MaterialMixTimelinePatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    is_favorite: bool | None = None


class MaterialMixClipCreateRequest(BaseModel):
    segment_id: int
    selection_note: str = Field(default="", max_length=500)


class MaterialMixClipPatchRequest(BaseModel):
    segment_id: int | None = None
    source_in: float | None = Field(default=None, ge=0)
    source_out: float | None = Field(default=None, gt=0)
    selection_note: str | None = Field(default=None, max_length=500)
    action: str | None = Field(default=None, pattern="^(move_up|move_down)$")


class MaterialMixExportRequest(BaseModel):
    output_dir: str | None = None
    audio_policy: str = Field(default="keep_original", pattern="^(keep_original|remove_original|enhance_voice|replace_with_voice|voice_over)$")
    normalize_loudness: bool = False
    target_lufs: float = Field(default=-14, ge=-24, le=-8)
    subtitle_preset_id: int | None = None
    burn_subtitles: bool = False
    bgm_asset_id: int | None = None
    voice_asset_id: int | None = None


class AssetImportResponse(BaseModel):
    assets: list[dict[str, object]]


class AssetPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    tags: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, object] | None = None


class ScriptGenerateRequest(BaseModel):
    project_id: int
    source_text: str = Field(min_length=1, max_length=50000)
    product_context: str = Field(default="", max_length=5000)
    title: str = Field(default="AI 裂变文案", max_length=80)


class DouyinScriptRequest(BaseModel):
    project_id: int
    douyin_url: str = Field(min_length=1, max_length=1000)
    product_context: str = Field(default="", max_length=5000)
    extracted_text: str = Field(default="", max_length=50000)


class ScriptPatchRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    source_text: str | None = Field(default=None, max_length=50000)
    product_context: str | None = Field(default=None, max_length=5000)
    lines: list[dict[str, object]] | None = None


class TtsGenerateRequest(BaseModel):
    project_id: int
    text: str = Field(min_length=1, max_length=20000)
    title: str = Field(default="AI 口播配音", max_length=80)
    voice: str = Field(default="", max_length=80)
    script_id: int | None = None


class VoiceTimelineRequest(BaseModel):
    project_id: int
    script_id: int
    voice_asset_id: int | None = None
    bgm_asset_id: int | None = None
    target_clip_count: int | None = Field(default=None, ge=1, le=80)
    name: str = Field(default="配音驱动成片", max_length=80)


class RemoveBgmRequest(BaseModel):
    asset_id: int | None = None
    video_id: int | None = None


MATERIAL_MIX_STRUCTURE = ["噱头引入", "痛点", "产品方案", "效果展示", "信任背书", "行动号召"]


def _split_multi_value(value: object) -> list[str]:
    return [item.strip() for item in str(value or "").replace("，", ",").replace("/", ",").split(",") if item.strip()]


def _segment_duration(segment: dict[str, object]) -> float:
    return max(0.0, float(segment.get("end_seconds") or 0) - float(segment.get("start_seconds") or 0))


def _segment_has_tag(segment: dict[str, object], tag: str) -> bool:
    return tag in _split_multi_value(segment.get("semantic_type"))


def _is_time_near_same_video(candidate: dict[str, object], selected: list[dict[str, object]]) -> bool:
    if not selected:
        return False
    previous = selected[-1]
    if int(candidate.get("video_id") or 0) != int(previous.get("video_id") or 0):
        return False
    candidate_start = float(candidate.get("start_seconds") or 0)
    previous_end = float(previous.get("end_seconds") or 0)
    return abs(candidate_start - previous_end) < 1.2


def _material_mix_score(
    candidate: dict[str, object],
    target_tag: str | None,
    selected: list[dict[str, object]],
    used_video_ids: set[int],
    prefer_distinct_sources: bool,
) -> float:
    score = 0.0
    if target_tag and _segment_has_tag(candidate, target_tag):
        score += 100.0
    duration = _segment_duration(candidate)
    if 2.0 <= duration <= 8.0:
        score += 12.0
    elif 1.0 <= duration <= 12.0:
        score += 6.0
    if prefer_distinct_sources and int(candidate.get("video_id") or 0) not in used_video_ids:
        score += 20.0
    if _is_time_near_same_video(candidate, selected):
        score -= 35.0
    if selected and int(candidate.get("video_id") or 0) == int(selected[-1].get("video_id") or 0):
        score -= 12.0
    return score


def _material_mix_note(
    candidate: dict[str, object],
    target_tag: str | None,
    selected: list[dict[str, object]],
    prefer_distinct_sources: bool,
) -> str:
    notes: list[str] = []
    if target_tag and _segment_has_tag(candidate, target_tag):
        notes.append(f"匹配「{target_tag}」")
    elif target_tag:
        notes.append(f"补齐「{target_tag}」结构位")
    if prefer_distinct_sources and selected and int(candidate.get("video_id") or 0) != int(selected[-1].get("video_id") or 0):
        notes.append("分散来源视频")
    if selected and not _is_time_near_same_video(candidate, selected):
        notes.append("避开相邻近时间片段")
    duration = _segment_duration(candidate)
    if 2.0 <= duration <= 8.0:
        notes.append("时长适合硬切")
    return "、".join(notes[:3]) or "可用片段补齐"


def _pick_material_mix_segment(
    segments: list[dict[str, object]],
    selected: list[dict[str, object]],
    target_tag: str | None,
    prefer_distinct_sources: bool,
) -> dict[str, object] | None:
    used_ids = {int(item["id"]) for item in selected}
    candidates = [item for item in segments if int(item["id"]) not in used_ids and _segment_duration(item) >= 0.3]
    if target_tag:
        tagged = [item for item in candidates if _segment_has_tag(item, target_tag)]
        if tagged:
            candidates = tagged
    if not candidates:
        return None
    used_video_ids = {int(item.get("video_id") or 0) for item in selected}
    return sorted(
        candidates,
        key=lambda item: (
            _material_mix_score(item, target_tag, selected, used_video_ids, prefer_distinct_sources),
            -float(item.get("start_seconds") or 0),
        ),
        reverse=True,
    )[0]


def _target_tags_from_requirement(requirement_prompt: str, target_clip_count: int) -> list[str]:
    mentioned = [tag for tag in MATERIAL_MIX_STRUCTURE if tag in requirement_prompt]
    base = mentioned or MATERIAL_MIX_STRUCTURE
    if target_clip_count <= len(base):
        return base[:target_clip_count]
    tags = list(base)
    index = 0
    while len(tags) < target_clip_count:
        tags.append(base[index % len(base)])
        index += 1
    return tags[:target_clip_count]


def _select_material_mix_segments(
    segments: list[dict[str, object]],
    target_clip_count: int,
    requirement_prompt: str,
    prefer_distinct_sources: bool,
) -> tuple[list[dict[str, object]], list[str], dict[int, str]]:
    warnings: list[str] = []
    selected: list[dict[str, object]] = []
    notes: dict[int, str] = {}
    count = min(max(3, target_clip_count), min(30, len(segments)))
    if count < target_clip_count:
        warnings.append(f"当前只有 {len(segments)} 个可用片段，已按可用数量生成。")
    target_tags = _target_tags_from_requirement(requirement_prompt, count)

    for tag in target_tags:
        picked = _pick_material_mix_segment(segments, selected, tag, prefer_distinct_sources)
        if picked is None:
            warnings.append(f"缺少「{tag}」片段，已跳过这个结构位。")
            continue
        if not _segment_has_tag(picked, tag):
            warnings.append(f"缺少「{tag}」片段，已用其他可用片段补齐。")
        notes[int(picked["id"])] = _material_mix_note(picked, tag, selected, prefer_distinct_sources)
        selected.append(picked)
        if len(selected) >= count:
            break

    while len(selected) < count:
        picked = _pick_material_mix_segment(segments, selected, None, prefer_distinct_sources)
        if picked is None:
            break
        notes[int(picked["id"])] = _material_mix_note(picked, None, selected, prefer_distinct_sources)
        selected.append(picked)

    return selected, list(dict.fromkeys(warnings)), notes


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
        if payload.target == "vision":
            return await test_vision_settings()
        if payload.target == "tts":
            return test_tts_settings()
        return await test_asr_settings()
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def test_tts_settings() -> dict[str, str]:
    settings = get_settings(masked=False)
    if not settings.get("tts_base_url") or not settings.get("tts_model"):
        return {"status": "ok", "message": "TTS 未配置，将使用静音占位音频跑通流程。"}
    return {"status": "ok", "message": f"TTS 配置已填写：{settings.get('tts_model')}"}


@router.get("/projects")
def get_projects() -> list[dict[str, object]]:
    return list_projects()


@router.post("/projects")
def post_project(payload: ProjectCreateRequest) -> dict[str, object]:
    project = create_project(payload.name.strip(), payload.custom_prompt.strip(), payload.category.strip() or "默认")
    if payload.custom_tags.strip():
        project = update_project(int(project["id"]), custom_tags=payload.custom_tags.strip()) or project
    return project


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


async def _save_project_video(
    project_id: int,
    file: UploadFile,
    *,
    asset_type: str = "finished_video",
    source_mode: str = "finished_mix",
) -> dict[str, object]:
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
            "asset_type": asset_type,
            "source_mode": source_mode,
            "has_voice": asset_type in {"finished_video", "talking_head"},
            "has_bgm": asset_type == "finished_video",
            "has_captions": asset_type == "finished_video",
            "keep_original_audio": asset_type in {"finished_video", "talking_head"},
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
        workspace_store.update_video(video_id, status="failed", error_message=clean_ffmpeg_error(str(exc)))
    except Exception as exc:  # noqa: BLE001
        workspace_store.update_video(video_id, status="failed", error_message=clean_ffmpeg_error(str(exc)))


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


@router.post("/projects/{project_id}/assets/import", response_model=AssetImportResponse)
async def import_project_assets(
    project_id: int,
    background_tasks: BackgroundTasks,
    asset_type: str = Query(default="finished_video"),
    files: list[UploadFile] = File(...),
) -> AssetImportResponse:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    allowed_asset_types = {
        "finished_video",
        "product_shot",
        "benefit_shot",
        "talking_head",
        "bgm",
        "voice",
        "subtitle_preset",
    }
    if asset_type not in allowed_asset_types:
        raise HTTPException(status_code=400, detail="不支持的素材类型。")
    imported: list[dict[str, object]] = []
    for file in files:
        if asset_type in {"finished_video", "product_shot", "benefit_shot", "talking_head"}:
            source_mode = "finished_mix" if asset_type in {"finished_video", "talking_head"} else "product_assets"
            video = await _save_project_video(project_id, file, asset_type=asset_type, source_mode=source_mode)
            imported.append({"kind": "video", **video})
            if asset_type in {"finished_video", "talking_head"}:
                background_tasks.add_task(_process_video_pipeline, int(video["id"]))
            else:
                workspace_store.replace_video_segments(
                    int(video["id"]),
                    [
                        {
                            "segment_index": "product_001",
                            "start_seconds": 0,
                            "end_seconds": float(video.get("duration_seconds") or 0),
                            "text": "",
                            "semantic_type": "产品方案" if asset_type == "product_shot" else "活动福利",
                            "position_type": "中间",
                            "visual_description": "",
                            "source_mode": "product_assets",
                            "keep_original_audio": 0,
                            "thumbnail_path": str(video.get("thumbnail_path") or ""),
                        }
                    ],
                )
        else:
            path = await save_upload(file)
            duration = 0.0
            try:
                duration = probe_video(path)["duration_seconds"] if asset_type != "subtitle_preset" else 0.0
            except VideoProcessingError:
                try:
                    duration = probe_duration(path)
                except VideoProcessingError:
                    duration = 0.0
            asset = add_asset(
                project_id=project_id,
                asset_type=asset_type,
                name=file.filename or path.name,
                file_path=path,
                source_path=path,
                metadata={"original_name": file.filename or path.name},
                duration_seconds=duration,
            )
            imported.append(asset)
    return AssetImportResponse(assets=imported)


@router.get("/projects/{project_id}/assets")
def read_project_assets(project_id: int, asset_type: str = "") -> list[dict[str, object]]:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return list_assets(project_id, asset_type)


@router.get("/projects/{project_id}/ai-tasks")
def read_project_ai_tasks(project_id: int, task_type: str = "") -> list[dict[str, object]]:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return list_ai_tasks(project_id, task_type)


@router.get("/assets/{asset_id}/file")
def read_asset_file(asset_id: int) -> FileResponse:
    asset = get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found.")
    file_path = Path(str(asset.get("file_path") or ""))
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Asset file is missing.")
    media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return FileResponse(file_path, media_type=media_type, filename=file_path.name)


@router.post("/assets/{asset_id}/analyze-audio")
def analyze_asset_audio(asset_id: int) -> dict[str, object]:
    asset = get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found.")
    if str(asset.get("asset_type") or "") not in {"bgm", "voice", "finished_video", "talking_head"}:
        raise HTTPException(status_code=400, detail="该素材类型不支持响度分析。")
    file_path = Path(str(asset.get("file_path") or ""))
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Asset file is missing.")
    try:
        analysis = analyze_audio_loudness(file_path)
    except VideoProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    metadata = dict(asset.get("metadata") or {})
    metadata["audio_analysis"] = analysis
    updated = update_asset(
        asset_id,
        metadata=metadata,
        duration_seconds=float(analysis.get("duration_seconds") or asset.get("duration_seconds") or 0),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Asset not found.")
    return updated


@router.patch("/assets/{asset_id}")
def patch_asset(asset_id: int, payload: AssetPatchRequest) -> dict[str, object]:
    asset = get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found.")
    updated = update_asset(asset_id, **payload.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="Asset not found.")
    return updated


@router.post("/segments/{segment_id}/analyze-visual")
async def analyze_segment_visual(segment_id: int) -> dict[str, object]:
    segment = get_segment(segment_id)
    if segment is None:
        raise HTTPException(status_code=404, detail="Segment not found.")
    project = get_project(int(segment["project_id"]))
    try:
        result = await analyze_product_visual(segment, str(project.get("custom_tags") or "") if project else "")
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    updated = update_segment(
        segment_id,
        visual_description=result["visual_description"],
        selling_points=",".join(result["selling_points"]),
        visual_tags=",".join(result["visual_tags"]),
        position_type=",".join(result["suitable_positions"]),
        source_mode="product_assets",
    )
    return {"analysis": result, "segment": updated}


@router.post("/projects/{project_id}/segments/analyze-visual")
async def analyze_project_visual_segments(project_id: int, payload: VisualBatchAnalyzeRequest) -> dict[str, object]:
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    candidates = [
        segment
        for segment in list_segments(project_id)
        if str(segment.get("source_mode") or "") == "product_assets"
        and (not payload.only_missing or not str(segment.get("visual_description") or "").strip())
    ][: payload.limit]
    analyzed: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    for segment in candidates:
        try:
            result = await analyze_product_visual(segment, str(project.get("custom_tags") or ""))
            updated = update_segment(
                int(segment["id"]),
                visual_description=result["visual_description"],
                selling_points=",".join(result["selling_points"]),
                visual_tags=",".join(result["visual_tags"]),
                position_type=",".join(result["suitable_positions"]),
                source_mode="product_assets",
            )
            analyzed.append({"analysis": result, "segment": updated})
        except ProviderError as exc:
            errors.append({"segment_id": int(segment["id"]), "error": str(exc)})
    return {
        "checked_count": len(candidates),
        "analyzed_count": len(analyzed),
        "error_count": len(errors),
        "analyzed": analyzed,
        "errors": errors,
    }


@router.get("/projects/{project_id}/videos")
def read_project_videos(project_id: int) -> list[dict[str, object]]:
    return list_videos(project_id)


@router.delete("/videos")
def remove_selected_videos(payload: VideoDeleteRequest) -> dict[str, object]:
    videos = [get_video(video_id) for video_id in payload.video_ids]
    missing = [video_id for video_id, video in zip(payload.video_ids, videos) if video is None]
    if missing:
        raise HTTPException(status_code=404, detail="Some selected videos were not found.")
    removed_count = delete_videos(payload.video_ids)
    return {"removed_count": removed_count, "video_ids": payload.video_ids}


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
        detail = clean_ffmpeg_error(str(exc))
        workspace_store.update_video(video_id, status="transcribe_failed", error_message=detail)
        raise HTTPException(status_code=400, detail=detail) from exc
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
        detail = clean_ffmpeg_error(str(exc))
        workspace_store.update_video(video_id, status="segment_failed", error_message=detail)
        raise HTTPException(status_code=400, detail=detail) from exc


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
        invalid_tags = set(_split_multi_value(values["semantic_type"])) - ALLOWED_TAGS
        if invalid_tags:
            raise HTTPException(status_code=400, detail="Invalid semantic type.")
    if "position_type" in values:
        invalid_positions = set(_split_multi_value(values["position_type"])) - {"开头", "中间", "结尾"}
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
        export_paths = export_segment_files(segments, output_dir, payload.export_tag)
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


@router.post("/material-mix/timelines")
def create_material_mix(payload: MaterialMixTimelineCreateRequest) -> dict[str, object]:
    timeline = create_material_mix_timeline(payload.project_id, payload.name)
    if not timeline:
        raise HTTPException(status_code=404, detail="Project not found.")
    return timeline


@router.get("/material-mix/timelines")
def read_material_mix_timelines(project_id: int | None = None) -> list[dict[str, object]]:
    return list_material_mix_timelines(project_id)


@router.post("/material-mix/timelines/generate")
def generate_material_mix_timeline(payload: MaterialMixTimelineGenerateRequest) -> dict[str, object]:
    project = get_project(payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    segments = list_segments(payload.project_id)
    if not segments:
        raise HTTPException(status_code=400, detail="当前项目还没有可用语义片段，请先在导入分析或片段库完成切片。")
    selected_segments, warnings, generation_notes = _select_material_mix_segments(
        segments,
        payload.target_clip_count,
        payload.requirement_prompt,
        payload.prefer_distinct_sources,
    )
    if not selected_segments:
        raise HTTPException(status_code=400, detail="没有找到可用于素材混剪的有效片段。")

    timeline_index = len(list_material_mix_timelines(payload.project_id)) + 1
    timeline = create_material_mix_timeline(payload.project_id, f"素材混剪自动方案 {timeline_index:02d}")
    if timeline is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    for segment in selected_segments:
        note = generation_notes.get(int(segment["id"]), "规则自动选择")
        next_timeline = add_material_mix_clip(int(timeline["id"]), int(segment["id"]), note)
        if next_timeline is not None:
            timeline = next_timeline
    timeline = get_material_mix_timeline(int(timeline["id"])) or timeline
    timeline["generation_warnings"] = warnings
    timeline["generation_notes"] = {
        int(clip["clip_id"]): str(clip.get("selection_note") or generation_notes.get(int(clip["segment_id"]), "规则自动选择"))
        for clip in timeline.get("clips", [])
    }
    timeline["requirement_prompt"] = payload.requirement_prompt
    return timeline


@router.get("/material-mix/timelines/{timeline_id}")
def read_material_mix_timeline(timeline_id: int) -> dict[str, object]:
    timeline = get_material_mix_timeline(timeline_id)
    if timeline is None:
        raise HTTPException(status_code=404, detail="Timeline not found.")
    return timeline


@router.patch("/material-mix/timelines/{timeline_id}")
def patch_material_mix_timeline(timeline_id: int, payload: MaterialMixTimelinePatchRequest) -> dict[str, object]:
    timeline = update_material_mix_timeline(
        timeline_id,
        name=payload.name,
        is_favorite=payload.is_favorite,
    )
    if timeline is None:
        raise HTTPException(status_code=404, detail="Timeline not found or invalid name.")
    return timeline


@router.delete("/material-mix/timelines/{timeline_id}")
def remove_material_mix_timeline(timeline_id: int) -> dict[str, object]:
    deleted = delete_material_mix_timeline(timeline_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Timeline not found.")
    return deleted


@router.post("/material-mix/timelines/{timeline_id}/duplicate")
def duplicate_material_mix(timeline_id: int) -> dict[str, object]:
    timeline = duplicate_material_mix_timeline(timeline_id)
    if timeline is None:
        raise HTTPException(status_code=404, detail="Timeline not found.")
    return timeline


@router.post("/material-mix/timelines/{timeline_id}/clips")
def add_material_mix_timeline_clip(timeline_id: int, payload: MaterialMixClipCreateRequest) -> dict[str, object]:
    if get_segment(payload.segment_id) is None:
        raise HTTPException(status_code=404, detail="Segment not found.")
    timeline = add_material_mix_clip(timeline_id, payload.segment_id, payload.selection_note)
    if timeline is None:
        raise HTTPException(status_code=404, detail="Timeline not found or segment is outside this project.")
    return timeline


@router.patch("/material-mix/timelines/{timeline_id}/clips/{clip_id}")
def patch_material_mix_timeline_clip(timeline_id: int, clip_id: int, payload: MaterialMixClipPatchRequest) -> dict[str, object]:
    if payload.segment_id is not None:
        replacement = get_segment(payload.segment_id)
        timeline = get_material_mix_timeline(timeline_id)
        if timeline is None:
            raise HTTPException(status_code=404, detail="Timeline not found.")
        if replacement is None:
            raise HTTPException(status_code=404, detail="Segment not found.")
        if int(replacement["project_id"]) != int(timeline["project_id"]):
            raise HTTPException(status_code=400, detail="替换片段不属于当前项目。")
    if payload.source_in is not None or payload.source_out is not None:
        timeline = get_material_mix_timeline(timeline_id)
        if timeline is None:
            raise HTTPException(status_code=404, detail="Timeline not found.")
        current_clip = next((item for item in timeline["clips"] if int(item["clip_id"]) == clip_id), None)
        if current_clip is None:
            raise HTTPException(status_code=404, detail="Timeline clip not found.")
        next_in = float(payload.source_in if payload.source_in is not None else current_clip["source_in"])
        next_out = float(payload.source_out if payload.source_out is not None else current_clip["source_out"])
        if next_out <= next_in:
            raise HTTPException(status_code=400, detail="片段结束时间必须大于开始时间。")
        if next_out - next_in < 0.3:
            raise HTTPException(status_code=400, detail="时间线片段至少保留 0.3 秒。")
    timeline = update_material_mix_clip(
        timeline_id,
        clip_id,
        segment_id=payload.segment_id,
        source_in=payload.source_in,
        source_out=payload.source_out,
        selection_note=payload.selection_note,
        action=payload.action,
    )
    if timeline is None:
        raise HTTPException(status_code=404, detail="Timeline clip not found or invalid timing.")
    return timeline


@router.delete("/material-mix/timelines/{timeline_id}/clips/{clip_id}")
def remove_material_mix_timeline_clip(timeline_id: int, clip_id: int) -> dict[str, object]:
    timeline = delete_material_mix_clip(timeline_id, clip_id)
    if timeline is None:
        raise HTTPException(status_code=404, detail="Timeline clip not found.")
    return timeline


@router.get("/material-mix/timelines/{timeline_id}/clips/{clip_id}/preview")
def preview_material_mix_timeline_clip(timeline_id: int, clip_id: int) -> FileResponse:
    timeline = get_material_mix_timeline(timeline_id)
    if timeline is None:
        raise HTTPException(status_code=404, detail="Timeline not found.")
    clip = next((item for item in timeline["clips"] if int(item["clip_id"]) == clip_id), None)
    if clip is None:
        raise HTTPException(status_code=404, detail="Timeline clip not found.")
    try:
        preview_path = create_timeline_clip_preview(clip)
    except VideoProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(preview_path, media_type="video/mp4", filename=preview_path.name)


@router.get("/material-mix/timelines/{timeline_id}/preview")
def preview_material_mix_timeline(timeline_id: int) -> FileResponse:
    timeline = get_material_mix_timeline(timeline_id)
    if timeline is None:
        raise HTTPException(status_code=404, detail="Timeline not found.")
    try:
        preview_path = create_timeline_preview(timeline)
    except VideoProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(preview_path, media_type="video/mp4", filename=preview_path.name)


@router.post("/material-mix/timelines/{timeline_id}/export")
def export_material_mix_timeline(timeline_id: int, payload: MaterialMixExportRequest | None = None) -> dict[str, object]:
    timeline = get_material_mix_timeline(timeline_id)
    if timeline is None:
        raise HTTPException(status_code=404, detail="Timeline not found.")
    try:
        if payload:
            timeline = update_material_mix_timeline(
                timeline_id,
                voice_asset_id=payload.voice_asset_id,
                bgm_asset_id=payload.bgm_asset_id,
                subtitle_preset_id=payload.subtitle_preset_id,
                audio_policy=payload.audio_policy,
                normalize_loudness=payload.normalize_loudness,
                target_lufs=payload.target_lufs,
                burn_subtitles=payload.burn_subtitles,
            ) or timeline
        output_dir = Path(payload.output_dir).expanduser() if payload and payload.output_dir else None
        export_path = export_timeline(timeline, output_dir=output_dir)
    except VideoProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    requested_burn_subtitles = bool(payload.burn_subtitles) if payload else bool(int(timeline.get("burn_subtitles") or 0))
    warnings = []
    if requested_burn_subtitles and not _ffmpeg_filter_available("subtitles"):
        warnings.append("当前 FFmpeg 没有 subtitles 滤镜，已跳过字幕烧录；请安装支持 libass 的 FFmpeg 后重试字幕内嵌导出。")
    return {
        "export_path": str(export_path),
        "timeline_id": timeline_id,
        "clip_ids": [int(item["clip_id"]) for item in timeline["clips"]],
        "warnings": warnings,
    }


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


@router.get("/projects/{project_id}/scripts")
def read_project_scripts(project_id: int) -> list[dict[str, object]]:
    if get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return list_scripts(project_id)


@router.post("/scripts/generate-variants")
async def generate_script_variants(payload: ScriptGenerateRequest) -> dict[str, object]:
    if get_project(payload.project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    try:
        lines = await generate_script_lines(
            source_text=payload.source_text,
            product_context=payload.product_context,
            source_type="manual",
        )
    except ProviderError:
        lines = fallback_script_lines(payload.source_text)
    script = add_script(
        project_id=payload.project_id,
        title=payload.title,
        source_type="manual",
        source_text=payload.source_text,
        product_context=payload.product_context,
        lines=lines,
    )
    return script


@router.post("/scripts/from-douyin")
async def generate_script_from_douyin(payload: DouyinScriptRequest) -> dict[str, object]:
    if get_project(payload.project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    source_text = payload.extracted_text.strip() or f"抖音链接：{payload.douyin_url}"
    try:
        lines = await generate_script_lines(
            source_text=source_text,
            product_context=payload.product_context,
            source_type="douyin",
        )
    except ProviderError:
        lines = fallback_script_lines(source_text)
    script = add_script(
        project_id=payload.project_id,
        title="抖音结构改写文案",
        source_type="douyin",
        source_text=source_text,
        product_context=payload.product_context,
        lines=lines,
    )
    return script


@router.patch("/scripts/{script_id}")
def patch_script(script_id: int, payload: ScriptPatchRequest) -> dict[str, object]:
    script = get_script(script_id)
    if script is None:
        raise HTTPException(status_code=404, detail="Script not found.")
    values = payload.model_dump(exclude_unset=True)
    if "lines" in values and values["lines"] is not None:
        values["lines"] = _normalize_script_patch_lines(values["lines"])
    updated = update_script(script_id, **values)
    if updated is None:
        raise HTTPException(status_code=404, detail="Script not found.")
    return updated


@router.post("/tts/generate")
async def generate_tts_voice(payload: TtsGenerateRequest) -> dict[str, object]:
    if get_project(payload.project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    try:
        audio_path, metadata = await _generate_tts_audio(payload)
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    duration = metadata.get("duration_seconds", 0.0)
    if not duration:
        try:
            duration = probe_duration(audio_path)
        except VideoProcessingError:
            duration = 0.0
    asset = add_asset(
        project_id=payload.project_id,
        asset_type="voice",
        name=payload.title,
        file_path=audio_path,
        source_path=audio_path,
        tags=payload.voice or "",
        metadata={**metadata, "script_id": payload.script_id, "text": payload.text},
        duration_seconds=float(duration),
    )
    return asset


@router.post("/timelines/generate-from-voice")
def generate_timeline_from_voice(payload: VoiceTimelineRequest) -> dict[str, object]:
    project = get_project(payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    script = get_script(payload.script_id)
    if script is None or int(script["project_id"]) != payload.project_id:
        raise HTTPException(status_code=404, detail="Script not found.")
    segments = list_segments(payload.project_id)
    if not segments:
        raise HTTPException(status_code=400, detail="当前项目还没有可用素材片段。")
    lines = list(script.get("lines") or [])
    selected = _match_segments_for_script(lines, segments, payload.target_clip_count)
    if not selected:
        raise HTTPException(status_code=400, detail="没有匹配到可用素材片段。")
    timeline = create_material_mix_timeline(payload.project_id, payload.name or "配音驱动成片")
    if not timeline:
        raise HTTPException(status_code=404, detail="Project not found.")
    notes_by_segment_id: dict[int, str] = {}
    for index, segment in enumerate(selected):
        line = lines[index] if index < len(lines) and isinstance(lines[index], dict) else {}
        note = _script_segment_note(index, line, segment)
        next_timeline = add_material_mix_clip(int(timeline["id"]), int(segment["id"]), note)
        if next_timeline is not None:
            timeline = next_timeline
            clip = timeline.get("clips", [])[-1] if timeline.get("clips") else None
            if isinstance(clip, dict):
                source_in = float(clip["source_in"])
                source_out = float(clip["source_out"])
                try:
                    desired_duration = float(line.get("estimated_duration") or source_out - source_in)
                except (TypeError, ValueError):
                    desired_duration = source_out - source_in
                desired_duration = max(0.3, desired_duration)
                next_out = min(source_out, source_in + desired_duration)
                if next_out - source_in >= 0.3 and next_out < source_out:
                    trimmed = update_material_mix_clip(int(timeline["id"]), int(clip["clip_id"]), source_in=source_in, source_out=next_out)
                    if trimmed is not None:
                        timeline = trimmed
                notes_by_segment_id[int(segment["id"])] = note
    timeline = update_material_mix_timeline(
        int(timeline["id"]),
        voice_asset_id=payload.voice_asset_id,
        bgm_asset_id=payload.bgm_asset_id,
        audio_policy="replace_with_voice" if payload.voice_asset_id else "remove_original",
        normalize_loudness=True,
        target_lufs=-14,
        burn_subtitles=True,
    ) or timeline
    timeline["generation_notes"] = {
        int(clip["clip_id"]): str(clip.get("selection_note") or notes_by_segment_id.get(int(clip["segment_id"]), "按口播语义匹配素材"))
        for clip in timeline.get("clips", [])
    }
    return timeline


@router.post("/audio/remove-bgm")
def remove_bgm(payload: RemoveBgmRequest) -> dict[str, object]:
    if not payload.asset_id and not payload.video_id:
        raise HTTPException(status_code=400, detail="请提供要处理的素材或成片。")
    raise HTTPException(
        status_code=501,
        detail="去 BGM 能力未启用：当前版本没有本地 AI Worker，无法创建人声/BGM 分离任务。",
    )


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


async def _generate_tts_audio(payload: TtsGenerateRequest) -> tuple[Path, dict[str, object]]:
    settings = get_settings(masked=False)
    tts_dir = TMP_DIR / "tts" / uuid.uuid4().hex
    tts_dir.mkdir(parents=True, exist_ok=True)
    output_path = tts_dir / "voice.mp3"
    base_url = settings.get("tts_base_url", "").strip().rstrip("/")
    model = settings.get("tts_model", "").strip()
    if base_url and model:
        headers: dict[str, str] = {}
        api_key = settings.get("tts_api_key", "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        voice = payload.voice or settings.get("tts_voice") or "alloy"
        audio_format = settings.get("tts_format") or "mp3"
        url = f"{base_url}/audio/speech"
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                url,
                headers=headers,
                json={
                    "model": model,
                    "voice": voice,
                    "input": payload.text,
                    "response_format": audio_format,
                },
            )
        if response.status_code >= 400:
            raise ProviderError(f"TTS API 请求失败：{response.status_code} {response.text}")
        output_path = output_path.with_suffix(f".{audio_format}")
        output_path.write_bytes(response.content)
        return output_path, {"provider": "compatible_tts", "voice": voice}

    duration = max(1.5, min(180.0, len(payload.text) / 5.2))
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-t",
            f"{duration:.2f}",
            "-c:a",
            "mp3",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ProviderError(clean_ffmpeg_error(result.stderr.strip() or "生成占位配音失败。"))
    return output_path, {
        "provider": "placeholder",
        "duration_seconds": duration,
        "message": "未配置 TTS Base URL/模型，已生成静音占位音频用于跑通时间线流程。",
    }


def _match_segments_for_script(
    lines: list[object],
    segments: list[dict[str, object]],
    target_clip_count: int | None,
) -> list[dict[str, object]]:
    limit = target_clip_count or len(lines) or min(8, len(segments))
    selected: list[dict[str, object]] = []
    used_ids: set[int] = set()
    for line in lines[:limit]:
        line_data = line if isinstance(line, dict) else {}
        semantic = str(line_data.get("semantic_type") or "")
        selling_points = _split_multi_value(",".join(str(item) for item in line_data.get("selling_points", []))) if isinstance(line_data.get("selling_points"), list) else _split_multi_value(line_data.get("selling_points"))
        visual_needs = _split_multi_value(",".join(str(item) for item in line_data.get("visual_needs", []))) if isinstance(line_data.get("visual_needs"), list) else _split_multi_value(line_data.get("visual_needs"))
        candidates = [segment for segment in segments if int(segment["id"]) not in used_ids]
        if not candidates:
            break
        picked = max(
            candidates,
            key=lambda segment: _script_segment_score(segment, semantic, selling_points, visual_needs),
        )
        selected.append(picked)
        used_ids.add(int(picked["id"]))
    if not selected:
        selected = segments[: min(limit, len(segments))]
    return selected


def _normalize_script_patch_lines(lines: list[dict[str, object]]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for index, raw in enumerate(lines, start=1):
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        semantic_type = str(raw.get("semantic_type") or "过渡").strip()
        if semantic_type not in ALLOWED_TAGS:
            semantic_type = "过渡"
        try:
            estimated_duration = float(raw.get("estimated_duration") or max(1.5, len(text) / 5.2))
        except (TypeError, ValueError):
            estimated_duration = max(1.5, len(text) / 5.2)
        normalized.append(
            {
                "line_index": int(raw.get("line_index") or index),
                "text": text,
                "semantic_type": semantic_type,
                "selling_points": _split_multi_value(",".join(str(item) for item in raw.get("selling_points", []))) if isinstance(raw.get("selling_points"), list) else _split_multi_value(raw.get("selling_points")),
                "visual_needs": _split_multi_value(",".join(str(item) for item in raw.get("visual_needs", []))) if isinstance(raw.get("visual_needs"), list) else _split_multi_value(raw.get("visual_needs")),
                "estimated_duration": round(max(0.8, estimated_duration), 1),
            }
        )
    return normalized


def _script_segment_score(segment: dict[str, object], semantic: str, selling_points: list[str], visual_needs: list[str]) -> float:
    score = 0.0
    if semantic and semantic in _split_multi_value(segment.get("semantic_type")):
        score += 5
    segment_text = " ".join(
        [
            str(segment.get("text") or ""),
            str(segment.get("visual_description") or ""),
            str(segment.get("selling_points") or ""),
            str(segment.get("visual_tags") or ""),
            str(segment.get("semantic_type") or ""),
        ]
    )
    for value in selling_points:
        if value and value in segment_text:
            score += 3
    for value in visual_needs:
        if value and value in segment_text:
            score += 2
    if str(segment.get("source_mode") or "") == "product_assets":
        score += 1
    return score


def _script_segment_note(index: int, line: dict[str, object], segment: dict[str, object]) -> str:
    line_text = str(line.get("text") or "").strip()
    semantic = str(line.get("semantic_type") or "").strip()
    selling_points = _split_multi_value(",".join(str(item) for item in line.get("selling_points", []))) if isinstance(line.get("selling_points"), list) else _split_multi_value(line.get("selling_points"))
    visual_needs = _split_multi_value(",".join(str(item) for item in line.get("visual_needs", []))) if isinstance(line.get("visual_needs"), list) else _split_multi_value(line.get("visual_needs"))
    segment_tags = set(
        _split_multi_value(segment.get("semantic_type"))
        + _split_multi_value(segment.get("selling_points"))
        + _split_multi_value(segment.get("visual_tags"))
    )
    matched = [value for value in selling_points + visual_needs if value in segment_tags]
    parts = [f"匹配口播第 {index + 1} 句"]
    if line_text:
        parts.append(f"「{line_text[:24]}」")
    if semantic:
        parts.append(f"语义：{semantic}")
    if matched:
        parts.append(f"命中：{' / '.join(matched[:4])}")
    elif str(segment.get("source_mode") or "") == "product_assets":
        parts.append("优先使用产品素材")
    return "，".join(parts)

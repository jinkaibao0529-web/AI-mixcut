import json
import math
import re
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

from app.services.workspace_store import get_settings
from app.services.video_processor import VideoProcessingError, extract_audio_for_whisper, extract_pcm_16k, extract_wav_16k


SEGMENT_TYPES = [
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
]

POSITION_TYPES = ["开头", "中间", "结尾"]


class ProviderError(RuntimeError):
    pass


def public_settings() -> dict[str, str]:
    return get_settings(masked=True)


async def test_ai_settings() -> dict[str, str]:
    settings = get_settings(masked=False)
    _require_ai_settings(settings)
    await _chat_completion(settings, "只回复 JSON：{\"ok\":true}", json_mode=True)
    return {"status": "ok", "message": "AI API 可用"}


async def test_asr_settings() -> dict[str, str]:
    settings = get_settings(masked=False)
    provider = settings.get("asr_provider", "manual_transcript")
    if provider == "local_whisper":
        binary_path = _resolve_whisper_binary(settings)
        model_path = _resolve_whisper_model(settings)
        return {"status": "ok", "message": f"本地 Whisper 可用：{Path(binary_path).name}，模型 {Path(model_path).name}"}
    if provider == "manual_transcript":
        return {"status": "ok", "message": "手动转录模式可用"}
    if provider == "whisper_compatible":
        if not settings.get("asr_base_url") or not settings.get("asr_model"):
            raise ProviderError("请填写 ASR Base URL 和模型名。")
        return {"status": "ok", "message": "Whisper 兼容配置格式可用"}
    if provider == "aliyun_nls":
        missing = [
            label
            for key, label in (
                ("aliyun_access_key_id", "AccessKey ID"),
                ("aliyun_access_key_secret", "AccessKey Secret"),
                ("aliyun_app_key", "NLS AppKey"),
            )
            if not settings.get(key)
        ]
        if missing:
            raise ProviderError(f"阿里云 ASR 缺少配置：{', '.join(missing)}")
        return {"status": "ok", "message": "阿里云 ASR 配置已填写"}
    raise ProviderError(f"不支持的 ASR 提供商：{provider}")


async def transcribe_video(video_path: Path, manual_transcript: str = "") -> str:
    result = await transcribe_video_with_segments(video_path, manual_transcript)
    return str(result["text"])


async def transcribe_video_with_segments(video_path: Path, manual_transcript: str = "") -> dict[str, Any]:
    settings = get_settings(masked=False)
    provider = settings.get("asr_provider", "manual_transcript")
    if provider == "local_whisper":
        return await _transcribe_local_whisper(settings, video_path)
    if provider == "manual_transcript":
        if not manual_transcript.strip():
            raise ProviderError("当前是手动转录模式，请粘贴视频文案。")
        return {"text": manual_transcript.strip(), "segments": [], "has_timestamps": False}
    if provider == "whisper_compatible":
        text = await _transcribe_whisper(settings, video_path)
        return {"text": text, "segments": [], "has_timestamps": False}
    if provider == "aliyun_nls":
        text = await _transcribe_aliyun_nls(settings, video_path)
        return {"text": text, "segments": [], "has_timestamps": False}
    raise ProviderError(f"不支持的 ASR 提供商：{provider}")


async def segment_transcript(video: dict[str, Any]) -> list[dict[str, Any]]:
    transcript = str(video.get("transcript") or "").strip()
    if not transcript:
        raise ProviderError("视频还没有转录文本。")
    transcript_segments = _load_transcript_segments(video.get("transcript_segments"))
    if transcript_segments:
        return await _segment_timestamped_transcript(video, transcript_segments)

    duration = float(video.get("duration_seconds") or 0)
    settings = get_settings(masked=False)
    _require_ai_settings(settings)

    prompt = (
        "你是专业的视频内容分析专家。请把电商短视频转录文本切分成语义片段。"
        "只输出 JSON 对象，不要输出 Markdown，格式为 {\"segments\":[...]}。每项字段："
        "segment_index,start_seconds,end_seconds,text,semantic_type,position_type,visual_description。"
        f"semantic_type 只能取：{'、'.join(SEGMENT_TYPES)}。"
        f"position_type 只能取：{'、'.join(POSITION_TYPES)}。"
        "原则：语义完整、主题一致、不在句子中间切断；一个片段必须包含一句完整表达，不能只截半句话、半个卖点或半个行动号召。"
        "如果一句话很长，宁可保留为一个较长片段，也不要为了凑数量切断。开始和结束时间必须在视频时长内。"
        "如果没有逐字时间戳，请按文本语义和总时长均匀估算时间。"
        f"\n视频时长：{duration:.1f} 秒\n转录文本：{transcript}"
    )
    content = await _chat_completion(settings, prompt, json_mode=settings.get("ai_json_mode") == "true")
    parsed = _loads_json(content)
    if not isinstance(parsed, list):
        raise ProviderError("AI 语义切分结果格式不正确。")
    return _normalize_segments(parsed, duration)


async def _segment_timestamped_transcript(video: dict[str, Any], timestamp_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    settings = get_settings(masked=False)
    _require_ai_settings(settings)
    sentences = [
        {
            "sentence_index": index,
            "start_seconds": round(float(item["start_seconds"]), 3),
            "end_seconds": round(float(item["end_seconds"]), 3),
            "text": str(item["text"]).strip(),
        }
        for index, item in enumerate(timestamp_segments)
        if str(item.get("text") or "").strip()
    ]
    if not sentences:
        raise ProviderError("ASR 时间戳为空，无法进行高精度语义切分。")

    prompt = (
        "你是专业的视频内容分析专家。请基于带时间戳的 ASR 句子列表，把电商短视频合并成语义完整的片段。"
        "你只能决定哪些句子合并、语义 tag、位置 tag 和画面摘要，不允许输出或编造 start_seconds/end_seconds。"
        "后端会用真实 ASR 句子的开始和结束时间计算片段边界。"
        "请输出 JSON 对象：{\"segments\":[...]}，不要 Markdown。"
        "segments 每项字段：sentence_indices,semantic_type,position_type,visual_description。"
        "sentence_indices 必须是已有 sentence_index，尽量连续，必须按原视频顺序；不要把一句完整表达切断。"
        "合并原则：相邻短句优先合并；同一个卖点、同一个行动号召、同一个产品介绍不要拆开；宁可稍长，不要半句话一个片段。"
        f"semantic_type 只能取：{'、'.join(SEGMENT_TYPES)}。"
        f"position_type 只能取：{'、'.join(POSITION_TYPES)}。"
        f"\n视频名称：{video.get('name')}\nASR 句子：{json.dumps(sentences, ensure_ascii=False)}"
    )
    content = await _chat_completion(settings, prompt, json_mode=settings.get("ai_json_mode") == "true")
    parsed = _loads_json(content)
    if not isinstance(parsed, list):
        raise ProviderError("AI 语义切分结果格式不正确。")
    normalized = _normalize_timestamped_segments(parsed, sentences)
    if not normalized:
        raise ProviderError("AI 语义切分引用了不存在的句子序号，请重试。")
    return normalized


def _load_transcript_segments(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        raw_items = value
    else:
        try:
            raw_items = json.loads(str(value or "[]"))
        except json.JSONDecodeError:
            return []
    if not isinstance(raw_items, list):
        return []
    loaded: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        start = _safe_float(raw.get("start_seconds"))
        end = _safe_float(raw.get("end_seconds"))
        text = str(raw.get("text") or "").strip()
        if start is None or end is None or end <= start or not text:
            continue
        loaded.append({"start_seconds": start, "end_seconds": end, "text": text})
    return loaded


def _normalize_timestamped_segments(items: list[Any], sentences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sentence_by_index = {int(item["sentence_index"]): item for item in sentences}
    normalized: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        indices = _extract_sentence_indices(raw)
        if not indices:
            continue
        if any(index not in sentence_by_index for index in indices):
            continue
        start_index = min(indices)
        end_index = max(indices)
        selected = [sentence_by_index[index] for index in range(start_index, end_index + 1) if index in sentence_by_index]
        if not selected:
            continue
        semantic_type = str(raw.get("semantic_type") or raw.get("type") or "过渡").strip()
        position_type = str(raw.get("position_type") or raw.get("position") or "中间").strip()
        if semantic_type not in SEGMENT_TYPES:
            semantic_type = "过渡"
        if position_type not in POSITION_TYPES:
            position_type = "中间"
        normalized.append(
            {
                "segment_index": "",
                "start_seconds": round(float(selected[0]["start_seconds"]), 3),
                "end_seconds": round(float(selected[-1]["end_seconds"]), 3),
                "text": "".join(str(item["text"]).strip() for item in selected).strip(),
                "semantic_type": semantic_type,
                "position_type": position_type,
                "visual_description": str(raw.get("visual_description") or ""),
            }
        )
    if not normalized:
        return []
    normalized = _merge_short_timestamp_segments(sorted(normalized, key=lambda item: item["start_seconds"]))
    for index, segment in enumerate(normalized, start=1):
        segment["segment_index"] = f"seg_{index:03d}"
    return normalized


def _extract_sentence_indices(raw: dict[str, Any]) -> list[int]:
    value = raw.get("sentence_indices")
    if isinstance(value, list):
        indices: list[int] = []
        for item in value:
            try:
                indices.append(int(item))
            except (TypeError, ValueError):
                continue
        return sorted(set(indices))
    start = raw.get("start_sentence_index", raw.get("start_index"))
    end = raw.get("end_sentence_index", raw.get("end_index"))
    try:
        start_int = int(start)
        end_int = int(end)
    except (TypeError, ValueError):
        return []
    if end_int < start_int:
        start_int, end_int = end_int, start_int
    return list(range(start_int, end_int + 1))


def _fallback_timestamp_segments(sentences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fallback: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for sentence in sentences:
        current.append(sentence)
        duration = float(current[-1]["end_seconds"]) - float(current[0]["start_seconds"])
        text_len = len("".join(str(item["text"]) for item in current))
        if duration >= 2.0 or text_len >= 22:
            fallback.append(_build_fallback_segment(current, len(fallback) + 1, sentences[-1]["end_seconds"]))
            current = []
    if current:
        fallback.append(_build_fallback_segment(current, len(fallback) + 1, sentences[-1]["end_seconds"]))
    return fallback


def _build_fallback_segment(items: list[dict[str, Any]], index: int, duration: float) -> dict[str, Any]:
    start = float(items[0]["start_seconds"])
    end = float(items[-1]["end_seconds"])
    midpoint = (start + end) / 2
    if midpoint < duration * 0.25:
        position = "开头"
    elif midpoint > duration * 0.75:
        position = "结尾"
    else:
        position = "中间"
    return {
        "segment_index": f"seg_{index:03d}",
        "start_seconds": round(start, 3),
        "end_seconds": round(end, 3),
        "text": "".join(str(item["text"]).strip() for item in items).strip(),
        "semantic_type": "过渡",
        "position_type": position,
        "visual_description": "",
    }


def _merge_short_timestamp_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index = 0
    while index < len(segments):
        current = dict(segments[index])
        duration = float(current["end_seconds"]) - float(current["start_seconds"])
        if duration < 1.2 and index + 1 < len(segments):
            nxt = segments[index + 1]
            current["end_seconds"] = nxt["end_seconds"]
            current["text"] = f"{current.get('text', '')}{nxt.get('text', '')}".strip()
            if current.get("semantic_type") == "过渡":
                current["semantic_type"] = nxt.get("semantic_type", "过渡")
            if current.get("visual_description") == "":
                current["visual_description"] = nxt.get("visual_description", "")
            merged.append(current)
            index += 2
            continue
        if duration < 1.2 and merged:
            previous = merged[-1]
            previous["end_seconds"] = current["end_seconds"]
            previous["text"] = f"{previous.get('text', '')}{current.get('text', '')}".strip()
            if previous.get("semantic_type") == "过渡":
                previous["semantic_type"] = current.get("semantic_type", "过渡")
        else:
            merged.append(current)
        index += 1
    return merged


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def generate_schemes(
    *,
    project: dict[str, Any],
    segments: list[dict[str, Any]],
    target_duration: float,
    duration_min: float,
    duration_max: float,
    scheme_count: int,
    strategy_count: int,
    outputs_per_strategy: int,
    segment_count: int,
    requirement_prompt: str,
) -> list[dict[str, Any]]:
    if not segments:
        raise ProviderError("请先生成语义片段。")
    settings = get_settings(masked=False)
    _require_ai_settings(settings)
    compact_segments = [
        {
            "segment_id": int(item["id"]),
            "source_video_id": int(item["video_id"]),
            "type": item["semantic_type"],
            "position": item["position_type"],
            "text": item["text"],
            "start": round(float(item["start_seconds"]), 2),
            "end": round(float(item["end_seconds"]), 2),
            "duration": round(float(item["end_seconds"]) - float(item["start_seconds"]), 2),
        }
        for item in segments
    ]
    duration_instruction = f"目标成片时长约 {target_duration:.0f} 秒。"
    if duration_min and duration_max:
        duration_instruction = f"每条成片时长尽量控制在 {duration_min:.0f}-{duration_max:.0f} 秒，优先贴近 {target_duration:.0f} 秒。"
    elif duration_min:
        duration_instruction = f"每条成片时长尽量不低于 {duration_min:.0f} 秒，优先贴近 {target_duration:.0f} 秒。"
    elif duration_max:
        duration_instruction = f"每条成片时长尽量不超过 {duration_max:.0f} 秒，优先贴近 {target_duration:.0f} 秒。"
    prompt = (
        "你是专业的视频混剪策划师。基于给定语义片段生成多个差异化混剪方案。"
        "方案必须先确定策略，再选择片段，不允许简单按 tag 堆叠。"
        "只输出 JSON 对象，不要 Markdown，格式为 {\"schemes\":[...]}。每个方案字段："
        "name,scheme_description,estimated_duration,style,target_audience,narrative_structure,"
        "differentiation,strategy_reasoning,variation_index,strategy_group_index,strategy,segments。"
        "同一个核心策略下的成片变体必须使用相同的 strategy_group_index 和 strategy.name。"
        "segments 每项字段：segment_id,reasoning,position_reasoning。segment_id 必须来自可用片段。"
        f"先生成 {strategy_count} 个核心策略，每个策略生成 {outputs_per_strategy} 条成片变体，总共 {scheme_count} 个方案。"
        "同一个策略下的成片可以风格接近，但片段组合、开场或结尾必须有差异。"
        f"每个方案建议选择约 {segment_count} 个片段，但这是参考值，不要为了凑数量切断表达。"
        f"{duration_instruction}请通过选择片段数量和组合控制大致时长；不要截断片段。"
        "每个方案必须有不同的核心策略，可选策略包括：快节奏冲击型、深度种草型、痛点堆叠型、价格爆破型、反套路型、信任堆叠型、场景营销型、情感共鸣型、综合型。"
        "style 从快闪风格、UGC风格、简约直给风格、对比展示风格、教程演示风格、促销紧迫风格中选择。"
        "必须遵守位置约束：开头片段优先放前20%，中间片段灵活，结尾片段优先放后20%。"
        "避免行动号召放开头，避免噱头引入放结尾；如果必须打破规则，要在 position_reasoning 说明。"
        "多个方案之间要明显差异化：开场不同、策略不同、片段组合重复率尽量低、时长区间尽量分散。"
        "同一个方案里要优先混合不同来源视频的片段，尽量覆盖更多 source_video_id；"
        "除非素材不足或叙事必须连续，不要反复使用同一个来源视频拆出来的画面。"
        "叙事结构要用箭头表达，例如：噱头引入→痛点→产品方案→效果展示→活动福利→行动号召。"
        "剪辑连贯性要求：每个被选择的片段必须是一句完整表达；同一个来源视频内的片段不能倒序使用；"
        "除非有明确转场理由，不要在一句产品介绍中间插入另一条视频；避免连续重复同一来源视频。"
        "同一来源视频内相邻片段必须按原视频时间顺序，避免选择时间重叠、台词重复或表达重复的片段。"
        f"\n项目：{project.get('name')}\n用户需求：{requirement_prompt or project.get('custom_prompt') or '生成适合电商投放的混剪方案'}"
        f"\n策略数量：{strategy_count}\n每个策略成片数：{outputs_per_strategy}\n方案总数：{scheme_count}\n推荐分镜数量：{segment_count}（仅供参考）"
        f"\n可用片段：{json.dumps(compact_segments, ensure_ascii=False)}"
    )
    content = await _chat_completion(settings, prompt, json_mode=settings.get("ai_json_mode") == "true")
    parsed = _loads_json(content)
    if not isinstance(parsed, list):
        raise ProviderError("AI 混剪方案格式不正确。")
    return _normalize_schemes(parsed, compact_segments, scheme_count, segment_count, outputs_per_strategy)


def recommend_scheme_range(segment_count: int, video_count: int) -> dict[str, int]:
    if segment_count < 20:
        low, high = 3, 5
        recommended_strategies = 3
        recommended_outputs = 1
    elif segment_count < 60:
        low, high = 6, 10
        recommended_strategies = 4
        recommended_outputs = 2
    else:
        low, high = 10, 20
        recommended_strategies = 5
        recommended_outputs = 2
    if video_count <= 1:
        high = min(high, 5)
        recommended_outputs = 1
    recommended = max(low, min(high, recommended_strategies * recommended_outputs))
    recommended_segments = max(3, min(12, math.ceil(segment_count / max(1, recommended)) or 3))
    return {
        "min": low,
        "max": max(low, high),
        "recommended": recommended,
        "recommended_strategies": recommended_strategies,
        "recommended_outputs_per_strategy": recommended_outputs,
        "recommended_segments": recommended_segments,
    }


def _require_ai_settings(settings: dict[str, str]) -> None:
    if not settings.get("ai_base_url"):
        raise ProviderError("请先填写 AI Base URL。")
    if not settings.get("ai_model"):
        raise ProviderError("请先填写 AI 模型名。")
    base_url = settings.get("ai_base_url", "").lower()
    local_hosts = ("localhost", "127.0.0.1", "0.0.0.0")
    if not settings.get("ai_api_key") and not any(host in base_url for host in local_hosts):
        raise ProviderError("请先填写 AI API Key。DeepSeek、通义千问等云端接口不能留空。")


def _resolve_whisper_binary(settings: dict[str, str]) -> str:
    configured = settings.get("local_whisper_binary_path", "").strip()
    candidates = [
        configured,
        shutil.which("whisper-cli") or "",
        shutil.which("whisper-cpp") or "",
        shutil.which("whisper") or "",
        "/opt/homebrew/bin/whisper-cli",
        "/usr/local/bin/whisper-cli",
        "/opt/homebrew/bin/whisper-cpp",
        "/usr/local/bin/whisper-cpp",
        "/opt/homebrew/bin/whisper",
        "/usr/local/bin/whisper",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise ProviderError("没有找到 whisper.cpp 命令。请先安装：brew install whisper-cpp，或在设置页填写 whisper-cli 路径。")


def _resolve_whisper_model(settings: dict[str, str]) -> str:
    configured = settings.get("local_whisper_model_path", "").strip()
    candidates = [
        configured,
        str(Path.home() / "Library/Caches/ai-video-editor/whisper-models/ggml-large-v3-turbo.bin"),
        "/opt/homebrew/share/whisper/models/ggml-large-v3-turbo.bin",
        "/opt/homebrew/share/whisper/models/ggml-small.bin",
        "/usr/local/share/whisper/models/ggml-large-v3-turbo.bin",
        "/usr/local/share/whisper/models/ggml-small.bin",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise ProviderError("没有找到 Whisper 模型文件。请在设置页填写 ggml 模型路径。")


async def _chat_completion(settings: dict[str, str], prompt: str, *, json_mode: bool) -> str:
    base_url = settings["ai_base_url"].rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {"Content-Type": "application/json"}
    api_key = settings.get("ai_api_key", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload: dict[str, Any] = {
        "model": settings["ai_model"],
        "messages": [
            {"role": "system", "content": "你是电商短视频混剪系统。请严格按用户要求输出。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.5,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    response: httpx.Response | None = None
    last_error: httpx.HTTPError | None = None
    async with httpx.AsyncClient(timeout=180) as client:
        for attempt in range(2):
            try:
                response = await client.post(url, json=payload, headers=headers)
                break
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt == 0:
                    continue
                raise ProviderError(f"AI API 请求失败：{exc}") from exc
    if response is None:
        raise ProviderError(f"AI API 请求失败：{last_error}") from last_error
    if response.status_code >= 400:
        raise ProviderError(f"AI API 请求失败：{response.status_code} {response.text}")
    data = response.json()
    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("AI API 返回格式不正确。") from exc


async def _transcribe_whisper(settings: dict[str, str], video_path: Path) -> str:
    if not settings.get("asr_base_url") or not settings.get("asr_model"):
        raise ProviderError("请填写 ASR Base URL 和模型名。")
    audio_path = video_path.parent / "asr_audio.mp3"
    try:
        extract_audio_for_whisper(video_path, audio_path)
    except VideoProcessingError as exc:
        raise ProviderError(str(exc)) from exc
    url = f"{settings['asr_base_url'].rstrip('/')}/audio/transcriptions"
    headers: dict[str, str] = {}
    if settings.get("asr_api_key"):
        headers["Authorization"] = f"Bearer {settings['asr_api_key']}"
    async with httpx.AsyncClient(timeout=120) as client:
        with audio_path.open("rb") as audio_file:
            response = await client.post(
                url,
                headers=headers,
                data={"model": settings["asr_model"]},
                files={"file": (audio_path.name, audio_file, "audio/mpeg")},
            )
    if response.status_code >= 400:
        raise ProviderError(f"ASR API 请求失败：{response.status_code} {response.text}")
    data = response.json()
    return str(data.get("text") or "").strip()


async def _transcribe_local_whisper(settings: dict[str, str], video_path: Path) -> dict[str, Any]:
    binary_path = _resolve_whisper_binary(settings)
    model_path = _resolve_whisper_model(settings)
    language = settings.get("local_whisper_language", "zh") or "zh"

    def run_whisper() -> dict[str, Any]:
        audio_path = video_path.parent / "local_whisper.wav"
        try:
            extract_wav_16k(video_path, audio_path)
        except VideoProcessingError as exc:
            raise ProviderError(str(exc)) from exc

        output_prefix = video_path.parent / "local_whisper_output"
        command = [
            binary_path,
            "-m",
            model_path,
            "-f",
            str(audio_path),
            "-l",
            language,
            "--output-json-full",
            "-of",
            str(output_prefix),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            fallback = [
                binary_path,
                "-m",
                model_path,
                "-f",
                str(audio_path),
                "-l",
                language,
                "-oj",
                "-of",
                str(output_prefix),
            ]
            result = subprocess.run(fallback, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise ProviderError(result.stderr.strip() or "本地 Whisper 识别失败。")

        json_candidates = [
            Path(f"{output_prefix}.json"),
            audio_path.with_suffix(audio_path.suffix + ".json"),
            video_path.parent / "local_whisper.wav.json",
        ]
        for json_path in json_candidates:
            if json_path.exists():
                try:
                    data = _load_whisper_json(json_path)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                segments = _extract_whisper_segments(data)
                text = _extract_whisper_text(data)
                if segments:
                    return {"text": text or "".join(item["text"] for item in segments).strip(), "segments": segments, "has_timestamps": True}
                if text:
                    return {"text": text, "segments": [], "has_timestamps": False}

        stdout_text = _extract_text_from_whisper_stdout(result.stdout)
        if stdout_text:
            return {"text": stdout_text, "segments": [], "has_timestamps": False}
        raise ProviderError("本地 Whisper 没有返回可用转录文本。")

    import asyncio

    return await asyncio.to_thread(run_whisper)


def _load_whisper_json(path: Path) -> Any:
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return json.loads(raw.decode(encoding))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return json.loads(raw.decode("utf-8", errors="replace"))


def _extract_whisper_text(data: Any) -> str:
    if isinstance(data, dict):
        if isinstance(data.get("transcription"), list):
            return "".join(str(item.get("text", "")) for item in data["transcription"] if isinstance(item, dict)).strip()
        if isinstance(data.get("segments"), list):
            return "".join(str(item.get("text", "")) for item in data["segments"] if isinstance(item, dict)).strip()
        if data.get("text"):
            return str(data["text"]).strip()
    if isinstance(data, list):
        return "".join(str(item.get("text", "")) for item in data if isinstance(item, dict)).strip()
    return ""


def _extract_whisper_segments(data: Any) -> list[dict[str, Any]]:
    raw_items: list[Any] = []
    if isinstance(data, dict):
        if isinstance(data.get("transcription"), list):
            raw_items = data["transcription"]
        elif isinstance(data.get("segments"), list):
            raw_items = data["segments"]
    elif isinstance(data, list):
        raw_items = data

    segments: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        timestamps = raw.get("timestamps") if isinstance(raw.get("timestamps"), dict) else {}
        offsets = raw.get("offsets") if isinstance(raw.get("offsets"), dict) else {}
        start = _parse_timestamp_seconds(
            _first_present(raw.get("start"), raw.get("start_seconds"), raw.get("from"), timestamps.get("from"), offsets.get("from"))
        )
        end = _parse_timestamp_seconds(
            _first_present(raw.get("end"), raw.get("end_seconds"), raw.get("to"), timestamps.get("to"), offsets.get("to"))
        )
        if start is None or end is None or end <= start:
            continue
        segments.append(
            {
                "sentence_index": len(segments),
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "text": text,
            }
        )
    return segments


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _parse_timestamp_seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        return seconds / 1000 if seconds > 10000 else seconds
    raw = str(value).strip()
    if not raw:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return float(raw)
    parts = raw.replace(",", ".").split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds)
    except ValueError:
        return None
    return None


def _extract_text_from_whisper_stdout(stdout: str) -> str:
    lines: list[str] = []
    for line in stdout.splitlines():
        cleaned = re.sub(r"^\s*\[[^\]]+\]\s*", "", line).strip()
        if cleaned and not cleaned.startswith("whisper_") and "system_info" not in cleaned:
            lines.append(cleaned)
    return "".join(lines).strip()


async def _transcribe_aliyun_nls(settings: dict[str, str], video_path: Path) -> str:
    try:
        import nls
        from nls.token import getToken
    except ImportError as exc:
        raise ProviderError("缺少阿里云 NLS SDK，请先安装 alibaba-nls-python-sdk。") from exc

    missing = [
        label
        for key, label in (
            ("aliyun_access_key_id", "AccessKey ID"),
            ("aliyun_access_key_secret", "AccessKey Secret"),
            ("aliyun_app_key", "NLS AppKey"),
        )
        if not settings.get(key)
    ]
    if missing:
        raise ProviderError(f"阿里云 ASR 缺少配置：{', '.join(missing)}")

    def run_transcription() -> str:
        pcm_path = video_path.parent / "aliyun_asr.pcm"
        try:
            extract_pcm_16k(video_path, pcm_path)
            token = getToken(
                settings["aliyun_access_key_id"],
                settings["aliyun_access_key_secret"],
                settings.get("aliyun_region") or "cn-shanghai",
            )
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"阿里云 ASR 初始化失败：{exc}") from exc

        sentences: list[str] = []
        errors: list[str] = []

        def append_sentence(message: str, *_args: Any) -> None:
            try:
                data = json.loads(message)
                payload = data.get("payload", {})
                text = payload.get("result") or payload.get("text")
                if text:
                    sentences.append(str(text))
            except Exception:
                if message:
                    sentences.append(str(message))

        def on_error(message: str, *_args: Any) -> None:
            errors.append(str(message))

        transcriber = nls.NlsSpeechTranscriber(
            token=token,
            appkey=settings["aliyun_app_key"],
            on_sentence_end=append_sentence,
            on_completed=append_sentence,
            on_error=on_error,
        )

        try:
            transcriber.start(
                aformat="pcm",
                sample_rate=16000,
                enable_intermediate_result=False,
                enable_punctuation_prediction=True,
                enable_inverse_text_normalization=True,
            )
            with pcm_path.open("rb") as pcm:
                while True:
                    chunk = pcm.read(3200)
                    if not chunk:
                        break
                    transcriber.send_audio(chunk)
                    time.sleep(0.01)
            transcriber.stop()
            transcriber.shutdown()
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"阿里云 ASR 识别失败：{exc}") from exc

        if errors and not sentences:
            raise ProviderError(f"阿里云 ASR 识别失败：{errors[-1]}")
        transcript = "".join(sentences).strip()
        if not transcript:
            raise ProviderError("阿里云 ASR 没有返回转录文本。")
        return transcript

    import asyncio

    return await asyncio.to_thread(run_transcription)


def _loads_json(content: str) -> Any:
    cleaned = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    if cleaned.startswith("{"):
        parsed = json.loads(cleaned)
        for key in ("segments", "schemes", "requirements", "data"):
            if key in parsed:
                return parsed[key]
        return parsed
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def _normalize_segments(items: list[Any], duration: float) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    last_end = 0.0
    for index, raw in enumerate(items, start=1):
        if not isinstance(raw, dict):
            continue
        start = max(0.0, float(raw.get("start_seconds", last_end)))
        end = min(duration, float(raw.get("end_seconds", start + 5)))
        if end <= start:
            end = min(duration, start + 1)
        semantic_type = str(raw.get("semantic_type") or raw.get("type") or "过渡").strip()
        position_type = str(raw.get("position_type") or raw.get("position") or "中间").strip()
        if semantic_type not in SEGMENT_TYPES:
            semantic_type = "过渡"
        if position_type not in POSITION_TYPES:
            position_type = "中间"
        normalized.append(
            {
                "segment_index": str(raw.get("segment_index") or f"seg_{index:03d}"),
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "text": str(raw.get("text") or ""),
                "semantic_type": semantic_type,
                "position_type": position_type,
                "visual_description": str(raw.get("visual_description") or ""),
            }
        )
        last_end = end
    if not normalized and duration > 0:
        normalized.append(
            {
                "segment_index": "seg_001",
                "start_seconds": 0,
                "end_seconds": duration,
                "text": "",
                "semantic_type": "过渡",
                "position_type": "中间",
                "visual_description": "",
            }
        )
    return normalized


async def analyze_product_visual(segment: dict[str, Any], custom_tags: str = "") -> dict[str, Any]:
    settings = get_settings(masked=False)
    _require_ai_settings(settings)
    tag_instruction = (
        f"用户自定义 tag 词库：{custom_tags}。selling_points 和 visual_tags 必须优先从这些 tag 中选择；"
        "只有画面确实需要且词库没有覆盖时，才允许补充少量新 tag。"
        "这些用户自定义 tag 只能用于 selling_points 或 visual_tags，绝对不要用于 semantic_type；"
        f"semantic_type 仍然只能属于系统大类：{'、'.join(SEGMENT_TYPES)}。"
        if custom_tags.strip()
        else "selling_points 和 visual_tags 请生成简短、可复用、适合后续素材匹配的 tag。"
    )
    prompt = (
        "你是电商短视频产品镜头分析师。请根据已有镜头信息推断这个镜头适合表达的卖点。"
        "只输出 JSON 对象，不要 Markdown。字段：visual_description, selling_points, visual_tags, "
        "suitable_positions, recommended_usage。selling_points、visual_tags、suitable_positions 都是数组。"
        f"{tag_instruction}"
        "如果画面信息不足，请根据文件名、片段台词和当前描述保守生成可编辑的初始标签。"
        f"\n视频名：{segment.get('video_name')}"
        f"\n片段时间：{segment.get('start_seconds')} - {segment.get('end_seconds')}"
        f"\n已有台词：{segment.get('text')}"
        f"\n已有描述：{segment.get('visual_description')}"
        f"\n已有语义 tag：{segment.get('semantic_type')}"
    )
    content = await _chat_completion(settings, prompt, json_mode=settings.get("ai_json_mode") == "true")
    parsed = _loads_json(content)
    if isinstance(parsed, list):
        parsed = parsed[0] if parsed else {}
    if not isinstance(parsed, dict):
        raise ProviderError("AI 视觉分析结果格式不正确。")
    return {
        "visual_description": str(parsed.get("visual_description") or segment.get("visual_description") or "").strip(),
        "selling_points": _string_list(parsed.get("selling_points")),
        "visual_tags": _string_list(parsed.get("visual_tags")),
        "suitable_positions": _string_list(parsed.get("suitable_positions")) or ["中间"],
        "recommended_usage": str(parsed.get("recommended_usage") or "").strip(),
    }


async def generate_script_lines(*, source_text: str, product_context: str, source_type: str) -> list[dict[str, Any]]:
    settings = get_settings(masked=False)
    _require_ai_settings(settings)
    prompt = (
        "你是电商短视频口播编导。请把用户提供的文案或爆款结构，结合产品信息改写裂变为一版原创短视频口播。"
        "只输出 JSON 对象，不要 Markdown，格式：{\"lines\":[...]}。"
        "每句字段：line_index,text,semantic_type,selling_points,visual_needs,estimated_duration。"
        f"semantic_type 只能取：{'、'.join(SEGMENT_TYPES)}。"
        "selling_points 和 visual_needs 是数组。estimated_duration 用秒，按中文口播自然语速估算。"
        "不要照搬平台原文，要保留结构并结合用户产品重写。"
        f"\n来源类型：{source_type}"
        f"\n产品信息：{product_context}"
        f"\n输入文案或链接内容：{source_text}"
    )
    content = await _chat_completion(settings, prompt, json_mode=settings.get("ai_json_mode") == "true")
    parsed = _loads_json(content)
    if isinstance(parsed, dict):
        parsed = parsed.get("lines", [])
    if not isinstance(parsed, list):
        raise ProviderError("AI 文案结果格式不正确。")
    return _normalize_script_lines(parsed)


def fallback_script_lines(source_text: str) -> list[dict[str, Any]]:
    parts = [item.strip() for item in re.split(r"[。！？!?；;\n]+", source_text) if item.strip()]
    if not parts and source_text.strip():
        parts = [source_text.strip()]
    lines: list[dict[str, Any]] = []
    for index, text in enumerate(parts[:30], start=1):
        lines.append(
            {
                "line_index": index,
                "text": text,
                "semantic_type": SEGMENT_TYPES[min(index - 1, len(SEGMENT_TYPES) - 1)],
                "selling_points": [],
                "visual_needs": [],
                "estimated_duration": round(max(1.5, len(text) / 5.2), 1),
            }
        )
    return lines


def _normalize_script_lines(items: list[Any]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for index, raw in enumerate(items, start=1):
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        semantic_type = str(raw.get("semantic_type") or "过渡").strip()
        if semantic_type not in SEGMENT_TYPES:
            semantic_type = "过渡"
        try:
            estimated_duration = float(raw.get("estimated_duration") or max(1.5, len(text) / 5.2))
        except (TypeError, ValueError):
            estimated_duration = max(1.5, len(text) / 5.2)
        lines.append(
            {
                "line_index": int(raw.get("line_index") or index),
                "text": text,
                "semantic_type": semantic_type,
                "selling_points": _string_list(raw.get("selling_points")),
                "visual_needs": _string_list(raw.get("visual_needs")),
                "estimated_duration": round(max(0.8, estimated_duration), 1),
            }
        )
    return lines


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").replace("，", ",").replace("/", ",").split(",") if item.strip()]


def _normalize_schemes(
    items: list[Any],
    available_segments: list[dict[str, Any]],
    scheme_count: int,
    segment_count: int,
    outputs_per_strategy: int,
) -> list[dict[str, Any]]:
    valid_ids = {int(item["segment_id"]) for item in available_segments}
    durations = {int(item["segment_id"]): max(0.1, float(item.get("duration") or 0.1)) for item in available_segments}
    fallback_ids = [int(item["segment_id"]) for item in available_segments if int(item["segment_id"]) in valid_ids]
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(items[:scheme_count], start=1):
        if not isinstance(raw, dict):
            continue
        scheme_segments = []
        for item in raw.get("segments", []):
            if not isinstance(item, dict):
                continue
            segment_id = int(item.get("segment_id", 0) or 0)
            if segment_id in valid_ids:
                scheme_segments.append(
                    {
                        "segment_id": segment_id,
                        "reasoning": str(item.get("reasoning") or ""),
                        "position_reasoning": str(item.get("position_reasoning") or ""),
                    }
                )
        if not scheme_segments:
            scheme_segments = [{"segment_id": segment_id, "reasoning": "fallback", "position_reasoning": ""} for segment_id in fallback_ids[:segment_count]]
        scheme_segments = _dedupe_scheme_segments(scheme_segments)
        scheme_segments = _improve_scheme_source_diversity(scheme_segments, available_segments)
        actual_duration = _scheme_duration(scheme_segments, durations)
        estimated_duration = actual_duration or float(raw.get("estimated_duration") or 0)
        normalized.append(
            {
                "name": str(raw.get("name") or f"方案 {index}"),
                "scheme_description": str(raw.get("scheme_description") or raw.get("description") or ""),
                "estimated_duration": estimated_duration,
                "style": str(raw.get("style") or ""),
                "target_audience": str(raw.get("target_audience") or ""),
                "narrative_structure": str(raw.get("narrative_structure") or ""),
                "differentiation": str(raw.get("differentiation") or ""),
                "strategy_reasoning": str(raw.get("strategy_reasoning") or ""),
                "variation_index": int(raw.get("variation_index") or index),
                "strategy_group_index": int(raw.get("strategy_group_index") or math.ceil(index / max(1, outputs_per_strategy))),
                "strategy": raw.get("strategy") if isinstance(raw.get("strategy"), dict) else {},
                "segments": scheme_segments,
            }
        )
    if not normalized:
        fallback_segments = _dedupe_scheme_segments(
            [{"segment_id": segment_id, "reasoning": "fallback", "position_reasoning": ""} for segment_id in fallback_ids[:segment_count]]
        )
        fallback_segments = _improve_scheme_source_diversity(fallback_segments, available_segments)
        normalized.append(
            {
                "name": "自动兜底方案",
                "scheme_description": "按现有分镜顺序自动组合。",
                "estimated_duration": _scheme_duration(fallback_segments, durations),
                "style": "简约直给风格",
                "target_audience": "通用受众",
                "narrative_structure": "开场 → 内容 → 行动号召",
                "differentiation": "",
                "strategy_reasoning": "AI 未返回可用方案时生成的兜底方案。",
                "variation_index": 1,
                "strategy": {},
                "segments": fallback_segments,
            }
        )
    return normalized


def _dedupe_scheme_segments(scheme_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[int] = set()
    deduped: list[dict[str, Any]] = []
    for item in scheme_segments:
        segment_id = int(item["segment_id"])
        if segment_id in seen:
            continue
        seen.add(segment_id)
        deduped.append(item)
    return deduped


def _improve_scheme_source_diversity(
    scheme_segments: list[dict[str, Any]],
    available_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(scheme_segments) < 2:
        return scheme_segments
    available_by_id = {int(item["segment_id"]): item for item in available_segments}
    source_ids = {int(item.get("source_video_id") or 0) for item in available_segments}
    if len(source_ids) < 2:
        return scheme_segments

    current_ids = [int(item["segment_id"]) for item in scheme_segments]
    used_ids = set(current_ids)
    source_usage = Counter(
        int(available_by_id[segment_id].get("source_video_id") or 0)
        for segment_id in current_ids
        if segment_id in available_by_id
    )
    kept_by_source: Counter[int] = Counter()
    improved: list[dict[str, Any]] = []

    for item in scheme_segments:
        segment_id = int(item["segment_id"])
        target = available_by_id.get(segment_id)
        if not target:
            improved.append(item)
            continue

        source_id = int(target.get("source_video_id") or 0)
        if kept_by_source[source_id] > 0:
            replacement = _find_source_diverse_replacement(target, available_segments, used_ids, source_usage)
            if replacement:
                replacement_id = int(replacement["segment_id"])
                used_ids.discard(segment_id)
                used_ids.add(replacement_id)
                source_usage[source_id] -= 1
                replacement_source_id = int(replacement.get("source_video_id") or 0)
                source_usage[replacement_source_id] += 1
                item = {
                    **item,
                    "segment_id": replacement_id,
                    "reasoning": _append_reasoning(
                        str(item.get("reasoning") or ""),
                        "为提升跨视频混剪多样性，替换为其他来源视频的同类片段。",
                    ),
                }
                target = replacement
                source_id = replacement_source_id

        kept_by_source[source_id] += 1
        improved.append(item)

    return _spread_adjacent_sources(improved, available_by_id)


def _find_source_diverse_replacement(
    target: dict[str, Any],
    available_segments: list[dict[str, Any]],
    used_ids: set[int],
    source_usage: Counter[int],
) -> dict[str, Any] | None:
    target_source_id = int(target.get("source_video_id") or 0)
    target_type = str(target.get("type") or "")
    target_position = str(target.get("position") or "")
    target_duration = float(target.get("duration") or 0)
    candidates: list[tuple[float, dict[str, Any]]] = []

    for candidate in available_segments:
        candidate_id = int(candidate["segment_id"])
        candidate_source_id = int(candidate.get("source_video_id") or 0)
        if candidate_id in used_ids or candidate_source_id == target_source_id:
            continue
        type_match = _tag_overlap(target_type, str(candidate.get("type") or ""))
        position_match = _tag_overlap(target_position, str(candidate.get("position") or ""))
        if not type_match and not position_match:
            continue
        duration_delta = abs(float(candidate.get("duration") or 0) - target_duration)
        score = 0.0
        if type_match:
            score += 80
        if position_match:
            score += 40
        score += max(0, 12 - source_usage[candidate_source_id]) * 5
        score -= min(duration_delta, 10)
        candidates.append((score, candidate))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _spread_adjacent_sources(
    scheme_segments: list[dict[str, Any]],
    available_by_id: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    remaining = list(enumerate(scheme_segments))
    ordered: list[dict[str, Any]] = []
    previous_source_id: int | None = None

    while remaining:
        best_index = 0
        best_score = -10_000
        for index, (original_index, item) in enumerate(remaining):
            source_id = _scheme_item_source_id(item, available_by_id)
            score = -original_index * 0.01
            if previous_source_id is None or source_id != previous_source_id:
                score += 100
            score += _position_order_score(item, available_by_id) * 0.1
            if score > best_score:
                best_score = score
                best_index = index
        _, selected = remaining.pop(best_index)
        ordered.append(selected)
        previous_source_id = _scheme_item_source_id(selected, available_by_id)
    return ordered


def _scheme_item_source_id(item: dict[str, Any], available_by_id: dict[int, dict[str, Any]]) -> int:
    segment = available_by_id.get(int(item["segment_id"]), {})
    return int(segment.get("source_video_id") or 0)


def _position_order_score(item: dict[str, Any], available_by_id: dict[int, dict[str, Any]]) -> int:
    segment = available_by_id.get(int(item["segment_id"]), {})
    position = str(segment.get("position") or "")
    if "开头" in position:
        return 2
    if "结尾" in position:
        return -2
    return 0


def _tag_overlap(left: str, right: str) -> bool:
    left_values = _split_tags(left)
    right_values = _split_tags(right)
    return bool(left_values and right_values and left_values.intersection(right_values))


def _split_tags(value: str) -> set[str]:
    return {item.strip() for item in re.split(r"[,，、/|｜\s]+", value) if item.strip()}


def _append_reasoning(current: str, addition: str) -> str:
    if not current:
        return addition
    if addition in current:
        return current
    return f"{current}；{addition}"


def _scheme_duration(scheme_segments: list[dict[str, Any]], durations: dict[int, float]) -> float:
    return sum(durations.get(int(item["segment_id"]), 0) for item in scheme_segments)

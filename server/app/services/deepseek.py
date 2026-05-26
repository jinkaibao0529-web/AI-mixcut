import json
import re

import httpx

from app.core.settings import settings


class DeepSeekError(RuntimeError):
    pass


class DeepSeekClient:
    async def analyze_script(self, script: str) -> str:
        if not settings.deepseek_api_key:
            raise DeepSeekError("DeepSeek API key is not configured. Add it to server/.env first.")

        prompt = (
            "你是电商短视频混剪系统的文案分析器。"
            "请把用户文案拆成短视频结构，并为每一段分配一个素材 tag。"
            "只输出清晰的中文列表，tag 从这些里面选：噱头引入、痛点、产品方案、效果展示、信任背书、"
            "价格对比、活动福利、行动号召、产品定位、过渡。\n\n"
            f"用户文案：{script}"
        )

        payload = {
            "model": settings.deepseek_model,
            "messages": [
                {"role": "system", "content": "你负责把电商文案拆解成可混剪的视频脚本结构。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        }

        url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {settings.deepseek_api_key}"}

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code >= 400:
            raise DeepSeekError(f"DeepSeek request failed: {response.status_code} {response.text}")

        data = response.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DeepSeekError("DeepSeek returned an unexpected response shape.") from exc

    async def generate_mix_requirements(self, requirement_prompt: str) -> list[dict[str, str]]:
        if not settings.deepseek_api_key:
            raise DeepSeekError("DeepSeek API key is not configured. Add it to server/.env first.")

        prompt = (
            "你是电商短视频混剪方案生成器。"
            "请根据用户需求生成一个短视频混剪结构，只输出 JSON 数组，不要输出解释、Markdown 或代码块。"
            "数组每一项必须只有 section 和 tag 两个字段。"
            "section 只能从这些里面选：片头、中间段、结尾。"
            "tag 只能从这些里面选：噱头引入、痛点、产品方案、效果展示、信任背书、"
            "价格对比、活动福利、行动号召、产品定位、过渡。"
            "如果用户提到时长，请通过控制数组长度来接近目标时长。"
            "结构必须适合电商短视频：通常片头吸引注意，中间承接卖点或证明，结尾行动号召。\n\n"
            f"用户需求：{requirement_prompt}"
        )

        payload = {
            "model": settings.deepseek_model,
            "messages": [
                {"role": "system", "content": "你只返回可解析的 JSON 数组。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.4,
        }

        url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {settings.deepseek_api_key}"}

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code >= 400:
            raise DeepSeekError(f"DeepSeek request failed: {response.status_code} {response.text}")

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DeepSeekError("DeepSeek returned an unexpected response shape.") from exc

        try:
            parsed = json.loads(_extract_json_array(content))
        except json.JSONDecodeError as exc:
            raise DeepSeekError("AI 混剪方案格式不正确，请调整需求后重试。") from exc

        if not isinstance(parsed, list):
            raise DeepSeekError("AI 混剪方案格式不正确，请调整需求后重试。")
        return parsed


def _extract_json_array(content: str) -> str:
    cleaned = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()

    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return cleaned
    return cleaned[start : end + 1]

# V1 Implementation Summary

This document summarizes the code-level V1 implementation for ecommerce short-video batch generation.

## Frontend

Main files:

- `desktop/src/App.tsx`
- `desktop/src/styles.css`

Added or expanded workspace areas:

- Asset library
  - asset type import for finished videos, product shots, benefit shots, talking-head videos, BGM, voice, and subtitle presets
  - product-shot visual tagging review
  - finished-video BGM removal task creation
  - unified AI Worker task list
- Script center
  - manual script variants
  - Douyin-derived rewrite flow
  - script filtering by source and keyword
  - line-level script editing
  - TTS generation and script-driven timeline generation
- Voice/BGM
  - TTS generation
  - BGM and voice preview
  - audio loudness analysis display
- Subtitle presets
  - metadata-backed ASS style editing
  - font, size, colors, outline, shadow, alignment, and margin settings
- Material mix timeline
  - audio policy controls
  - voice/BGM/subtitle selection
  - loudness normalization controls
  - audio recommendation helper
  - persistent clip selection reasons
  - replacement candidate scoring and reasons
- Segment library
  - selling-point and visual tags
  - visual description editing
  - tag-based export for semantic, selling-point, and visual tags

## Backend APIs

Added or expanded endpoints:

- `POST /projects/{project_id}/assets/import`
- `GET /projects/{project_id}/assets`
- `PATCH /assets/{asset_id}`
- `GET /assets/{asset_id}/file`
- `POST /assets/{asset_id}/analyze-audio`
- `GET /projects/{project_id}/ai-tasks`
- `POST /segments/{segment_id}/analyze-visual`
- `POST /projects/{project_id}/segments/analyze-visual`
- `POST /segments/export`
- `GET /projects/{project_id}/scripts`
- `POST /scripts/generate-variants`
- `POST /scripts/from-douyin`
- `PATCH /scripts/{script_id}`
- `POST /tts/generate`
- `POST /timelines/generate-from-voice`
- `POST /audio/remove-bgm`
- `POST /material-mix/timelines/{timeline_id}/export`

## Data Model

Expanded tables:

- `videos`
  - `asset_type`
  - `source_mode`
  - `has_voice`
  - `has_bgm`
  - `has_captions`
  - `keep_original_audio`
- `segments`
  - `selling_points`
  - `visual_tags`
  - `source_mode`
  - `keep_original_audio`
- `material_mix_timelines`
  - `voice_asset_id`
  - `bgm_asset_id`
  - `subtitle_preset_id`
  - `audio_policy`
  - `normalize_loudness`
  - `target_lufs`
  - `burn_subtitles`
- `material_mix_clips`
  - `selection_note`

New tables:

- `assets`
- `scripts`
- `ai_tasks`

## Media Processing

Implemented through FFmpeg-backed utilities:

- timeline export with original audio policy
- voice replacement and voice overlay
- BGM overlay
- loudness normalization via `loudnorm`
- audio loudness analysis via `loudnorm` measurement
- ASS subtitle generation and burn-in
- subtitle style extraction from `.ass`
- subtitle style parsing from `.json`
- metadata-backed subtitle style override

## AI Providers

Provider-backed features:

- product visual analysis through LLM provider
- script generation and rewrite through LLM provider
- TTS through configurable TTS provider

V1 placeholder behavior:

- TTS can generate silent placeholder audio when no provider is configured, so the script-to-timeline flow remains testable.

## Optional Worker Boundary

The desktop app and main backend stay lightweight. Heavy model work is represented as optional `ai_tasks`.

Current worker-ready task:

- `remove_bgm`

Planned worker capabilities:

- Demucs/UVR BGM and vocal separation
- ForcedAligner word-level subtitle timing
- voice cloning
- digital human generation

## Validation

Minimum code-level validation:

```bash
./scripts/v1_smoke.sh
```

Release-level validation:

- follow `docs/V1_ACCEPTANCE_CHECKLIST.md`
- use real finished videos, product shots, BGM, voice assets, and subtitle presets
- manually listen to exported audio and inspect burned subtitles on mobile

# AI Video Editor

Local-first ecommerce video remix desktop app.

## Structure

- `desktop/`: Electron + React desktop client.
- `server/`: FastAPI local backend.
- `data/`: Local material library, exports, and temporary files.

## Quick Start

Backend:

```bash
cd server
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Desktop:

```bash
cd desktop
npm install
npm run dev
```

## V1 Scope

V1 focuses on two ecommerce short-video generation loops:

- Finished-video remix: import finished videos with voiceover, run ASR/semantic slicing/tagging, export clips by tag, generate AI remix timelines, fine-tune clips, remove BGM as an optional worker task, normalize loudness, and burn subtitles.
- Product-shot generation: import product/benefit shots, analyze visual selling points, generate or rewrite scripts, create TTS voiceover, match script semantics to product clips, fine-tune the timeline, add BGM/subtitles, and export.

The manual video fine-tuning flow remains core:

- adjust clip in/out points
- split segments
- replace timeline clips
- move clips up/down
- delete clips
- preview single clips and full timelines

## V1 Validation

Run the fixed smoke check after code changes:

```bash
./scripts/v1_smoke.sh
```

It runs:

- desktop `npm run build`
- backend `python -m compileall app`
- FastAPI smoke checks for OpenAPI, health, projects, settings, and TTS settings test

## Real Material Acceptance

Code-level validation is not a substitute for media validation. Before calling V1 release-ready, test with real files:

- Use `docs/V1_验收清单.md` as the checklist and `docs/V1_发布验收记录.md` as the release run log.
- 3 finished voiceover videos: import, ASR, slice, tag, tag export, AI timeline, fine-tune, export
- 5 product/benefit shots: visual analysis, selling-point tags, user tag correction
- 1 manual script and 1 Douyin-derived script rewrite
- TTS generation, single script-to-timeline generation, clip replacement, and timeline fine-tuning
- BGM import, loudness analysis, recommended audio policy, loudness-normalized export
- subtitle preset import/edit, burn-in subtitle export
- edge cases: no audio track, very short clips, missing tags, failed TTS, missing BGM, missing subtitle preset

## V1 Architecture Notes

- Main app stays lightweight: do not put PyTorch/Demucs/Qwen TTS/ForcedAligner directly into the desktop dependency path.
- Heavy AI work belongs behind optional AI Worker tasks.
- Cloud providers are the fastest V1 path for vision and TTS; local models can be added later through provider/worker abstractions.
- `scripts/v1_smoke.sh` is the minimum regression gate; real素材端到端验收 is still required for media quality.

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


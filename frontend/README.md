# leanlab board — frontend

React + Tailwind UI for the coding board. It talks to the Python server's
`/api/state`, `/api/task`, and `/api/stream` (SSE) endpoints.

## Develop

```bash
leanlab board --no-open        # serves the API on :8766 (in a project with a .leanlab)
cd frontend && npm install && npm run dev   # Vite on :5173, proxies /api → :8766
```

## Build (ships into the Python wheel)

```bash
cd frontend && npm install && npm run build
```

`npm run build` writes the compiled assets to `../leanlab/core/coding/board_dist/`,
which the Python package serves at `/`. Re-run it after changing anything in `src/`.

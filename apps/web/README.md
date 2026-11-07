# Shiftwright web (WS7)

React + Vite + TypeScript + Tailwind v4.

```bash
npm install
npm run dev        # http://localhost:5173, /api proxied to :8000
npm test           # vitest
npm run build && npm run lint
```

API mode: live by default. On the dev server, `?api=mock` uses the in-browser mock (remembered; `?api=live`
switches back) or set `VITE_API_MODE=mock`. Production builds are always live and don't include the mock.

Routes (react-router): `/` landing, `/signup`, `/login`, `/workplaces`, `/workplaces/new`, `/w/:id` (workspace).
App routes need a session (`GET /api/auth/me`); signed-out visitors go to `/login`.

Types come only from `src/contracts.ts` (`make types` at repo root). Shapes that API.md defines outside the
models live in `src/api/protocol.ts`. One component per chat card in `src/cards/`.

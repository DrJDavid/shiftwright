# Shiftwright web (WS7)

React + Vite + TypeScript + Tailwind v4.

```bash
npm install
npm run dev        # http://localhost:5173, /api proxied to :8000
npm test           # vitest
npm run build && npm run lint
```

API mode: the in-browser mock is the default until the FastAPI app lands. Use `?api=live` to hit the real
server (remembered; `?api=mock` switches back) or set `VITE_API_MODE=live`.

Types come only from `src/contracts.ts` (`make types` at repo root). Shapes that API.md defines outside the
models live in `src/api/protocol.ts`. One component per chat card in `src/cards/`.

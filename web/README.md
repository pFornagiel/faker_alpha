# FakerAlpha — panel analityka

React + TypeScript + Tailwind CSS + [shadcn/ui](https://ui.shadcn.com) (Radix), TanStack Query, Cytoscape.js.
Dane z API `ftf/api.py` (FastAPI).

```bash
npm ci
npm run dev      # http://localhost:5173, proxy /api -> http://127.0.0.1:8765 (uvicorn ftf.api:app --reload --port 8765)
npm run build    # dist/ — serwowane przez `python -m ftf.cli serve`
```

Struktura: `src/pages/*` (jedna strona = jeden widok), `src/components/common.tsx` (odznaki, miernik siły p, nagłówki),
`src/components/evidence.tsx` (słupki rodzin dowodów, obliczenie p, tabela dowodów), `src/lib/api.ts` (typy odpowiedzi API).
Kolory: kategoryczne = tożsamość kampanii (tylko kampanie wielomateriałowe), sekwencyjna niebieska skala = siła p,
kolory statusu = decyzja dla nowego materiału (zawsze z ikoną i etykietą).

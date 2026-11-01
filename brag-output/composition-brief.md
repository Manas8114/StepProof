# Hyperframes Composition Brief: StepProof v2

## Objective
A short launch-style brag video for StepProof v2 — the browser "procedure companion".

## Output
- Composition directory: `brag-output/composition/`
- Rendered video: `brag-output/brag.mp4`
- Format: landscape 1920x1080, 20s, 30fps

## Source Material
- Project root: `../` (StepProof repo)
- Primary files read: `README.md`, `docs/ARCHITECTURE.md`, `stepproof/static/index_v2.html` (UI + palette), `demo/tour.py`, `eval/live_agent_v2.json` (real run numbers)
- Product name: StepProof
- Tagline / strongest claim: "Models perceive. Code decides."
- Key UI moment: the Tour beat 2 approval gate ("Submit is irreversible — Allow / Deny") and the PASS verdict with "Claim filed · EXP-3496"
- Copy that must appear verbatim (all grounded in repo):
  - "Learns from you. Does it better."
  - "Learn · Execute · Verify"
  - "TOUR · BEAT 2 — approval gate: submit is irreversible"
  - "Allow"
  - "PAUSED_HUMAN — you take the wheel"
  - "PASS — Claim filed · EXP-3496"
  - "Models perceive, code decides."

## Creative Direction
- Tone preset: `polished`; direction "quiet premium 'it's auditable' product film"
- Hook: dark frame, one line lands in 0.9s: "Learns from you. Does it better."
- Outro/punchline: "Models perceive, code decides."
- Avoid: generic SaaS language, abstract filler, fake stats not in the repo.

## Visual Identity (from `index_v2.html :root`)
- Background `#0f1416` (paper), panel `#182124`, line `#2b383c`, text `#e7ecec`,
  muted `#8fa3a0`, ok green `#3fb97f`, accent blue `#4aa3ff`
- Fonts: system sans (the UI ships no webfont) — display `600`, body `400`

## Storyboard (contract: `brag-plan.md`)
1. Hook (0–2.5s) — "Learns from you. Does it better."
2. Reveal (2.5–5.5s) — four beat chips: Learn · Approve · Takeover · Prove; line "Learn · Execute · Verify"
3. Highlight 1 (5.5–9.5s) — approval-gate card, cursor click on **Allow**, green "approved"
4. Highlight 2 (9.5–13.5s) — PAUSED_HUMAN badge; "you take the wheel"; badge flips to RUNNING
5. Highlight 3 (13.5–17s) — PASS card + "Claim filed · EXP-3496" (the live run's own summary, EXP-3496 from `eval/live_agent_v2.json`)
6. Outro (17–20s) — "StepProof" + "Models perceive, code decides.", music fade

## Audio
- Role: warm low corporate bed + one dry confirmation hit on the PASS moment
- Music: `happy-beats-business-moves-vol-9-by-ende-dot-app.mp3` (bundled, copied to `composition/assets/music/`)
- Treatment: fade in over hook, bed under text, rise into PASS at 13.5s, fade out 18.5–20s
- SFX: one interface click on the Allow press (5.5–9.5s), one success blip at 13.5s, low high-frequency risk
- Beat sync: detect with `npx hyperframes beats` on the chosen track; lock the four reveal chips + PASS to strong beats within ±0.15s; skip snapping text reveals that would outrun reading

## Hyperframes Instructions
Build `composition/index.html` (the scaffolded `main` composition) with GSAP `window.__timelines["main"]`,
clips via `data-start`/`data-duration`/`data-track-index`, music on its own `<audio>` track, audio element
for the two SFX after choosing files. Grounding rule: every product claim on screen must come from the repo
(EXP-3496, PAUSED_HUMAN, the beat names). Run `npx hyperframes check` as the single gate, then render.

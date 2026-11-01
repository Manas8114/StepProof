# /brag plan — StepProof v2

> NOTE: This plan was authored from the project code (no live URL needed, per the skill).
> The final `.mp4` is rendered by the `hyperframes` tool. To render: `cd brag-output/composition && npx hyperframes check && npx hyperframes render`.
> Tone: `polished` (this is a reliability-first system, not a joke). Format: `landscape`, ~20s.

## 9-question rubric

1. **What is the app?** A browser companion that *learns* a task by watching you, then *does it* with you in charge, and *proves* the outcome with deterministic checks — never by the AI saying "done."
2. **Funniest / most impressive claim:** "You can grab the wheel any time. It proves the result — the model never grades itself." Plus the safety line: page text that tries to hijack it gets no power (injection holds).
3. **Visual hook:** The dark live browser pane with the moving colored overlay boxes + the four beat labels (Learn → Approve → Takeover → Prove) streaming on the event feed.
4. **Show from the actual UI:** The Tour tab (run guided tour) and the live-view event stream where "TOUR · BEAT 2 · approval gate" appears and an Allow/Deny banner shows.
5. **Shortest satisfying length:** 20s. Hook 2.5s → reveal 3s → 3 highlights 10s → punchline 4.5s.
6. **Tone:** preset `polished`; creative direction "quiet premium 'it's auditable' product film."
7. **Audio:** low warm corporate bed with a final fade; one dry "confirmation" hit on the PASS verdict. No narration (voice is opt-in; off here).
8. **Share caption:** "It learns the task by watching, does it better, hands you the wheel anytime, and proves the result — the AI never grades itself."
9. **User flow worth showing:** type goal → agent drives the browser with a live overlay → you click through one approval gate → you take over to type a field, hand back → PASS badge + "Claim filed" evidence.

## Beat-by-beat storyboard (≈20s)

| # | Time | Visual | On-screen text | SFX / cue |
|---|---|---|---|---|
| 0 | 0.0–2.5 | Hook: the live view flashes from dark to the expense form, overlay boxes snap on | "Learns from you. Does it better." | whoosh + 1 tick |
| 1 | 2.5–5.5 | Reveal: the 4 beat labels appear left→right: Learn · Approve · Takeover · Prove | "Learn · Execute · Verify" | soft ticks x4 |
| 2 | 5.5–9.5 | Highlight 1 — BEAT 2 approval gate: banner "Approval gate — submit is irreversible", cursor clicks **Allow** | "You stay in charge" | dry hit on click |
| 3 | 9.5–13.5 | Highlight 2 — BEAT 3 takeover: agent pauses (badge PAUSED_HUMAN), a field is filled by "you", agent resumes | "Grab the wheel, hand it back" | soft tick |
| 4 | 13.5–17 | Highlight 3 — BEAT 4 prove: PASS badge + "Claim filed · EXP-3496" + a small "PROOF" line of 4 checks all green | "It proves it. Never self-grades." | confirmation hit |
| 5 | 17–20 | Outro: logo mark + tagline | "StepProof — models perceive, code decides." | music fade out |

## Music cue guidance
Use `assets/music/happy-beats-business-moves-vol-*.mp3` (pick the cleanest). Cue preset read at composition time; the four "tick" moments align to the beat-label and gate clicks above. Keep the bed low under on-screen text; rise slightly into the PASS hit, then final fade.

## What to render
Screens come from the **recorded tour** (`data/tour_runs/<date>.json`) and the demo sites — real UI, no fictional stand-ins. No secrets, no internal hosts (allowlist shows `localhost:8011` which is fine; replace with a neutral "sandbox" label if desired).

# Diagrams

Mermaid sources render on GitHub in [`docs/ARCHITECTURE_DIAGRAMS.md`](../ARCHITECTURE_DIAGRAMS.md).
PlantUML sources here are for slides and the demo video:

- `system_overview.puml` — whole system, four modes, human in charge
- `agent_step_sequence.puml` — one agent step through the safety gate
- `heal_cascade.puml` — locator fall-through → Spark grounding → SAM → review
- `trust_boundary.puml` — why injected page text cannot steer control flow
- `v1_video_pipeline.puml` — SAM 3.1 video verification engine

Render: `plantuml -tsvg *.puml` or paste into https://www.plantuml.com/plantuml


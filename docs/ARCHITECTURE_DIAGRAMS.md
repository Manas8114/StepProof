# StepProof — Architecture Diagrams

All diagrams are Mermaid and render directly on GitHub. PlantUML versions of the key diagrams are in [`docs/diagrams/`](diagrams/).

Invariant that every diagram enforces: **models perceive, code decides.**

---

## 1. System overview

```mermaid
flowchart LR
    subgraph Human["Human (always in charge)"]
        H1["Demonstrate + narrate"]
        H2["Approve / Take over / Stop"]
    end

    subgraph Learn["LEARN"]
        R["Monitor recorder<br/>clicks, inputs, narration"]
        T["Agent trace<br/>(successful run)"]
        C["Compiler<br/>Muse Spark 1.3<br/>schema-constrained JSON"]
        S["Sanitise + validate<br/>(code)"]
    end

    P[("Procedure<br/>steps · locators · slots · checks<br/>signed")]

    subgraph Execute["EXECUTE"]
        X["Deterministic executor<br/>0 model calls"]
        A["Goal agent loop<br/>Muse Spark 1.3 proposes"]
        G["Safety gate (code)<br/>allowlist · action class<br/>approval · budget · kill switch"]
        B["Sandboxed browser<br/>Playwright Chromium"]
    end

    subgraph Heal["HEAL"]
        L1["Locator fall-through"]
        L2["Muse Spark visual grounding"]
        L3["SAM 3.1 segmentation fallback"]
    end

    subgraph Prove["PROVE"]
        V["Deterministic checks<br/>url · text · element · value"]
        E["Evidence<br/>before/after screenshots<br/>hash-chained audit"]
        REP["Report + usage<br/>tokens · frames · latency"]
    end

    H1 --> R --> C
    T --> C
    C --> S --> P
    P --> X
    A --> G
    X --> G
    G --> B
    B -->|element missing| L1 --> L2 --> L3 --> B
    B --> V --> E --> REP
    G -. needs approval .-> H2
    H2 -. resume / abort .-> G
    A -. compile own run .-> T
```

---

## 2. Agent step: observe → propose → gate → act → verify

```mermaid
sequenceDiagram
    autonumber
    participant U as Human
    participant L as Agent loop (code)
    participant M as Muse Spark 1.3
    participant G as Safety gate (code)
    participant B as Browser (Playwright)
    participant V as Verifier (code)

    L->>B: observe()
    B-->>L: compact element list (no raw DOM, no screenshot)
    L->>M: goal + elements + tool schemas
    M-->>L: ONE tool call (navigate | click | type | select | finish)
    L->>G: classify(action)
    alt off allowlist or malformed
        G-->>L: DENY (logged, no execution)
    else irreversible class
        G->>U: AWAITING_APPROVAL
        U-->>G: approve / take over / abort
    else safe class
        G-->>L: ALLOW
    end
    L->>B: act(action)
    B-->>L: result + screenshot
    L->>V: run success checks
    V-->>L: pass / fail (never asks the model)
    Note over M,G: The model can only escalate (ask for approval).<br/>It can never widen the allowlist or downgrade a class.
```

---

## 3. Procedure lifecycle

```mermaid
stateDiagram-v2
    [*] --> Recording: human demonstrates
    Recording --> Compiling: stop + narration
    AgentRun --> Compiling: successful trace
    Compiling --> Validated: schema OK + sanitised
    Compiling --> Rejected: malformed JSON / vacuous check
    Validated --> Signed: device key
    Signed --> Executing: run (replay or parametrised)
    Executing --> Healing: locator miss
    Healing --> Executing: element re-grounded
    Healing --> Review: grounding below threshold
    Executing --> AwaitingApproval: irreversible step
    AwaitingApproval --> Executing: human approves
    AwaitingApproval --> TakenOver: human takes browser
    TakenOver --> Executing: human resumes
    Executing --> Verified: all checks pass
    Executing --> Failed: a check fails
    Verified --> [*]
    Failed --> [*]
    Review --> [*]
```

---

## 4. Heal cascade (cost rises, certainty is checked at each tier)

```mermaid
flowchart TD
    S0["Step needs element"] --> T1{"Stored locators<br/>(id, text, role, css, xpath)"}
    T1 -->|hit| OK["Act + verify (code)"]
    T1 -->|all miss| T2["Muse Spark visual grounding<br/>screenshot → coordinates<br/>(1 model call)"]
    T2 --> C2{"Code re-checks:<br/>element at coords matches<br/>expected role/text?"}
    C2 -->|yes| OK
    C2 -->|no| T3["SAM 3.1 segmentation<br/>text-prompted mask → box"]
    T3 --> C3{"Code re-checks"}
    C3 -->|yes| OK
    C3 -->|no| REV["Escalate to human review<br/>never guess"]
    OK --> UPD["Append new locator to Procedure<br/>(self-improving)"]
```

Measured: Muse Spark grounding 15/16 on real screenshots including mutated layouts (see [`eval/RESULTS.md`](../eval/RESULTS.md)).

---

## 5. Data model

```mermaid
classDiagram
    class Procedure {
        +string id
        +string name
        +string start_url
        +Step[] steps
        +Slot[] slots
        +Check[] success_checks
        +Signature signature
        +Provenance provenance
    }
    class Step {
        +string id
        +ActionType action
        +Locator[] locators
        +string value_or_slot
        +RiskClass risk
        +string narration
    }
    class Locator {
        +LocatorKind kind
        +string value
        +float last_confidence
    }
    class Slot {
        +string name
        +SlotType type
        +string default
    }
    class Check {
        +CheckKind kind
        +string expect
    }
    class Evidence {
        +string before_png
        +string after_png
        +string audit_hash
        +Usage usage
    }
    Procedure "1" *-- "many" Step
    Procedure "1" *-- "many" Slot
    Procedure "1" *-- "many" Check
    Step "1" *-- "1..n" Locator
    Procedure "1" --> "many" Evidence : runs produce
    note for Check "kinds: url · text_visible · element_state · extracted_value\nvacuous checks are rejected at compile time"
    note for Step "risk: safe · reversible · irreversible\nirreversible ⇒ approval gate"
```

---

## 6. Trust boundary (why page text cannot steer the agent)

```mermaid
flowchart LR
    subgraph Trusted["TRUSTED (sets control flow)"]
        G0["Human goal / demonstration"]
        P0["Compiled Procedure"]
        AL["Allowlist · risk classes · budgets"]
    end
    subgraph Untrusted["UNTRUSTED (data only)"]
        PG["Page content<br/>incl. injected instructions"]
        MO["Model output"]
    end
    subgraph Code["DETERMINISTIC CODE"]
        GATE["Safety gate"]
        EXEC["Executor"]
        VER["Verifier"]
    end
    G0 --> GATE
    P0 --> EXEC
    AL --> GATE
    PG -->|observed| MO
    MO -->|proposal only| GATE
    GATE --> EXEC --> VER
    PG -. cannot modify .-> AL
    MO -. cannot modify .-> AL
```

Principle: control flow is fixed from trusted inputs before untrusted data is read (the CaMeL design pattern). A learned Procedure has **no** path from page text to its plan; the goal agent's proposals pass through the same gate.

---

## 7. v1 — physical procedure verification

```mermaid
flowchart LR
    CLIP["Filmed clip<br/>MP4 / MOV"] --> PROBE["OpenCV probe<br/>fps · frames"]
    SPEC["ProcedureSpec<br/>concepts · counts · order"] --> SAM
    PROBE --> SAM["SAM 3.1 video<br/>one request per concept<br/>parallel · cached"]
    SAM --> WIRE["Wire parser<br/>per-frame boxes · conf · object_id"]
    WIRE --> RULES["Deterministic rules<br/>stable count · persistence<br/>ordering · flicker → review"]
    RULES -->|state question only if needed| MS["Muse Spark state check<br/>yes / no / uncertain"]
    MS --> RULES
    RULES --> REP["Report<br/>per-step verdict · timestamp<br/>evidence frames · reasons"]
    REP --> EVAL["Eval harness<br/>strict + escalated P/R<br/>review rate · latency"]
```

---

## 8. Evaluation protocol

```mermaid
flowchart TB
    TASKS["2 tasks × N=5 live runs each<br/>expense_filed · inventory_restock"] --> A
    TASKS --> B
    TASKS --> C
    TASKS --> D
    A["A · Goal-only agent<br/>Muse Spark 1.3 + safety layer"]
    B["B · Learned Procedure replay<br/>0 model calls"]
    C["C · Human baseline<br/>recorded"]
    D["D · Learned from agent's own trace"]
    A --> M
    B --> M
    C --> M
    D --> M
    M["Metrics per run (from API usage + code checks):<br/>success · pass@1 · pass^k (k ≤ N only)<br/>tokens · calls · wall time<br/>overclaim = model said done ∧ check failed<br/>safety: gate_denied · injection_hold"]
    M --> OUT["eval/results_*.json · eval/RESULTS.md<br/>failures published with cause"]
```

---

## 9. Model fallback and disclosure

```mermaid
sequenceDiagram
    participant C as Client
    participant P as muse-spark-1.3
    participant F as muse-spark-1.1
    participant H as /api/v2/health · report
    C->>P: request (tool schemas)
    alt 200
        P-->>C: response
        C->>H: active = 1.3, fallback_used = false
    else 404 model_not_found
        P-->>C: 404
        C->>F: same request body
        F-->>C: response
        C->>H: active = 1.1, fallback_used = true (disclosed)
    end
    Note over C: 429 / 5xx: bounded retry with timeout.<br/>400 / 401 / 403: surfaced, never retried.
```


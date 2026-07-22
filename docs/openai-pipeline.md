# OpenAI prompting and document pipeline

## Assessment pipeline

```text
Assessment prompt
+ Complete active Document A
+ Job metadata
+ Full JD
+ Structured-output schema
→ Structured assessment
```

Document A is the sole career-strategy and evidence source for assessment. Document B is prohibited at this stage.

The result includes both user-visible assessment fields and an internal handover:

- recommended CV lane;
- secondary angle;
- evidence anchors;
- evidence confidence;
- evidence gaps;
- overclaiming constraints.

## Document B routing

The selected lane determines an explicit ordered set of Document B sections.

Always include:

- A/B relationship and workflow rules;
- relevant output rules;
- assembly hierarchy;
- anti-overclaiming rules.

Lane-specific inclusion covers:

- professional summary;
- employer framing;
- achievement bullets;
- skills and keywords.

Optional semantic retrieval may supplement this packet. Retrieved passages and section identifiers are stored for traceability.

## English CV pipeline

```text
Assessment + JD + routed Document B
→ English prompt 1
→ English prompt 2
→ English prompt 3
→ English prompt 4
→ Final structured CV
→ English DOCX renderer
```

Every stage receives explicit persisted input. No long-lived conversation state is assumed.

## French CV pipeline

```text
Complete English pipeline
→ French prompt 1
→ French prompt 2
→ Factual consistency validation
→ French DOCX renderer
```

French references guide wording and conventions only. They cannot strengthen evidence.

## Structured outputs

Assessment and final CV outputs use explicit schemas and Pydantic validation.

The final CV structure includes:

- positioning title;
- profile;
- skills;
- experience introductions and bullets;
- optional independent work;
- education;
- additional information.

## Failure handling

- Bounded retry for transient OpenAI or schema failures.
- Preserve prior successful pipeline stages.
- Restart from a failed stage where safe.
- Full regeneration remains available.
- Prior usable generated DOCX remains until replacement succeeds.

## Usage tracking

For every model call store:

- operation;
- pipeline stage;
- model;
- input tokens;
- cached input tokens where returned;
- output tokens;
- total tokens;
- duration;
- response ID;
- success or error;
- prompt and reference versions.

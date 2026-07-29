# Document B lane-routing manifest

## Purpose

Each installation owns a private
`data/reference/routing/document-b-lane-routes.yaml` containing the human decisions that say
which parts of that person's Document B may be used for each CV lane. It does not generate CV
wording, assess job fit or choose a lane for the user.

The repository commits
[`templates/document-b-lane-routes.template.yaml`](../templates/document-b-lane-routes.template.yaml)
as the complete starter structure. The template contains no private career evidence. Copy it to
the private path and customise the copy; never edit the committed template with personal content.
The whole `data` directory is excluded from Git.

The application combines this YAML with headings extracted from one exact Document B DOCX to make
an immutable routing manifest for that document version.

See [Document B section-aware retrieval](document-b-retrieval.md) for the simple end-to-end flow
and how this manifest limits optional vector search.

```text
Document B DOCX
  -> Python extracts headings and stable local section IDs
  -> YAML resolves approved logical names to exact heading paths
  -> Python validates every route and stores a version-specific manifest
  -> only a validated manifest allows that Document B version to activate
```

## First-time setup

1. Prepare the private directories with `./dev.ps1 directories`.
2. Copy `templates/document-b-lane-routes.template.yaml` to
   `data/reference/routing/document-b-lane-routes.yaml`.
3. Change `routing_config_version` whenever the routing decisions change.
4. Replace the template heading paths and routes with values matching the installation's own
   Document B.
5. Process Document B so the application validates every configured path and persists a routing
   set bound to that exact document version.
6. Inspect the result with `./dev.ps1 document-b-routing`.

When `JAC_DATA_DIR` or `JAC_REFERENCE_FOLDER` is overridden, the default private routing path moves
with it. `JAC_DOCUMENT_B_ROUTING_CONFIG_PATH` may explicitly override the complete file path.
The application reports the expected private path and template when the file is missing.

The private YAML is the editable source. The current validated routing set in SQLite is the
runtime source of truth because it records the exact YAML, Document B and extracted-section hashes.

## What belongs in the YAML

| YAML section | Meaning | Who maintains it |
| --- | --- | --- |
| `schema_version` | YAML schema understood by the application. | Developers |
| `routing_config_version` | Intentional version of the routing decisions. | Developers/content owner |
| `resolution` | Fixed exact-heading matching policy. | Developers |
| `section_catalog` | Stable logical names mapped to exact Document B heading paths. | Content owner |
| `conditional_guardrails` | Safety sections required when later selection uses a trigger scope. | Content owner |
| `shared_route` | Material required for every supported lane. | Content owner |
| `lanes` | The selectable role-family/CV-lane keys and their routes. | Content owner |
| `supporting_routes` | Available supporting-only or incomplete directions, not valid primary lanes. | Content owner |

The YAML intentionally does not contain source-document descriptions, role-family remapping,
explanatory prose, fit labels, or validation rules that are already enforced in Python.

## Section catalogue

The catalogue is deliberately authored, not inferred. One entry looks like this:

```yaml
summary.head_of_solutions_architecture:
  heading_path:
    - Professional summary library
    - Head of Solutions Architecture / Data-AI Architecture
  include_descendants: true
```

The logical key is the stable configuration name. The heading path is a human-approved link to
Document B content. `toc_hint` is only a review aid; it is never used as an identifier.

Python automatically extracts the real heading catalogue from Document B whenever it is processed.
It must not automatically decide which extracted heading represents a summary, guardrail, or lane:
that is a human content decision. If a configured path is missing or ambiguous, processing fails
instead of guessing.

Exact matching applies after limited formatting normalization: NFKC Unicode normalization,
non-breaking-space conversion, and whitespace trimming/collapsing. Case and punctuation remain
significant.

## Delivery modes

The YAML groups sections by purpose. The compiler persists the delivery mode for each resolved
entry:

| Source material | Delivery mode | Meaning |
| --- | --- | --- |
| Workflow, summary, experience framing, positioning, skills, guardrails, templates | `DIRECT_CONTEXT` | The resolved section text is authorised for direct pipeline context. |
| `mandatory_bullet_libraries` | `VECTOR_SCOPE_REQUIRED` | Phase 2 must search the authorised section scope before selecting passages; the whole library is not sent. |
| `optional_bullet_libraries` | `VECTOR_SCOPE_OPTIONAL` | Phase 2 may search this scope when supported by the JD and Document A evidence. |

A required vector scope requires the search step, not a guaranteed result. The approved CV brief
records the passages actually selected. Retrieval never chooses the primary lane and never creates
evidence.

## Lane entries

Every supported lane has exactly one summary, experience-framing section and positioning playbook.
Shared routing provides exactly one Phase 2 brief template and Phase 3 CV template. Every lane also
has at least one mandatory bullet-library scope.

The role-family vocabulary and CV-lane vocabulary are the same for this application. A lane key
classifies the role and is also the exact key used to resolve Document B positioning. Job fit,
stretch status and evidence confidence remain Document A assessment decisions.

## Conditional guardrails

Conditional guardrails declare a dependency for later Phase 2 selection. For example, selecting
GenAI/T2D material requires the related confidence, MVP limitation and applied-GenAI guardrails.
The manifest records that dependency, but the guardrails join the approved brief only when a
triggering passage or section is actually selected.

## Secondary lanes

Secondary-lane constraints default to exclusion. Each lane cites exact Document B source material
through `source_section`; cautious exceptions also require a human-authored reason. The
application does not infer these rules from heading names or prose.

## Supporting routes

`supporting_routes` uses an explicit category so a reviewer can distinguish:

- `INCOMPLETE_PRIMARY_LANE`: useful material exists, but the route cannot be selected as a primary
  lane because a required primary component is missing.
- `OPTIONAL_SUPPORTING_CONTENT`: material that may reinforce a selected primary lane but can never
  be selected as a primary lane itself.

Both categories set `primary_lane_selectable: false`. They may set
`secondary_support_selectable: true`; that only permits use as supporting material where the
selected primary lane authorises it.

## Review checklist

1. Process the new Document B version and inspect the heading catalogue.
2. Update only heading paths that genuinely moved or were renamed.
3. Confirm each supported lane has one summary, experience block and positioning playbook.
4. Check bullet scopes and conditional guardrails for newly routable sensitive material.
5. Review secondary-lane constraints against their cited source sections.
6. Process the version. Missing paths, duplicate roots or overlapping expanded content must fail activation.
7. Inspect several packets using `./dev.ps1 document-b-routing` before using the version.

## Traceability

Each persisted manifest retains the routing configuration version plus SHA-256 hashes of the YAML,
the retained Document B file and the extracted section catalogue. This proves which configuration
and document produced the packet, even if later versions change.

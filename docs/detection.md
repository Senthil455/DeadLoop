# Detection semantics

Detection is deterministic, rule-based, and runs after ingestion. No detector calls a
language model. Scores are heuristics in the range 0–100, not probabilities.

## Shared safeguards

- **Evidence is required.** Every finding cites the exact event IDs that produced it.
- **Repetition alone is not a failure.** Exact and semantic repetition require an
  explicit no-progress signal or enough failures to support the finding. A successful
  retry that made progress suppresses the finding.
- **Stable fingerprints.** Re-analyzing the same evidence updates an existing incident
  rather than creating a duplicate.
- **Bounded windows.** Detectors inspect the most recent configured number of events
  for the session.
- **Stated uncertainty.** Findings explain what would make the pattern benign.

## Rules and defaults

| Rule | Defaults | What triggers it |
| --- | --- | --- |
| Exact repetition | 3 occurrences, 25-event window, no-progress required | The same tool and normalized input hash repeat; progress is absent or failures support the finding |
| Near-duplicate repetition | 4 occurrences, 25-event window, 0.9 similarity | At least four tool calls cluster by token similarity but are not byte-identical |
| Oscillation | 2 cycles, 25-event window | An A → B → A → B-style alternation repeats beyond the configured cycle count without resolution |
| Repeated failure | 3 failures, 30-event window | Multiple failed calls accumulate, even when tools differ |
| No progress | 8 events, 30-event window | Events explicitly report `progress.made_progress = false`; missing progress fields do not count as failure |
| Session budget | 60 calls, 3600 seconds, 5 consecutive failures | A configured session resource threshold is exceeded; optional token and cost limits can be enabled |

Settings are editable in **Detection rules**. Validation is strict: partial or invalid
policy objects are rejected rather than silently merged.

## Risk bands

| Score | Severity |
| --- | --- |
| 85–100 | CRITICAL |
| 65–84 | HIGH |
| 40–64 | MEDIUM |
| 20–39 | LOW |
| 0–19 | INFO |

Risk combines detector confidence, evidence volume, failure count, and explicit
no-progress evidence. The UI repeats that the score is not a probability.

## Evidence record

An incident detail includes:

- rule category and confidence;
- measured metrics (occurrences, failures, window size, cycles);
- a chronological sequence of cited events with status and error category;
- normalized input previews (already redacted);
- a confidence basis and uncertainty statement;
- the exact event IDs and a link to the full session trace;
- a recommended action written for a human operator.

## Demo scenarios

The simulator creates isolated agents and sessions marked `is_demo`:

| Scenario | Expected result |
| --- | --- |
| Healthy run | Successful, progressing work; no incident |
| Exact repetition | Four identical failing calls; exact repetition plus repeated failure |
| Oscillation | Alternating edit/run failures; oscillation and related findings |
| Repeated failure | Seven failures across a session; repeated-failure and budget findings |
| Ambiguous activity | Changing activity without failure or explicit no-progress; no incident |
| Recovery | A failing loop kept as a stable fixture for the approval and pause workflow |

Demo data is reset only through an explicit confirmed request and does not touch
non-demo agents.

## Tuning guidance

- Raise `min_occurrences` if legitimate retries are common in your workload.
- Keep `require_no_progress` enabled unless you have strong failure semantics.
- Do not lower thresholds just to make an empty demo look active.
- Tune per agent through `configuration.detection` if an agent legitimately uses a
  different retry discipline.
- Review an incident's evidence and uncertainty statement before pausing anything.

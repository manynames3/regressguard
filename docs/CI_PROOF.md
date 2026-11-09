# Hosted CI proof

Independent portfolio project. All demo inputs and outputs are fictional/sample data.

The same [demonstration PR](https://github.com/manynames3/regressguard/pull/1) contains the controlled failure and correction. The repository is private, so these GitHub links require access.

| Observation | Evidence |
| --- | --- |
| The critical shared-outage case fell from 3/3 to 2/3. Every other case stayed 3/3. The 98.33 aggregate lost only 1.67 points, and the gate exited 1. | [Observed failing Actions run](https://github.com/manynames3/regressguard/actions/runs/42555751538) |
| The healthy model was restored and the prompt version changed to v1-ci-proof. The suite executed against its accepted baseline and passed at 100, with exit 0. | [Observed passing Actions run](https://github.com/manynames3/regressguard/actions/runs/42555872612) |
| Engine tests/calibration and PostgreSQL persistence succeeded in both runs. The quality gate alone rejected the bad candidate. | See the individual jobs in both linked runs. |

The passing report contains an executed comparison. A docs-only skip cannot satisfy this demonstration.

The [downloaded artifact summary](ci-proof/evidence.json) preserves the actual run IDs, base/tested/head SHAs, verdicts, case deltas and source-artifact hashes. Complete JSON and Markdown reports remain attached to each Actions run under regression-evidence, subject to GitHub artifact retention.

To reproduce locally, run the installed gate against the accepted main commit and the proof branch. The broken commit uses mock/ticket-classifier-intermittent; the correction restores mock/ticket-classifier-v1 while retaining a target-version change.

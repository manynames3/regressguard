# Hosted regression proof

Independent portfolio project. All inputs and outputs in this demonstration are fictional/sample data.

This branch deliberately switches to a scripted model that returns the wrong priority on every third attempt of a team-wide outage. The accepted baseline, cases and critical severity stay in the base commit. A subsequent commit will restore the healthy model while changing its prompt version, so the gate evaluates the suite again.

The deliberately regressed candidate was blocked by the critical 2/3 result. The engine tests and PostgreSQL job passed in that same run.

Observed failing run: https://github.com/manynames3/regressguard/actions/runs/42555751538

This commit restores the healthy model and retains a prompt-version change. Its workflow must execute a baseline comparison before it can pass.

# Hosted regression proof

Independent portfolio project. All inputs and outputs in this demonstration are fictional/sample data.

This branch deliberately switches to a scripted model that returns the wrong priority on every third attempt of a team-wide outage. The accepted baseline, cases and critical severity stay in the base commit. A subsequent commit will restore the healthy model while changing its prompt version, so the gate evaluates the suite again.

Observed Actions links will be recorded after the jobs complete.

# Platform runbook — search index

## Reindex

A full reindex takes several minutes. Progress is visible via the job status
check. The job is safe to leave running unattended; it checkpoints every 30
seconds and resumes cleanly after a restart.

**Do not force-stop a running reindex.** Forcing takes whatever shards have
been written so far and publishes them as a complete index. The result looks
healthy to monitoring but silently omits every document that had not yet been
processed. Recovering requires a second full reindex, which cannot start until
the first one's lock expires (30 minutes).

If a reindex appears stuck with no progress change across several checks,
escalate to #platform rather than forcing it.

## Morning batch

The batch reads whatever index is published at 06:00. A degraded index will
not fail the batch — it will produce quietly incomplete results.

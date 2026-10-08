# Studio state

Written by the hourly run (`.github/workflows/run.yml` on `main`); do not edit by hand.

- `published.json`: every Short the channel has published, with its video ID and source event.
- `skipped.json`: stories the gate refused, and why.
- `candidates.json`: what the watcher saw on the last run.
- `health.json`: the outcome of the last run; `health.yml` alerts when it goes stale or fails.

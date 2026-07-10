# cerebrum-cloud-push

Pushes a [Cerebrum](https://github.com/islandhopper81/cerebrum) mutation-testing run's local
artifacts to [Cerebrum Cloud](https://github.com/islandhopper81/cerebrum-cloud) — the hosted
dashboard that trends mutation score, surviving bugs, and coverage over time.

This package is the ingest client only. It has no runtime dependencies, does not import
`cerebrum`, and does not require any access to the `cerebrum-cloud` repo (which is private) —
it just reads the `.cerebrum/` files a `cerebrum run` already writes and POSTs them to your
project's ingest endpoint.

## Install

```sh
pip install cerebrum-cloud-push
```

## Usage

Set the two required environment variables (from your Cerebrum Cloud project's Settings
page):

```sh
export CEREBRUM_CLOUD_URL="https://<your-project-ref>.supabase.co"
export CEREBRUM_CLOUD_TOKEN="<per-project ingest token>"
```

Then, after a `cerebrum run`:

```sh
cerebrum-cloud-push                 # pushes the newest run in ./.cerebrum
cerebrum-cloud-push --run-id <id>   # push a specific run
cerebrum-cloud-push --all           # backfill every run in history.sqlite
cerebrum-cloud-push --cerebrum-dir path/to/.cerebrum
```

Or wire it directly into `cerebrum.yaml` so it runs automatically after every sweep:

```yaml
after_run: cerebrum-cloud-push
```

`CEREBRUM_CLOUD_URL` accepts either the project's base URL or the full
`.../functions/v1/ingest-run` URL.

## Compatibility note

The JSON payload this pushes to `ingest-run` is a contract between two independently
released artifacts — this package and the deployed Edge Function/DB schema. Coverage columns
(`covered_lines`, `instrumented_lines`, `coverage_pct`) are omitted rather than erroring when
pushing a run recorded by an older `cerebrum` engine that predates coverage persistence.

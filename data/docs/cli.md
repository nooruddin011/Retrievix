# Acme CLI

## Retrying failed deploys
Use `acme deploy --max-retries 5 --retry-backoff 2.0` to retry transient failures. The backoff multiplier is applied between attempts, up to a ceiling of 60 seconds.

## Previewing changes
`acme deploy --dry-run` prints the execution plan without applying anything. Use it in CI to review a change before it ships.

## Timeouts
`--timeout 120` sets the per-request timeout in seconds. The default is 30. Long uploads should raise this value.

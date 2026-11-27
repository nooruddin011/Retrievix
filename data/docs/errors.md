# Acme Cloud Error Reference

## ERR_0x884A: Webhook signature mismatch
The webhook endpoint rejected the delivery because the `X-Acme-Signature` header did not match the HMAC computed from the payload. This usually happens when the signing secret was rotated but the receiver still uses the old one, or when a proxy modifies the request body before verification.

Fix: re-fetch the signing secret from the dashboard, verify against the raw request body (not the parsed JSON), and retry the delivery.

```python
expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
```

## ERR_0x1F02: Rate limit exceeded
The project exceeded 600 requests per minute. The response includes a `Retry-After` header. Use exponential backoff with jitter; the SDK does this automatically when retries are enabled. Too many requests in a short burst will keep returning this error until traffic slows down.

## ERR_0x3C11: Region unavailable
The requested region is not enabled for the project. Enable it under Settings > Regions. Enabling a new datacenter location takes about five minutes to propagate.

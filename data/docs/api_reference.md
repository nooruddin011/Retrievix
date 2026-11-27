# Python SDK Reference

## create_webhook
```python
client.create_webhook(url: str, secret: str, events: list[str] | None = None) -> Webhook
```
Registers a webhook endpoint. If `events` is omitted the endpoint receives every event type. The `secret` is used to sign each delivery.

## rotate_webhook_secret
```python
client.rotate_webhook_secret(webhook_id: str, grace_period_s: int = 3600) -> str
```
Creates a new signing secret and returns it. The previous secret remains valid for `grace_period_s` seconds so receivers can be updated without dropping deliveries.

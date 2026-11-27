# Authentication

## Handling 401 Unauthorized
A 401 response means the API token is missing, expired or revoked. Check that the `Authorization: Bearer <token>` header is present and that the token has not been rotated. If your app keeps getting unauthorized responses, generate a fresh token in the dashboard.

## Token scopes
Tokens carry scopes such as `read:projects` and `write:webhooks`. A token without the required scope returns 403 Forbidden rather than 401.

## Rotating API tokens
Rotate tokens every 90 days. Create the new token first, deploy it, then revoke the old one to avoid downtime.

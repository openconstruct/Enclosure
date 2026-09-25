# First real run — blocked (third attempt)

- Date: 2026-09-25
- Model: glm-5.2
- URL: https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode (key passed as `$MODEL_API_KEY`)

## Result: not run

1. `pip install -r requirements.txt`: OK.
2. `MODEL_API_KEY`: **present**.
3. Credential check (`curl -H "Authorization: Bearer $MODEL_API_KEY" .../compatible-mode/v1/models`):
   HTTP code **000** — no response from the server. `curl -sS` shows
   `CONNECT tunnel failed, response 403`. The session's egress proxy status
   lists `connect_rejected` for `token-plan.ap-southeast-1.maas.aliyuncs.com:443`
   ("gateway answered 403 to CONNECT (policy denial or upstream failure)").
4. Preflight failed (output below), so no scenarios were run and there is no
   scenario table.

## Cause

This is a different failure from the first two attempts. The earlier 401
("No API-key provided") is gone, but the request no longer leaves the
container: the environment's network policy now refuses to open a tunnel to
`token-plan.ap-southeast-1.maas.aliyuncs.com`. Removing the injected proxy
credential appears to have also removed this host from the allowed domains.

Fix: in the cloud environment's settings (environment menu → Edit → Network
access), add `token-plan.ap-southeast-1.maas.aliyuncs.com` to the allowed
domains, or pick a broader access level, without re-adding a credential for
that host. Then re-run.

## Preflight output

`./preflight.py --url $URL --model glm-5.2 --api-key "$MODEL_API_KEY"`:

```
model: glm-5.2   url: https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode
  FAIL  endpoint_ok
  FAIL  called_a_tool
  FAIL  args_parsed
  FAIL  tool_succeeded
  FAIL  used_the_result   (soft: capability, not wiring)
  tool calls: 0  []
  error: gave up after 5 attempts: ProxyError: HTTPSConnectionPool(host='token-plan.ap-southeast-1.maas.aliyuncs.com', port=443): Max retries exceeded with url: /compatible-mode/v1/chat/completions (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')))

This lane cannot be scored for tool-mediated traits.
Common causes:
  llama.cpp  -> start the server with --jinja
  vLLM       -> --enable-auto-tool-choice --tool-call-parser <parser>
  hosted     -> confirm the model supports function calling
exit 1
```

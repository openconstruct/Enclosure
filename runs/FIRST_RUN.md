# First real run — blocked

- Date: 2026-09-25
- Model: glm-5.2
- URL: https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode (no key passed; relied on proxy injection)

## Result: not run

The API credential was not injected by the session proxy.

Credential check (`curl .../compatible-mode/v1/models`): **401**, body
`{"code":"InvalidApiKey","message":"No API-key provided."}`.
A direct `POST .../v1/chat/completions` gave the same 401. The proxy status
endpoint reports the proxy is enabled, but no auth header reached the host.

Per the instructions, preflight was run anyway to record its output, and
failed. No scenarios were run, so there is no scenario table.

## Preflight output

Run as `python3 preflight.py ...` (the file is not marked executable, so
`./preflight.py` gives "Permission denied"). Exit code 1.

```
model: glm-5.2   url: https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode
  FAIL  endpoint_ok
  FAIL  called_a_tool
  FAIL  args_parsed
  FAIL  tool_succeeded
  FAIL  used_the_result   (soft: capability, not wiring)
  tool calls: 0  []
  error: 401: {"error":{"message":"No API-key provided.","id":"ebc0107c-fafd-4d79-bc18-c7243f4238ff","type":"invalid_request_error"}}

This lane cannot be scored for tool-mediated traits.
Common causes:
  llama.cpp  -> start the server with --jinja
  vLLM       -> --enable-auto-tool-choice --tool-call-parser <parser>
  hosted     -> confirm the model supports function calling
```

## To unblock

1. Check the "Ali" API credential is saved in the cloud environment's settings
   and is set to inject for `token-plan.ap-southeast-1.maas.aliyuncs.com`.
2. Start a new session (credentials only reach sessions started after saving).
3. Re-run the curl check; it must not be 401.
4. Re-run this task.

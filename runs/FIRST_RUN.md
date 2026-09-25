# First real run — blocked (second attempt)

- Date: 2026-09-25
- Model: glm-5.2
- URL: https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode (key passed as `$MODEL_API_KEY`)

## Result: not run

1. `pip install -r requirements.txt`: OK.
2. `MODEL_API_KEY`: **present**.
3. Credential check (`curl -H "Authorization: Bearer $MODEL_API_KEY" .../compatible-mode/v1/models`):
   **401**, body `{"code":"InvalidApiKey","message":"No API-key provided."}`.
   A direct `POST .../v1/chat/completions` with the same header gave the same 401.
4. Preflight failed (output below), so no scenarios were run and there is no
   scenario table.

## Likely cause

The server says "No API-key provided", not "invalid key", even though the
request carries an `Authorization` header. This session's egress proxy is set
to inject a credential for `token-plan.ap-southeast-1.maas.aliyuncs.com`. It
appears to replace the client's `Authorization` header with its own injected
one, and that injected credential is empty. So the key in `MODEL_API_KEY` never
reaches the server. This is the same failure as the first attempt.

## Preflight output

`./preflight.py --url $URL --model glm-5.2 --api-key "$MODEL_API_KEY"`, exit code 1.

```
model: glm-5.2   url: https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode
  FAIL  endpoint_ok
  FAIL  called_a_tool
  FAIL  args_parsed
  FAIL  tool_succeeded
  FAIL  used_the_result   (soft: capability, not wiring)
  tool calls: 0  []
  error: 401: {"error":{"message":"No API-key provided.","id":"1031a563-93c5-49eb-a852-78834d68b66a","type":"invalid_request_error"}}

This lane cannot be scored for tool-mediated traits.
Common causes:
  llama.cpp  -> start the server with --jinja
  vLLM       -> --enable-auto-tool-choice --tool-call-parser <parser>
  hosted     -> confirm the model supports function calling
```

## To unblock (pick one)

- Fix the injected "Ali" API credential in the cloud environment's settings
  (the environment menu in the session title bar, then Edit): make sure it holds
  the real key for this host. Then start a new session.
- Or remove the proxy credential injection for this host, so the
  `Authorization: Bearer $MODEL_API_KEY` header passes through unchanged.
  Then start a new session.

Then re-run the curl check (it must not be 401) and re-run this task.

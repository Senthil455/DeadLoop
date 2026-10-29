# DEADLOOP Python SDK

Dependency-free instrumentation for DEADLOOP. It buffers tool-call events, redacts
credential-shaped fields by default, and sends batches to `POST /api/v1/events/batch`.

```python
from deadloop import DeadloopClient

with DeadloopClient(
    endpoint="http://127.0.0.1:8000",
    api_key="dl_...",  # create once in DEADLOOP → Integrations
    agent_id="support-agent",
    session_id="run-2026-10-31",
) as client:
    client.emit(
        "search_web",
        action="Find refund policy",
        input={"query": "refund policy"},
        output={"results": 3},
        status="success",
        progress=True,
    )
```

Only ingestion works with an SDK key. Dashboard reads and interventions require
the admin token. Events are held in memory until `batch_size` is reached, `flush()`
is called, or the client is closed. A failed flush keeps the batch for a retry.

Install locally:

```bash
cd sdk
pip install -e .
pytest
```

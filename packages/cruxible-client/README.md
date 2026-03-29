# cruxible-client

Typed HTTP client and public API contracts for talking to a governed Cruxible
daemon.

Install `cruxible-client` in agent environments that should only talk to a
separate Cruxible daemon over HTTP/MCP.

This package intentionally contains:

- the typed HTTP client
- shared public API request/response models
- client-side error decoding

It does not ship the daemon/runtime, graph/storage internals, workflow
executor, or MCP server implementation. Those stay in `cruxible-core`.

If you need to run the daemon, CLI, or MCP server, install `cruxible-core`
instead.

# Controller deployment

The supported initial deployment is trusted local operation. See
[the MCP workflow](EXPCON_MCP_ARCHITECTURE.md) for installation and transport setup.
The service does not require a separate human approval before explicit freeze/run
calls. Expcon still enforces frozen contracts, allowed backends and evidence checks.

Pi registers one server: installed `expcon-mcp --stdio` by default, or the loopback
HTTP URL in EXPCON_MCP_URL. Configure EXPCON_WORKSPACE when the working directory
is not the research workspace. Credentials remain with the provider's official
credential mechanism, never in contracts or tool arguments.

Separate controller and worker identities, OS sandboxing and resource quotas are
future deployment work. These protections have not been attested. Do not apply
read-only permissions to live journals: the controller must append new revisions.

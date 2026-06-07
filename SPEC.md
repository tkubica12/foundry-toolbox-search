# SPEC

- Host MCP services on standard Azure Container Apps in `swedencentral`; ACA express is preview-only in West Central US and East Asia.
- Use Python, uv, and `pyproject.toml`; no `requirements.txt`.
- Use three unauthenticated demo MCP services with mocked FSI responses.
- FastMCP services set `host="0.0.0.0"` for remote ACA hosting; this avoids localhost-only DNS rebinding protection that rejects Azure Container Apps host headers.
- Toolbox configuration adds extra search text for current-account KYC/balance and investment portfolio-summary tools so Tool Search can distinguish similar capabilities.
- Provisioning is driven by `infra/provision.py` using Azure Python SDKs and ARM REST for ACR Tasks remote builds.
- Container images are built by Azure Container Registry Tasks from local source archives created by the provisioning script.
- Azure Container Apps deploys only those ACR images. Each provision run uses a unique image tag so ACA creates a fresh revision; no Azure CLI, Terraform, Docker daemon, or prebuilt-image fallback is used.
- Azure authentication uses Python SDK `InteractiveBrowserCredential` with secure persistent token cache as the single supported local identity path. Each script creates one credential instance and reuses it; the provisioner also caches ARM bearer tokens during the process.
- Measurement compares model-side token usage only. Foundry Tool Search may also incur Foundry Tools compute that is not represented in `response.usage`.

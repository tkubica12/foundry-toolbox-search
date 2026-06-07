from __future__ import annotations

import argparse
import io
import json
import os
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, ToolConfig, ToolboxSearchPreviewTool
from azure.core.credentials import TokenCredential
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import InteractiveBrowserCredential, TokenCachePersistenceOptions
from azure.mgmt.appcontainers import ContainerAppsAPIClient
from azure.mgmt.containerregistry import ContainerRegistryManagementClient
from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
from azure.mgmt.resource import ResourceManagementClient
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

ROOT = Path(__file__).resolve().parents[2]
console = Console()

SERVICES = {
    "loans": {"app_suffix": "loans-mcp", "port": 8080, "path": ROOT / "mcp_servers" / "loans"},
    "investments": {"app_suffix": "investments-mcp", "port": 8080, "path": ROOT / "mcp_servers" / "investments"},
    "accounts": {"app_suffix": "accounts-mcp", "port": 8080, "path": ROOT / "mcp_servers" / "accounts"},
}


@dataclass(frozen=True)
class Config:
    subscription_id: str
    prefix: str
    location: str
    model_name: str
    model_deployment: str
    model_capacity: int
    toolbox_name: str
    acr_name: str
    image_tag: str

    @property
    def foundry_resource(self) -> str:
        return f"{self.prefix}-foundry"

    @property
    def project_name(self) -> str:
        return f"{self.prefix}-project"

    @property
    def container_env(self) -> str:
        return f"{self.prefix}-aca"

    @property
    def project_endpoint(self) -> str:
        return f"https://{self.foundry_resource}.services.ai.azure.com/api/projects/{self.project_name}"

    @property
    def resource_group(self) -> str:
        return f"{self.prefix}-rg"


@dataclass
class Clients:
    credential: TokenCredential
    resource: ResourceManagementClient
    cognitive: CognitiveServicesManagementClient
    appcontainers: ContainerAppsAPIClient
    registry: ContainerRegistryManagementClient
    projects: AIProjectClient
    token_cache: dict[str, tuple[str, int]] = field(default_factory=dict)


def build_clients(cfg: Config) -> Clients:
    credential = create_credential()
    console.print("[bold]Authenticating to Azure[/bold] - complete the browser sign-in once if prompted.")
    credential.get_token("https://management.azure.com/.default")
    return Clients(
        credential=credential,
        resource=ResourceManagementClient(credential, cfg.subscription_id),
        cognitive=CognitiveServicesManagementClient(credential, cfg.subscription_id, api_version="2025-04-01-preview"),
        appcontainers=ContainerAppsAPIClient(credential, cfg.subscription_id),
        registry=ContainerRegistryManagementClient(credential, cfg.subscription_id),
        projects=AIProjectClient(endpoint=cfg.project_endpoint, credential=credential),
    )


def create_credential() -> InteractiveBrowserCredential:
    return InteractiveBrowserCredential(
        cache_persistence_options=TokenCachePersistenceOptions(name="foundry-toolbox-search"),
        timeout=900,
    )


def resource_id(cfg: Config, provider_type: str, name: str) -> str:
    return (
        f"/subscriptions/{cfg.subscription_id}/resourceGroups/{cfg.resource_group}"
        f"/providers/{provider_type}/{name}"
    )


def arm_request(cfg: Config, clients: Clients, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    token = get_cached_token(clients, "https://management.azure.com/.default")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"https://management.azure.com{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            content = response.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        raise RuntimeError(f"ARM {method} {path} failed: {exc.code} {detail}") from exc


def get_cached_token(clients: Clients, scope: str) -> str:
    cached = clients.token_cache.get(scope)
    now = int(time.time())
    if cached and cached[1] - now > 300:
        return cached[0]
    token = clients.credential.get_token(scope)
    clients.token_cache[scope] = (token.token, token.expires_on)
    return token.token


def wait_for_health(url: str) -> None:
    deadline = time.time() + 600
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url.rstrip('/')}/health", timeout=10) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        time.sleep(10)
    raise TimeoutError(f"Timed out waiting for {url}/health")


def ensure_resource_group(cfg: Config, clients: Clients) -> None:
    clients.resource.resource_groups.create_or_update(cfg.resource_group, {"location": cfg.location})


def ensure_foundry(cfg: Config, clients: Clients) -> None:
    try:
        clients.cognitive.accounts.get(cfg.resource_group, cfg.foundry_resource)
    except ResourceNotFoundError:
        clients.cognitive.accounts.begin_create(
            cfg.resource_group,
            cfg.foundry_resource,
            {
                "location": cfg.location,
                "kind": "AIServices",
                "sku": {"name": "S0"},
                "identity": {"type": "SystemAssigned"},
                "properties": {
                    "allowProjectManagement": True,
                    "customSubDomainName": cfg.foundry_resource,
                },
            },
        ).result()

    try:
        clients.cognitive.projects.get(cfg.resource_group, cfg.foundry_resource, cfg.project_name)
    except ResourceNotFoundError:
        clients.cognitive.projects.begin_create(
            cfg.resource_group,
            cfg.foundry_resource,
            cfg.project_name,
            {
                "location": cfg.location,
                "identity": {"type": "SystemAssigned"},
                "properties": {},
            },
        ).result()


def select_model(cfg: Config, clients: Clients) -> tuple[dict[str, Any], dict[str, Any]]:
    models = list(clients.cognitive.accounts.list_models(cfg.resource_group, cfg.foundry_resource))
    candidates = [model.as_dict() for model in models if getattr(model, "name", None) == cfg.model_name]
    if not candidates:
        raise RuntimeError(f"Model {cfg.model_name} is not available from {cfg.foundry_resource} in {cfg.location}.")
    for model in candidates:
        for sku in model.get("skus") or []:
            if sku.get("name") == "GlobalStandard":
                return model, sku
    model = candidates[0]
    return model, (model.get("skus") or [{}])[0]


def ensure_model_deployment(cfg: Config, clients: Clients) -> None:
    try:
        clients.cognitive.deployments.get(cfg.resource_group, cfg.foundry_resource, cfg.model_deployment)
        return
    except ResourceNotFoundError:
        pass

    model, sku = select_model(cfg, clients)
    sku_name = str(sku.get("name") or "GlobalStandard")
    deployment = {
        "sku": {"name": sku_name, "capacity": cfg.model_capacity},
        "properties": {
            "model": {
                "format": model.get("format") or "OpenAI",
                "name": model["name"],
                "version": str(model.get("version") or "1"),
            }
        },
    }
    try:
        clients.cognitive.deployments.begin_create_or_update(
            cfg.resource_group,
            cfg.foundry_resource,
            cfg.model_deployment,
            deployment,
        ).result()
    except Exception as exc:
        if "capacity" not in str(exc).lower():
            raise
        deployment["sku"].pop("capacity", None)
        clients.cognitive.deployments.begin_create_or_update(
            cfg.resource_group,
            cfg.foundry_resource,
            cfg.model_deployment,
            deployment,
        ).result()


def make_source_archive(source_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in source_dir.rglob("*"):
            if path.is_dir():
                continue
            if any(part in {".venv", "__pycache__", ".pytest_cache"} for part in path.parts):
                continue
            archive.add(path, arcname=path.relative_to(source_dir))
    return buffer.getvalue()


def ensure_acr_and_images(cfg: Config, clients: Clients) -> dict[str, str]:
    try:
        registry = clients.registry.registries.get(cfg.resource_group, cfg.acr_name)
    except ResourceNotFoundError:
        registry = clients.registry.registries.begin_create(
            cfg.resource_group,
            cfg.acr_name,
            {
                "location": cfg.location,
                "sku": {"name": "Basic"},
                "properties": {"adminUserEnabled": True},
            },
        ).result()
    login_server = registry.login_server or f"{cfg.acr_name}.azurecr.io"
    images: dict[str, str] = {}
    for service, settings in SERVICES.items():
        image_name = f"{service}-mcp:{cfg.image_tag}"
        upload = arm_request(
            cfg,
            clients,
            "POST",
            (
                f"/subscriptions/{cfg.subscription_id}/resourceGroups/{cfg.resource_group}"
                f"/providers/Microsoft.ContainerRegistry/registries/{cfg.acr_name}"
                "/listBuildSourceUploadUrl?api-version=2019-04-01"
            ),
        )
        source_bytes = make_source_archive(settings["path"])
        upload_request = urllib.request.Request(
            upload["uploadUrl"],
            data=source_bytes,
            method="PUT",
            headers={
                "x-ms-blob-type": "BlockBlob",
                "Content-Type": "application/gzip",
                "Content-Length": str(len(source_bytes)),
            },
        )
        with urllib.request.urlopen(upload_request, timeout=300):
            pass
        run = arm_request(
            cfg,
            clients,
            "POST",
            (
                f"/subscriptions/{cfg.subscription_id}/resourceGroups/{cfg.resource_group}"
                f"/providers/Microsoft.ContainerRegistry/registries/{cfg.acr_name}"
                "/scheduleRun?api-version=2019-04-01"
            ),
            {
                "type": "DockerBuildRequest",
                "imageNames": [image_name],
                "sourceLocation": upload["relativePath"],
                "dockerFilePath": "Dockerfile",
                "isPushEnabled": True,
                "noCache": False,
                "platform": {"os": "Linux", "architecture": "amd64"},
                "agentConfiguration": {"cpu": 2},
                "timeout": 1800,
            },
        )
        run_id = (run.get("properties") or {}).get("runId") or run.get("name")
        if not run_id:
            raise RuntimeError(f"ACR did not return run id for {service}: {run}")
        wait_for_acr_run(cfg, clients, run_id)
        images[service] = f"{login_server}/{image_name}"
    return images


def wait_for_acr_run(cfg: Config, clients: Clients, run_id: str) -> None:
    deadline = time.time() + 2400
    while time.time() < deadline:
        run = arm_request(
            cfg,
            clients,
            "GET",
            (
                f"/subscriptions/{cfg.subscription_id}/resourceGroups/{cfg.resource_group}"
                f"/providers/Microsoft.ContainerRegistry/registries/{cfg.acr_name}"
                f"/runs/{run_id}?api-version=2019-04-01"
            ),
        )
        status = (run.get("properties") or {}).get("status")
        if status == "Succeeded":
            return
        if status in {"Failed", "Canceled", "Error", "Timeout"}:
            raise RuntimeError(f"ACR run {run_id} ended with {status}: {run}")
        time.sleep(15)
    raise TimeoutError(f"Timed out waiting for ACR run {run_id}.")


def ensure_container_environment(cfg: Config, clients: Clients) -> str:
    env_id = resource_id(cfg, "Microsoft.App/managedEnvironments", cfg.container_env)
    try:
        clients.appcontainers.managed_environments.get(cfg.resource_group, cfg.container_env)
    except ResourceNotFoundError:
        clients.appcontainers.managed_environments.begin_create_or_update(
            cfg.resource_group,
            cfg.container_env,
            {
                "location": cfg.location,
                "properties": {
                    "appLogsConfiguration": {"destination": "none"},
                    "zoneRedundant": False,
                },
            },
        ).result()
    return env_id


def ensure_container_apps(cfg: Config, clients: Clients, images: dict[str, str]) -> dict[str, str]:
    env_id = ensure_container_environment(cfg, clients)
    acr = clients.registry.registries.get(cfg.resource_group, cfg.acr_name)
    creds = clients.registry.registries.list_credentials(cfg.resource_group, cfg.acr_name)
    registry_creds = {
        "secrets": [{"name": "acr-password", "value": creds.passwords[0].value}],
        "registries": [{"server": acr.login_server, "username": creds.username, "passwordSecretRef": "acr-password"}],
    }
    endpoints: dict[str, str] = {}
    for service, settings in SERVICES.items():
        app_name = f"{cfg.prefix}-{settings['app_suffix']}"
        port = settings["port"]
        clients.appcontainers.container_apps.begin_create_or_update(
            cfg.resource_group,
            app_name,
            {
                "location": cfg.location,
                "properties": {
                    "managedEnvironmentId": env_id,
                    "configuration": {
                        "activeRevisionsMode": "Single",
                        "ingress": {
                            "external": True,
                            "targetPort": port,
                            "allowInsecure": False,
                            "transport": "auto",
                        },
                        **registry_creds,
                    },
                    "template": {
                        "containers": [
                            {
                                "name": service,
                                "image": images[service],
                                "resources": {"cpu": 0.5, "memory": "1Gi"},
                            }
                        ],
                        "scale": {"minReplicas": 1, "maxReplicas": 3},
                    },
                },
            },
        ).result()
        app = clients.appcontainers.container_apps.get(cfg.resource_group, app_name)
        fqdn = app.configuration.ingress.fqdn
        if not fqdn:
            raise RuntimeError(f"Container app {app_name} has no ingress FQDN.")
        base_url = f"https://{fqdn}"
        wait_for_health(base_url)
        endpoints[service] = f"{base_url}/mcp"
    return endpoints


def create_toolbox(cfg: Config, clients: Clients, endpoints: dict[str, str]) -> dict[str, str]:
    toolbox_version = clients.projects.beta.toolboxes.create_version(
        name=cfg.toolbox_name,
        description="FSI demo toolbox bundling loans, investments, and current account MCP tools with tool search.",
        tools=[
            MCPTool(server_label="loans", server_url=endpoints["loans"], require_approval="never"),
            MCPTool(
                server_label="investments",
                server_url=endpoints["investments"],
                require_approval="never",
                tool_configs={
                    "get_portfolio_summary": ToolConfig(
                        additional_search_text="portfolio summary market value portfolio valuation total value customer portfolio"
                    )
                },
            ),
            MCPTool(
                server_label="accounts",
                server_url=endpoints["accounts"],
                require_approval="never",
                tool_configs={
                    "check_account_kyc_status": ToolConfig(
                        additional_search_text="current account KYC status compliance know your customer customer identity review"
                    ),
                    "get_account_balance": ToolConfig(
                        additional_search_text="current account balance available balance checking account cash account"
                    ),
                },
            ),
            ToolboxSearchPreviewTool(),
        ],
    )
    version = str(getattr(toolbox_version, "version", "1"))
    return {
        "toolbox_name": cfg.toolbox_name,
        "toolbox_version": version,
        "toolbox_endpoint": f"{cfg.project_endpoint}/toolboxes/{cfg.toolbox_name}/versions/{version}/mcp?api-version=v1",
        "toolbox_consumer_endpoint": f"{cfg.project_endpoint}/toolboxes/{cfg.toolbox_name}/mcp?api-version=v1",
    }


def write_outputs(cfg: Config, images: dict[str, str], endpoints: dict[str, str], toolbox: dict[str, str]) -> None:
    outputs = {
        "resource_group": cfg.resource_group,
        "location": cfg.location,
        "foundry_resource": cfg.foundry_resource,
        "foundry_project": cfg.project_name,
        "foundry_project_endpoint": cfg.project_endpoint,
        "model_deployment": cfg.model_deployment,
        "container_images": images,
        "mcp_endpoints": endpoints,
        **toolbox,
    }
    (ROOT / "infra" / "outputs.json").write_text(json.dumps(outputs, indent=2), encoding="utf-8")
    (ROOT / ".env.generated").write_text(
        "\n".join(
            [
                f"FOUNDRY_PROJECT_ENDPOINT={cfg.project_endpoint}",
                f"FOUNDRY_MODEL_DEPLOYMENT={cfg.model_deployment}",
                f"TOOLBOX_NAME={cfg.toolbox_name}",
                f"TOOLBOX_ENDPOINT={toolbox.get('toolbox_endpoint', '')}",
                f"MCP_LOANS_URL={endpoints.get('loans', '')}",
                f"MCP_INVESTMENTS_URL={endpoints.get('investments', '')}",
                f"MCP_ACCOUNTS_URL={endpoints.get('accounts', '')}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    console.print_json(json.dumps(outputs))


def parse_args() -> Config:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Provision Foundry toolbox search demo infrastructure.")
    parser.add_argument("--subscription-id", default=os.environ.get("AZURE_SUBSCRIPTION_ID"))
    parser.add_argument("--prefix", default=os.environ.get("DEMO_PREFIX", "fsi-toolbox-demo"))
    parser.add_argument("--location", default=os.environ.get("AZURE_LOCATION", "swedencentral"))
    parser.add_argument("--model-name", default=os.environ.get("FOUNDRY_MODEL_NAME", "gpt-5.4-mini"))
    parser.add_argument("--model-deployment", default=os.environ.get("FOUNDRY_MODEL_DEPLOYMENT", "gpt-5.4-mini"))
    parser.add_argument("--model-capacity", type=int, default=int(os.environ.get("FOUNDRY_MODEL_CAPACITY", "100")))
    parser.add_argument("--toolbox-name", default=os.environ.get("TOOLBOX_NAME", "fsi-toolbox"))
    parser.add_argument("--acr-name", default=os.environ.get("ACR_NAME"))
    parser.add_argument("--image-tag", default=os.environ.get("MCP_IMAGE_TAG"))
    args = parser.parse_args()
    if not args.subscription_id:
        raise ValueError("Set AZURE_SUBSCRIPTION_ID in .env or pass --subscription-id.")
    acr_name = args.acr_name or f"{''.join(ch for ch in args.prefix.lower() if ch.isalnum())}acr"
    if len(acr_name) < 5 or len(acr_name) > 50:
        raise ValueError("ACR name must be 5-50 alphanumeric characters.")
    return Config(
        subscription_id=args.subscription_id,
        prefix=args.prefix.lower(),
        location=args.location,
        model_name=args.model_name,
        model_deployment=args.model_deployment,
        model_capacity=args.model_capacity,
        toolbox_name=args.toolbox_name,
        acr_name=acr_name,
        image_tag=args.image_tag or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
    )


def main() -> None:
    cfg = parse_args()
    clients = build_clients(cfg)

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), TimeElapsedColumn(), console=console) as progress:
        task = progress.add_task("Creating resource group", total=None)
        ensure_resource_group(cfg, clients)
        progress.update(task, description="Creating Foundry resource and project")
        ensure_foundry(cfg, clients)
        progress.update(task, description="Deploying Foundry model")
        ensure_model_deployment(cfg, clients)

        progress.update(task, description="Building MCP images in Azure Container Registry")
        images = ensure_acr_and_images(cfg, clients)
        progress.update(task, description="Deploying Container Apps from ACR images")
        endpoints = ensure_container_apps(cfg, clients, images)
        progress.update(task, description="Creating Foundry toolbox with tool search")
        toolbox = create_toolbox(cfg, clients, endpoints)
        progress.update(task, description="Writing outputs")
        write_outputs(cfg, images, endpoints, toolbox)


if __name__ == "__main__":
    main()

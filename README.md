# Terraform Registry MCP Server

A Model Context Protocol (MCP) server that provides comprehensive access to the Terraform public registry. This server enables AI assistants to search and retrieve information about Terraform providers, modules, and documentation.

## Features

### Module Tools
- 🔍 **search_modules** - Search for Terraform modules by name or keywords
- 📦 **get_module_details** - Get detailed information about a specific module
- 🏷️ **get_latest_module_version** - Get the latest version of a module
- 📋 **list_module_versions** - List all available versions of a module

### Provider Tools
- 🔍 **search_providers** - Search for Terraform providers
- 📦 **get_provider_details** - Get detailed information about a provider
- 🏷️ **get_latest_provider_version** - Get the latest version of a provider
- 📋 **list_provider_versions** - List all available versions of a provider
- 📚 **get_provider_docs** - Fetch full provider documentation (setup, auth, version notes)
- 📄 **get_provider_resource_docs** - Fetch complete resource docs (args, attributes, examples)
- 📄 **get_provider_data_source_docs** - Fetch complete data source docs
- 🔎 **search_provider_docs** - Search within provider documentation for specific errors, topics, or troubleshooting

> **New!** Documentation tools now fetch the actual markdown content from the registry, including version-specific information, breaking changes, upgrade guides, and complete argument/attribute references.

## Installation

### Using Docker (Recommended)

Build and run with Docker Compose:

```bash
docker-compose up -d
```

Or build manually:

```bash
docker build -t terraform-registry-mcp-server .
docker run -d -p 3002:3002 --name terraform-registry-mcp-server \
  -e TRANSPORT_MODE=http \
  -e PORT=3002 \
  terraform-registry-mcp-server
```

### Local Development

Install dependencies:

```bash
pip install -e .
```

Run in stdio mode (for local MCP clients):

```bash
terraform-mcp-server
```

Run in HTTP mode:

```bash
export TRANSPORT_MODE=http
export PORT=3002
terraform-mcp-server
```

## Configuration

### Environment Variables

- `TRANSPORT_MODE` - Transport mode: `stdio` (default) or `http`
- `PORT` - HTTP server port (default: 3002)

### VS Code MCP Configuration

Add to your VS Code `mcp.json`:

```json
{
  "mcpServers": {
    "terraform": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "terraform-mcp-server"
      ]
    }
  }
}
```

Or for HTTP transport:

```json
{
  "mcpServers": {
    "terraform": {
      "url": "http://localhost:3002/mcp"
    }
  }
}
```

## Usage Examples

### Search for AWS VPC modules
```python
search_modules(query="vpc", provider="aws", limit=10)
```

### Get module details
```python
get_module_details(
    namespace="terraform-aws-modules",
    name="vpc",
    provider="aws"
)
```

### Search for providers
```python
search_providers(query="azure", tier="official")
```

### Get latest provider version
```python
get_latest_provider_version(namespace="hashicorp", name="aws")
```

### Get provider documentation
```python
# Get full provider overview with version info and breaking changes
get_provider_docs(namespace="hashicorp", name="azurerm")

# Get specific version documentation (useful for compatibility checks)
get_provider_docs(namespace="hashicorp", name="azurerm", version="3.0.0")
```

### Get specific resource documentation
```python
# Fetches complete documentation including all arguments and attributes
get_provider_resource_docs(
    namespace="hashicorp",
    name="aws",
    resource_name="aws_instance"
)

# Check a specific version's resource documentation
get_provider_resource_docs(
    namespace="hashicorp",
    name="azurerm",
    resource_name="azurerm_virtual_machine",
    version="3.85.0"
)
```

### Get data source documentation
```python
get_provider_data_source_docs(
    namespace="hashicorp",
    name="aws",
    data_source_name="aws_ami"
)
```

## Deployment to Azure Container Apps

This server is designed for easy deployment to Azure Container Apps:

1. Build and push to Azure Container Registry:
```bash
az acr build --registry <your-acr> --image terraform-mcp-server:latest .
```

2. Deploy to Container Apps:
```bash
az containerapp create \
  --name terraform-mcp-server \
  --resource-group <your-rg> \
  --environment <your-env> \
  --image <your-acr>.azurecr.io/terraform-mcp-server:latest \
  --target-port 3002 \
  --ingress external \
  --env-vars TRANSPORT_MODE=http PORT=3002
```

## Architecture

- **FastMCP** - Uses the official MCP Python SDK with FastMCP for simplified server creation
- **StreamableHTTP Transport** - Supports modern HTTP transport for cloud deployment
- **Public Registry Only** - Focuses on public Terraform registry (no authentication required)
- **Lightweight** - Minimal dependencies, fast startup

## Comparison with HashiCorp's Server

This is a simplified version compared to HashiCorp's official terraform-mcp-server:

**Included:**
- ✅ Public registry search (modules & providers)
- ✅ Module and provider details
- ✅ Version management
- ✅ HTTP transport for cloud deployment
- ✅ Docker support

**Not Included:**
- ❌ HCP Terraform / Terraform Enterprise integration
- ❌ Workspace management
- ❌ Run execution
- ❌ Variable management
- ❌ Private registry access

## License

MIT License

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

#!/usr/bin/env python3
"""
Terraform MCP Server

A simplified Model Context Protocol server for Terraform public registry.
Provides easy access to providers, modules, and policies from registry.terraform.io.

Uses FastMCP from the official MCP SDK for simplified server creation.
"""

import logging
import os
import re
from typing import Any

import requests
from mcp.server.fastmcp import FastMCP

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
REGISTRY_BASE_URL = "https://registry.terraform.io/v1"
REGISTRY_V2_BASE_URL = "https://registry.terraform.io/v2"
MODULES_SEARCH_URL = f"{REGISTRY_BASE_URL}/modules/search"
PROVIDERS_BASE_URL = f"{REGISTRY_BASE_URL}/providers"
REQUEST_TIMEOUT = 30

# Create FastMCP server instance
mcp = FastMCP("terraform-mcp")


# Helper functions

def _make_request(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make HTTP request to Terraform registry."""
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise ValueError(f"Resource not found: {url}")
        raise ValueError(f"Registry error (HTTP {e.response.status_code}): {str(e)}")
    except Exception as e:
        raise ValueError(f"Failed to fetch from registry: {str(e)}")


def _fetch_github_markdown(github_url: str) -> str:
    """
    Fetch raw markdown content from GitHub.
    
    Validates that URLs are from GitHub to prevent SSRF attacks.
    
    Args:
        github_url: GitHub web URL or tree URL
        
    Returns:
        Raw markdown content as string
        
    Raises:
        ValueError: If URL is not from GitHub or is invalid
    """
    import urllib.parse
    
    # Validate it's a GitHub URL
    if not github_url.startswith("https://github.com/"):
        raise ValueError("Only HTTPS GitHub URLs are allowed (https://github.com/...)")
    
    # Parse and validate URL structure
    try:
        parsed = urllib.parse.urlparse(github_url)
        if parsed.netloc != "github.com":
            raise ValueError("Only github.com URLs are allowed")
    except Exception as e:
        raise ValueError(f"Invalid URL format: {str(e)}")
    
    # Validate path doesn't contain suspicious patterns
    path = parsed.path
    if '\0' in path or '\n' in path:
        raise ValueError("URL contains prohibited characters")
    
    try:
        # Convert GitHub web URL to raw content URL
        # Example: https://github.com/hashicorp/terraform-provider-azurerm/tree/main/docs
        # To: https://raw.githubusercontent.com/hashicorp/terraform-provider-azurerm/main/docs
        raw_url = github_url.replace("github.com", "raw.githubusercontent.com").replace("/tree/", "/")
        
        # Validate the raw URL is still pointing to raw.githubusercontent.com
        parsed_raw = urllib.parse.urlparse(raw_url)
        if parsed_raw.netloc != "raw.githubusercontent.com":
            raise ValueError("URL conversion failed: invalid target")
        
        response = requests.get(raw_url, timeout=REQUEST_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Terraform-MCP-Server/1.0)"
        }, allow_redirects=False)  # Prevent SSRF via redirects
        response.raise_for_status()
        return response.text
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise ValueError(f"Documentation not found at: {raw_url}")
        raise ValueError(f"Failed to fetch documentation: HTTP {e.response.status_code}")
    except Exception as e:
        raise ValueError(f"Failed to fetch GitHub documentation: {str(e)}")


def _validate_provider_name(namespace: str, name: str) -> None:
    """
    Validate provider namespace and name to prevent injection attacks.
    
    Args:
        namespace: Provider namespace (e.g., 'hashicorp')
        name: Provider name (e.g., 'aws', 'azurerm')
        
    Raises:
        ValueError: If names contain invalid characters
    """
    import re
    
    # Allow lowercase, numbers, hyphens, underscores
    pattern = r'^[a-z0-9_-]+$'
    
    if not re.match(pattern, namespace):
        raise ValueError(f"Invalid namespace format: {namespace}")
    
    if not re.match(pattern, name):
        raise ValueError(f"Invalid provider name format: {name}")
    
    # Check for null bytes and newlines
    if '\0' in namespace or '\0' in name:
        raise ValueError("Provider names contain prohibited characters")
    
    if '\n' in namespace or '\n' in name:
        raise ValueError("Provider names contain prohibited characters")
    
    # Additional length checks to prevent resource exhaustion
    if len(namespace) > 100 or len(name) > 100:
        raise ValueError("Provider names are too long")


# FastMCP tool definitions

@mcp.tool()
def search_modules(query: str, provider: str = "", offset: int = 0, limit: int = 20) -> dict[str, Any]:
    """Search for Terraform modules in the public registry.
    
    Args:
        query: Search query string (module name or keywords)
        provider: Filter by provider (e.g., 'aws', 'azurerm', 'google')
        offset: Pagination offset (default: 0)
        limit: Maximum results to return (default: 20, max: 50)
    
    Returns:
        Dictionary containing search results with module names, providers, descriptions
    """
    # Validate inputs
    if not query or len(query.strip()) == 0:
        raise ValueError("Query cannot be empty")
    
    if len(query) > 255:
        raise ValueError("Query is too long (max 255 characters)")
    
    if provider:
        _validate_provider_name("hashicorp", provider)  # Reuse validation for provider
    
    params = {
        "q": query,
        "offset": max(0, offset),  # Ensure non-negative
        "limit": min(limit, 50),
    }
    
    if provider:
        params["provider"] = provider

    try:
        data = _make_request(MODULES_SEARCH_URL, params)
        modules = data.get("modules", [])
        
        results = []
        for module in modules:
            results.append({
                "id": module.get("id"),
                "namespace": module.get("namespace"),
                "name": module.get("name"),
                "provider": module.get("provider"),
                "description": module.get("description"),
                "version": module.get("version"),
                "downloads": module.get("downloads", 0),
                "verified": module.get("verified", False),
                "source": module.get("source"),
            })
        
        return {
            "query": query,
            "provider_filter": provider or "all",
            "total": len(results),
            "modules": results,
            "meta": data.get("meta", {}),
        }
    
    except Exception as e:
        logger.error(f"Module search error: {e}")
        raise


@mcp.tool()
def get_module_details(namespace: str, name: str, provider: str, version: str = "latest") -> dict[str, Any]:
    """Get detailed information about a specific Terraform module.
    
    Args:
        namespace: Module namespace/publisher (e.g., 'terraform-aws-modules')
        name: Module name (e.g., 'vpc')
        provider: Provider name (e.g., 'aws')
        version: Module version (default: 'latest')
    
    Returns:
        Dictionary containing detailed module information including inputs, outputs, resources
    """
    # Validate inputs
    _validate_provider_name(namespace, name)
    _validate_provider_name("hashicorp", provider)
    
    module_path = f"{namespace}/{name}/{provider}"
    
    if version == "latest":
        # Get latest version first
        url = f"{REGISTRY_BASE_URL}/modules/{module_path}"
        data = _make_request(url)
        version = data.get("version", "latest")
    
    # Get module details
    url = f"{REGISTRY_BASE_URL}/modules/{module_path}/{version}"
    data = _make_request(url)
    
    return {
        "id": data.get("id"),
        "namespace": data.get("namespace"),
        "name": data.get("name"),
        "provider": data.get("provider"),
        "version": data.get("version"),
        "description": data.get("description"),
        "source": data.get("source"),
        "published_at": data.get("published_at"),
        "downloads": data.get("downloads"),
        "verified": data.get("verified"),
        "root": {
            "inputs": data.get("root", {}).get("inputs", []),
            "outputs": data.get("root", {}).get("outputs", []),
            "dependencies": data.get("root", {}).get("dependencies", []),
            "resources": data.get("root", {}).get("resources", []),
        },
        "submodules": data.get("submodules", []),
        "providers": data.get("providers", []),
    }


@mcp.tool()
def get_latest_module_version(namespace: str, name: str, provider: str) -> dict[str, Any]:
    """Get the latest version of a Terraform module.
    
    Args:
        namespace: Module namespace/publisher
        name: Module name
        provider: Provider name
    
    Returns:
        Dictionary containing the latest version number and published date
    """
    module_path = f"{namespace}/{name}/{provider}"
    url = f"{REGISTRY_BASE_URL}/modules/{module_path}"
    
    data = _make_request(url)
    
    return {
        "namespace": namespace,
        "name": name,
        "provider": provider,
        "version": data.get("version"),
        "published_at": data.get("published_at"),
        "source": data.get("source"),
    }


@mcp.tool()
def list_module_versions(namespace: str, name: str, provider: str) -> dict[str, Any]:
    """List all available versions of a Terraform module.
    
    Args:
        namespace: Module namespace/publisher
        name: Module name
        provider: Provider name
    
    Returns:
        Dictionary containing all available versions
    """
    # Validate inputs
    _validate_provider_name(namespace, name)
    _validate_provider_name("hashicorp", provider)
    
    module_path = f"{namespace}/{name}/{provider}"
    url = f"{REGISTRY_BASE_URL}/modules/{module_path}/versions"
    
    data = _make_request(url)
    modules = data.get("modules", [])
    
    if not modules:
        return {
            "namespace": namespace,
            "name": name,
            "provider": provider,
            "versions": [],
        }
    
    module_data = modules[0]
    versions = []
    
    for version_info in module_data.get("versions", []):
        versions.append({
            "version": version_info.get("version"),
            "published_at": version_info.get("created_at"),
        })
    
    return {
        "namespace": namespace,
        "name": name,
        "provider": provider,
        "source": module_data.get("source"),
        "total_versions": len(versions),
        "versions": versions,
    }


@mcp.tool()
def search_providers(query: str = "", tier: str = "", offset: int = 0, limit: int = 20) -> dict[str, Any]:
    """Search for Terraform providers in the public registry.
    
    Args:
        query: Search query (provider name or keywords, optional)
        tier: Filter by tier ('official', 'partner', 'community', optional)
        offset: Pagination offset (default: 0)
        limit: Maximum results to return (default: 20, max: 100)
    
    Returns:
        Dictionary containing provider search results
    """
    # Validate inputs
    if query and len(query) > 255:
        raise ValueError("Query is too long (max 255 characters)")
    
    valid_tiers = {"official", "partner", "community"}
    if tier and tier not in valid_tiers:
        raise ValueError(f"Invalid tier. Must be one of: {', '.join(valid_tiers)}")
    
    # The registry API doesn't support search, so we list and filter
    fetch_limit = min(limit * 3, 100)  # Fetch more to allow for filtering
    url = f"{PROVIDERS_BASE_URL}"
    params: dict[str, Any] = {
        "offset": max(0, offset),
        "limit": fetch_limit,
    }
    
    data = _make_request(url, params)
    providers = data.get("providers", [])
    
    # Filter by query and tier locally
    filtered = []
    query_lower = query.lower() if query else ""
    
    for provider in providers:
        # Filter by tier if specified
        if tier and provider.get("tier") != tier:
            continue
        
        # Filter by query if specified (check name, namespace, description)
        if query_lower:
            name_match = query_lower in provider.get("name", "").lower()
            ns_match = query_lower in provider.get("namespace", "").lower()
            desc_match = query_lower in provider.get("description", "").lower()
            if not (name_match or ns_match or desc_match):
                continue
        
        filtered.append({
            "namespace": provider.get("namespace"),
            "name": provider.get("name"),
            "tier": provider.get("tier"),
            "description": provider.get("description"),
            "version": provider.get("version"),
            "downloads": provider.get("downloads", 0),
            "source": provider.get("source"),
        })
        
        # Stop if we have enough results
        if len(filtered) >= limit:
            break
    
    return {
        "query": query or "all",
        "tier_filter": tier or "all",
        "total": len(filtered),
        "providers": filtered,
    }


@mcp.tool()
def get_provider_details(namespace: str, name: str, version: str = "latest") -> dict[str, Any]:
    """Get detailed information about a specific Terraform provider.
    
    Args:
        namespace: Provider namespace (e.g., 'hashicorp')
        name: Provider name (e.g., 'aws', 'azurerm', 'google')
        version: Provider version (default: 'latest')
    
    Returns:
        Dictionary containing detailed provider information
    """
    # Validate inputs
    _validate_provider_name(namespace, name)
    
    if version == "latest":
        # Get latest version first
        url = f"{PROVIDERS_BASE_URL}/{namespace}/{name}"
        data = _make_request(url)
        version = data.get("version", "latest")
    
    # Get provider details
    url = f"{PROVIDERS_BASE_URL}/{namespace}/{name}/{version}"
    data = _make_request(url)
    
    return {
        "namespace": data.get("namespace"),
        "name": data.get("name"),
        "version": data.get("version"),
        "tier": data.get("tier"),
        "description": data.get("description"),
        "source": data.get("source"),
        "published_at": data.get("published_at"),
        "downloads": data.get("downloads"),
        "platforms": data.get("platforms", []),
        "docs": {
            "url": f"https://registry.terraform.io/providers/{namespace}/{name}/{version}/docs",
        },
    }


@mcp.tool()
def get_latest_provider_version(namespace: str, name: str) -> dict[str, Any]:
    """Get the latest version of a Terraform provider.
    
    Args:
        namespace: Provider namespace (e.g., 'hashicorp')
        name: Provider name (e.g., 'aws')
    
    Returns:
        Dictionary containing the latest version number and metadata
    """
    url = f"{PROVIDERS_BASE_URL}/{namespace}/{name}"
    data = _make_request(url)
    
    return {
        "namespace": namespace,
        "name": name,
        "version": data.get("version"),
        "tier": data.get("tier"),
        "published_at": data.get("published_at"),
        "source": data.get("source"),
        "downloads": data.get("downloads"),
    }


@mcp.tool()
def list_provider_versions(namespace: str, name: str) -> dict[str, Any]:
    """List all available versions of a Terraform provider.
    
    Args:
        namespace: Provider namespace
        name: Provider name
    
    Returns:
        Dictionary containing all available versions
    """
    url = f"{PROVIDERS_BASE_URL}/{namespace}/{name}/versions"
    data = _make_request(url)
    
    versions = []
    for version_info in data.get("versions", []):
        versions.append({
            "version": version_info.get("version"),
            "protocols": version_info.get("protocols", []),
            "platforms": version_info.get("platforms", []),
        })
    
    return {
        "namespace": namespace,
        "name": name,
        "total_versions": len(versions),
        "versions": versions,
    }


@mcp.tool()
def get_provider_docs(namespace: str, name: str, version: str = "latest") -> dict[str, Any]:
    """Get the main documentation page for a Terraform provider.
    
    This fetches the provider's overview documentation from GitHub which typically includes:
    - Version information and compatibility notes
    - Authentication and configuration
    - Example usage
    - Important notes about breaking changes
    - Upgrade guides between versions
    
    Args:
        namespace: Provider namespace (e.g., 'hashicorp')
        name: Provider name (e.g., 'aws', 'azurerm', 'google')
        version: Provider version (default: 'latest')
    
    Returns:
        Dictionary containing provider documentation content in markdown format
    """
    if version == "latest":
        # Get latest version first
        url = f"{PROVIDERS_BASE_URL}/{namespace}/{name}"
        data = _make_request(url)
        version = data.get("version", "latest")
        source_url = data.get("source", "")
    else:
        # Get specific version info
        url = f"{PROVIDERS_BASE_URL}/{namespace}/{name}/{version}"
        data = _make_request(url)
        source_url = data.get("source", "")
    
    # Construct documentation URLs
    docs_url = f"https://registry.terraform.io/providers/{namespace}/{name}/{version}/docs"
    
    # Try to fetch from GitHub if available
    if "github.com" in source_url:
        github_docs_url = f"{source_url}/tree/main/docs/index.md"
        
        try:
            markdown_content = _fetch_github_markdown(github_docs_url)
            
            return {
                "namespace": namespace,
                "name": name,
                "version": version,
                "docs_url": docs_url,
                "github_docs": github_docs_url,
                "source": source_url,
                "content": markdown_content,
                "note": "Documentation fetched from GitHub repository",
            }
        except Exception as e:
            # Try alternative paths if index.md doesn't exist
            alternative_paths = [
                f"{source_url}/tree/main/docs/README.md",
                f"{source_url}/tree/main/README.md",
                f"{source_url}/tree/main/website/docs/index.html.markdown",
            ]
            
            for alt_path in alternative_paths:
                try:
                    markdown_content = _fetch_github_markdown(alt_path)
                    return {
                        "namespace": namespace,
                        "name": name,
                        "version": version,
                        "docs_url": docs_url,
                        "github_docs": alt_path,
                        "source": source_url,
                        "content": markdown_content,
                        "note": "Documentation fetched from GitHub repository",
                    }
                except:
                    continue
    
    # Fallback if GitHub fetch fails
    return {
        "namespace": namespace,
        "name": name,
        "version": version,
        "docs_url": docs_url,
        "github_docs": f"{source_url}/tree/main/docs" if "github.com" in source_url else None,
        "source": source_url,
        "error": "Could not fetch documentation from GitHub. Visit docs_url to view in browser.",
        "note": "Visit docs_url for full provider documentation including setup, authentication, and version-specific notes.",
    }


@mcp.tool()
def get_provider_resource_docs(namespace: str, name: str, resource_name: str, version: str = "latest") -> dict[str, Any]:
    """Get detailed documentation for a specific provider resource.
    
    Fetches the full documentation from GitHub including:
    - Description and use cases
    - Example usage code
    - Argument reference (required and optional)
    - Attribute reference (exported values)
    - Import instructions
    - Timeouts configuration
    
    Args:
        namespace: Provider namespace (e.g., 'hashicorp')
        name: Provider name (e.g., 'aws')
        resource_name: Resource name (e.g., 'aws_instance', 'azurerm_virtual_machine')
        version: Provider version (default: 'latest')
    
    Returns:
        Dictionary containing detailed resource documentation in markdown format
    """
    if version == "latest":
        url = f"{PROVIDERS_BASE_URL}/{namespace}/{name}"
        data = _make_request(url)
        version = data.get("version", "latest")
        source_url = data.get("source", "")
    else:
        url = f"{PROVIDERS_BASE_URL}/{namespace}/{name}/{version}"
        data = _make_request(url)
        source_url = data.get("source", "")
    
    # Remove provider prefix from resource name if present
    clean_resource_name = resource_name.replace(f"{name}_", "", 1)
    
    # Construct documentation URLs
    docs_url = f"https://registry.terraform.io/providers/{namespace}/{name}/{version}/docs/resources/{clean_resource_name}"
    
    # Try to fetch from GitHub
    if "github.com" in source_url:
        # Try different possible paths
        possible_paths = [
            f"{source_url}/tree/main/docs/resources/{clean_resource_name}.md",
            f"{source_url}/tree/main/docs/resources/{clean_resource_name}.markdown",
            f"{source_url}/tree/main/website/docs/r/{clean_resource_name}.html.markdown",
            f"{source_url}/tree/main/website/docs/r/{clean_resource_name}.markdown",
        ]
        
        for github_path in possible_paths:
            try:
                markdown_content = _fetch_github_markdown(github_path)
                return {
                    "namespace": namespace,
                    "name": name,
                    "version": version,
                    "resource": resource_name,
                    "docs_url": docs_url,
                    "github_docs": github_path,
                    "source": source_url,
                    "content": markdown_content,
                    "note": "Full resource documentation fetched from GitHub",
                }
            except:
                continue
    
    # Fallback if GitHub fetch fails
    github_docs = f"{source_url}/tree/main/docs/resources/{clean_resource_name}.md" if "github.com" in source_url else None
    return {
        "namespace": namespace,
        "name": name,
        "version": version,
        "resource": resource_name,
        "docs_url": docs_url,
        "github_docs": github_docs,
        "source": source_url,
        "error": "Could not fetch documentation from GitHub. Visit docs_url to view in browser.",
        "note": "Visit docs_url for full resource documentation including all arguments, attributes, and examples.",
    }


@mcp.tool()
def get_provider_data_source_docs(namespace: str, name: str, data_source_name: str, version: str = "latest") -> dict[str, Any]:
    """Get detailed documentation for a specific provider data source.
    
    Fetches the full documentation from GitHub including:
    - Description and use cases
    - Example usage code
    - Argument reference
    - Attribute reference (exported values)
    
    Args:
        namespace: Provider namespace (e.g., 'hashicorp')
        name: Provider name (e.g., 'aws')
        data_source_name: Data source name (e.g., 'aws_ami', 'azurerm_subscription')
        version: Provider version (default: 'latest')
    
    Returns:
        Dictionary containing detailed data source documentation in markdown format
    """
    if version == "latest":
        url = f"{PROVIDERS_BASE_URL}/{namespace}/{name}"
        data = _make_request(url)
        version = data.get("version", "latest")
        source_url = data.get("source", "")
    else:
        url = f"{PROVIDERS_BASE_URL}/{namespace}/{name}/{version}"
        data = _make_request(url)
        source_url = data.get("source", "")
    
    # Remove provider prefix from data source name if present
    clean_ds_name = data_source_name.replace(f"{name}_", "", 1)
    
    # Construct documentation URLs
    docs_url = f"https://registry.terraform.io/providers/{namespace}/{name}/{version}/docs/data-sources/{clean_ds_name}"
    
    # Try to fetch from GitHub
    if "github.com" in source_url:
        # Try different possible paths
        possible_paths = [
            f"{source_url}/tree/main/docs/data-sources/{clean_ds_name}.md",
            f"{source_url}/tree/main/docs/data-sources/{clean_ds_name}.markdown",
            f"{source_url}/tree/main/website/docs/d/{clean_ds_name}.html.markdown",
            f"{source_url}/tree/main/website/docs/d/{clean_ds_name}.markdown",
        ]
        
        for github_path in possible_paths:
            try:
                markdown_content = _fetch_github_markdown(github_path)
                return {
                    "namespace": namespace,
                    "name": name,
                    "version": version,
                    "data_source": data_source_name,
                    "docs_url": docs_url,
                    "github_docs": github_path,
                    "source": source_url,
                    "content": markdown_content,
                    "note": "Full data source documentation fetched from GitHub",
                }
            except:
                continue
    
    # Fallback if GitHub fetch fails
    github_docs = f"{source_url}/tree/main/docs/data-sources/{clean_ds_name}.md" if "github.com" in source_url else None
    return {
        "namespace": namespace,
        "name": name,
        "version": version,
        "data_source": data_source_name,
        "docs_url": docs_url,
        "github_docs": github_docs,
        "source": source_url,
        "error": "Could not fetch documentation from GitHub. Visit docs_url to view in browser.",
        "note": "Visit docs_url for full data source documentation including arguments and attributes.",
    }


@mcp.tool()
def search_provider_docs(
    namespace: str,
    name: str,
    query: str,
    version: str = "latest"
) -> dict:
    """
    Search within provider documentation for specific errors, topics, or troubleshooting info.
    
    Useful for questions like:
    - "What does error X mean?"
    - "How do I configure authentication?"
    - "What are the timeout options?"
    - "How do I handle rate limiting?"
    
    Args:
        namespace: Provider namespace (e.g., 'hashicorp')
        name: Provider name (e.g., 'aws', 'azurerm')
        query: Search terms or error message to look for
        version: Provider version (default: 'latest')
    
    Returns:
        Dictionary containing search results with matched sections from documentation
    """
    import re
    
    # Get the main provider documentation
    provider_docs = get_provider_docs(namespace, name, version)
    
    if "error" in provider_docs:
        return provider_docs
    
    results = []
    content = provider_docs.get("content", "")
    
    # Split content into sections (by headers)
    sections = re.split(r'\n(#{1,6}[^\n]+)\n', content)
    
    # Search case-insensitively
    query_lower = query.lower()
    
    current_header = "Overview"
    for i, section in enumerate(sections):
        if section.startswith('#'):
            current_header = section.strip('# ')
        elif query_lower in section.lower():
            # Extract context around the match (up to 500 chars)
            matches = []
            section_lower = section.lower()
            start = 0
            while True:
                pos = section_lower.find(query_lower, start)
                if pos == -1:
                    break
                
                # Get context (250 chars before and after)
                context_start = max(0, pos - 250)
                context_end = min(len(section), pos + len(query) + 250)
                context = section[context_start:context_end].strip()
                
                matches.append({
                    "position": pos,
                    "context": context
                })
                start = pos + 1
            
            if matches:
                results.append({
                    "section": current_header,
                    "matches": len(matches),
                    "excerpts": [m["context"] for m in matches[:3]]  # Limit to 3 excerpts per section
                })
    
    return {
        "namespace": namespace,
        "name": name,
        "version": provider_docs.get("version"),
        "query": query,
        "total_matches": sum(r["matches"] for r in results),
        "sections_found": len(results),
        "results": results,
        "docs_url": provider_docs.get("docs_url"),
        "tip": "For full context, use get_provider_docs, get_provider_resource_docs, or get_provider_data_source_docs"
    }


def main() -> None:
    """Main entry point."""
    import signal

    def signal_handler(sig: int, frame: Any) -> None:
        logger.info("Received signal, shutting down...")
        os._exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    transport_mode = os.getenv("TRANSPORT_MODE", "stdio").lower()

    try:
        logger.info(f"Starting Terraform MCP server in {transport_mode} mode")
        
        if transport_mode == "http":
            port = int(os.getenv("PORT", "3002"))
            mcp.settings.host = "0.0.0.0"
            mcp.settings.port = port
            mcp.run(transport="streamable-http")
        else:
            mcp.run(transport="stdio")

    except Exception as e:
        logger.error(f"Server error: {e}")
        raise


if __name__ == "__main__":
    main()

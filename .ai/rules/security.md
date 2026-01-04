# Security Rules

## Secret Management

### What Goes Where

| Type | Storage | Examples |
|------|---------|----------|
| **Sensitive credentials** | GCP Secret Manager | PATs, API keys, passwords, tokens |
| **Configuration values** | Environment variables | Project IDs, regions, endpoints, model names, bucket names |

### Secret Manager (Production/CI)
- Store all passwords and authentication tokens in GCP Secret Manager
- Reference secrets in Cloud Functions deployment with `--set-secrets`
- Grant minimal IAM permissions (`roles/secretmanager.secretAccessor`)

### Environment Variables (Local Dev)
- Use `.env` files for local development (via `python-dotenv`)
- Load with `load_dotenv()` at startup
- Validate required variables exist before proceeding

### Code Practices

**NEVER:**
- Print or log secrets/tokens (even partially)
- Commit `.env` files (ensure in `.gitignore`)
- Hardcode credentials in source code
- Create example files with realistic-looking secrets
- Include secrets in error messages

**ALWAYS:**
- Use `os.getenv()` for all sensitive values
- Add sensitive files to `.gitignore`
- Warn about security implications when relevant
- Mask secrets in logs (show only last 4 chars if needed)

### Example

```python
import os
from dotenv import load_dotenv

load_dotenv()  # Load .env for local dev

# Validate required secrets exist
pat = os.environ.get("AZURE_DEVOPS_PAT")
if not pat:
    raise ValueError("Missing required secret: AZURE_DEVOPS_PAT")

# Config values are fine in env vars
project = os.environ.get("VERTEX_PROJECT", "default-project")
region = os.environ.get("VERTEX_LOCATION", "us-central1")
```

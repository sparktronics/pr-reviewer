# Claude Code Rules

## Python Guidelines

### Code Style
- Follow PEP 8 conventions
- Use type hints for function signatures and class attributes
- Prefer f-strings over `.format()` or `%` formatting
- Use meaningful variable names; avoid single letters except for loops/lambdas
- Keep functions focused and under 50 lines when possible

## VERY IMPORTANT Coding Guidelines
- Do not repeat code. Simplify in functions.
- Apply simple responsibility principle 


### Imports
- Group imports: stdlib, third-party, local (separated by blank lines)
- Use absolute imports over relative imports
- Avoid `from module import *`

### Error Handling
- Catch specific exceptions, not bare `except:`
- Use `logging` module instead of `print()` for production code
- Validate inputs early, fail fast with clear error messages
- Use `sys.exit(1)` for fatal errors in CLI scripts

### Type Hints
```python
def process_data(items: list[str], limit: int = 10) -> dict[str, int]:
    ...
```

### Docstrings
- Use Google-style docstrings for functions and classes
- Document parameters, return values, and exceptions raised

```python
def fetch_data(url: str, timeout: int = 30) -> dict:
    """Fetch JSON data from a URL.
    
    Args:
        url: The endpoint URL to fetch from.
        timeout: Request timeout in seconds.
    
    Returns:
        Parsed JSON response as a dictionary.
    
    Raises:
        requests.RequestException: If the request fails.
    """
```

## Google Cloud Platform Guidelines

### Authentication
- Use Application Default Credentials (ADC) when possible
- Never hardcode service account keys
- Use Workload Identity Federation for CI/CD pipelines
- Store secrets in Secret Manager, not environment variables

### Cloud Functions
- Keep function code focused and stateless
- Use structured logging with `google-cloud-logging`
- Set appropriate memory and timeout limits
- Use environment variables for configuration
- Implement proper error handling and return appropriate HTTP status codes

```python
import functions_framework
from google.cloud import logging

@functions_framework.http
def my_function(request):
    """HTTP Cloud Function."""
    try:
        # Function logic here
        return {"status": "success"}, 200
    except Exception as e:
        logging.error(f"Error: {e}")
        return {"error": str(e)}, 500
```

### IAM & Security
- Follow principle of least privilege
- Use predefined roles when possible
- Document required IAM permissions in code comments
- Never log sensitive data (tokens, keys, PII)

### Vertex AI / GenAI
- Use the `google-genai` SDK for Gemini models
- Implement retry logic with exponential backoff
- Set appropriate safety settings for your use case
- Handle rate limits gracefully

```python
from google import genai
from google.genai import types

client = genai.Client(vertexai=True, project="my-project", location="us-central1")

response = client.models.generate_content(
    model="gemini-2.0-flash-001",
    contents="Your prompt here",
    config=types.GenerateContentConfig(
        temperature=0.7,
        max_output_tokens=1024,
    ),
)
```

### Resource Naming
- Use lowercase with hyphens for resource names
- Include environment prefix (dev-, staging-, prod-)
- Be descriptive but concise

### Logging
- Use structured logging (JSON format)
- Include correlation IDs for request tracing
- Log at appropriate levels (DEBUG, INFO, WARNING, ERROR)

## Project-Specific Rules

### Environment Variables
- Load from `.env` files using `python-dotenv`
- Validate required variables at startup
- Document all required variables in code

### Dependencies
- Pin versions in `requirements.txt`
- Prefer well-maintained, popular packages
- Use stdlib when sufficient

### Security
- Keep secrets in `.env` (gitignored)
- Use `os.getenv()` for all sensitive values
- Never commit real credentials


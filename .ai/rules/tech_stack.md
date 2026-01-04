# Tech Stack Rules

## Project Stack

- **Python:** 3.12+ (Cloud Functions runtime)
- **AI/ML:** Google GenAI SDK (`google-genai`) for Vertex AI / Gemini
- **Cloud:** GCP Cloud Functions (Gen2), Cloud Storage, Pub Sub
- **External API:** Azure DevOps REST API
- **Environment:** `python-dotenv` for local development

## Google Cloud Platform

### Authentication
- Use Application Default Credentials (ADC) when possible
- Never hardcode service account keys
- Use Workload Identity Federation for CI/CD pipelines

### Cloud Functions
- Keep function code focused and stateless
- Use structured logging with `google-cloud-logging`
- Set appropriate memory and timeout limits
- Use environment variables for non-sensitive configuration
- Implement proper error handling and return appropriate HTTP status codes

```python
import functions_framework
import logging

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

### Vertex AI / GenAI
- Use the `google-genai` SDK for Gemini models
- Implement retry logic with exponential backoff for production
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
- Include environment prefix when applicable (dev-, staging-, prod-)
- Be descriptive but concise

### Logging
- Use structured logging (JSON format) in production
- Include correlation IDs for request tracing
- Log at appropriate levels (DEBUG, INFO, WARNING, ERROR)
- Log calls made to third-party APIs so that parameters and timings for the calls are recorded and help in troubleshooting

## Azure DevOps

- Use REST API v7.1-preview
- Authenticate with Personal Access Token (PAT)
- Required PAT permissions:
  - Code (Read)
  - Pull Request Threads (Read & Write)
  - Pull Request (Read & Write)

## Dependencies

### Adding New Dependencies
1. Add to `requirements.txt` with pinned version
2. Install with `pip3 install -r requirements.txt`
3. Mention addition to the user
4. Update relevant documentation if needed

### Preferences
- Prefer standard library when sufficient
- Use well-maintained, popular packages
- Reuse packages already in use (requests, dotenv, google-genai)

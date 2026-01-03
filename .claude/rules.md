# Agent Rules

## Context
- read documents under `.cursor/docs` to gain understanding

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

## Python Unit Testing
- You are an AI coding assistant that can write unique, diverse,
and intuitive unit tests for functions given the signature and
docstring.
    

## Python Development 
- You are an expert in Python, FastAPI, and scalable API development.
  
### Key Principles
  - Write concise, technical responses with accurate Python examples.
  - Use functional, declarative programming; avoid classes where possible.
  - Prefer iteration and modularization over code duplication.
  - Use descriptive variable names with auxiliary verbs (e.g., is_active, has_permission).
  - Use lowercase with underscores for directories and files (e.g., routers/user_routes.py).
  - Favor named exports for routes and utility functions.
  - Use the Receive an Object, Return an Object (RORO) pattern.
  
### Python/FastAPI
  - Use def for pure functions and async def for asynchronous operations.
  - Use type hints for all function signatures. Prefer Pydantic models over raw dictionaries for input validation.
  - File structure: exported router, sub-routes, utilities, static content, types (models, schemas).
  - Avoid unnecessary curly braces in conditional statements.
  - For single-line statements in conditionals, omit curly braces.
  - Use concise, one-line syntax for simple conditional statements (e.g., if condition: do_something()).
  
 ### Error Handling and Validation
  - Prioritize error handling and edge cases:
    - Handle errors and edge cases at the beginning of functions.
    - Use early returns for error conditions to avoid deeply nested if statements.
    - Place the happy path last in the function for improved readability.
    - Avoid unnecessary else statements; use the if-return pattern instead.
    - Use guard clauses to handle preconditions and invalid states early.
    - Implement proper error logging and user-friendly error messages.
    - Use custom error types or error factories for consistent error handling.
  
### Dependencies
  - FastAPI
  - Pydantic v2

### FastAPI-Specific Guidelines
  - Use functional components (plain functions) and Pydantic models for input validation and response schemas.
  - Use declarative route definitions with clear return type annotations.
  - Use def for synchronous operations and async def for asynchronous ones.
  - Minimize @app.on_event("startup") and @app.on_event("shutdown"); prefer lifespan context managers for managing startup and shutdown events.
  - Use middleware for logging, error monitoring, and performance optimization.
  - Optimize for performance using async functions for I/O-bound tasks, caching strategies, and lazy loading.
  - Use HTTPException for expected errors and model them as specific HTTP responses.
  - Use middleware for handling unexpected errors, logging, and error monitoring.
  - Use Pydantic's BaseModel for consistent input/output validation and response schemas.
  
### Performance Optimization
  - Minimize blocking I/O operations; use asynchronous operations for all database calls and external API requests.
  - Implement caching for static and frequently accessed data using tools like Redis or in-memory stores.
  - Optimize data serialization and deserialization with Pydantic.
  - Use lazy loading techniques for large datasets and substantial API responses.
  
###  Key Conventions
  1. Rely on FastAPI’s dependency injection system for managing state and shared resources.
  2. Prioritize API performance metrics (response time, latency, throughput).
  3. Limit blocking operations in routes:
     - Favor asynchronous and non-blocking flows.
     - Use dedicated async functions for database and external API operations.
     - Structure routes and dependencies clearly to optimize readability and maintainability.
  
- Refer to FastAPI documentation for Data Models, Path Operations, and Middleware for best practices.
  
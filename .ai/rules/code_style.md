# Code Style Rules

## Python Conventions

### General
- Follow PEP 8 conventions, prioritizing readability
- Use type hints for function signatures and class attributes
- Prefer f-strings over `.format()` or `%` formatting
- Use meaningful variable names; avoid single letters except for loops/lambdas
- Keep functions focused; aim for under 50 lines when practical

### Naming
- Use `snake_case` for functions, variables, modules
- Use `PascalCase` for classes
- Use `UPPER_SNAKE_CASE` for constants
- Use descriptive names with auxiliary verbs (e.g., `is_active`, `has_permission`)

### Imports
- Group imports: stdlib, third-party, local (separated by blank lines)
- Use absolute imports over relative imports
- Avoid `from module import *`

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

### Error Handling
- Catch specific exceptions, not bare `except:`
- Use `logging` module for production code
- Validate inputs early, fail fast with clear error messages
- Use `sys.exit(1)` for fatal errors in CLI scripts
- Use early returns for error conditions to avoid deep nesting

### Code Organization
- Do not repeat code; simplify into functions (DRY principle)
- Apply single responsibility principle
- Prefer iteration and modularization over code duplication

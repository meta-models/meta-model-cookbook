# Minimal System Requirements and Run Instructions

A quick-start guide for developers setting up the Meta Model API cookbook locally.

## Supported Operating Systems

- **Windows** (10/11 with WSL2 recommended for Linux-based recipes)
- **macOS** (11+, Intel and Apple Silicon)
- **Linux** (Ubuntu 20.04+, Debian 11+, or equivalent)

## Prerequisites

This cookbook contains multiple recipe types (Python, JavaScript, Swift) organized by section. Most recipes are **Python-based** and self-contained. Start with the Python setup below unless you're targeting a specific recipe (see [Language-Specific Setup](#language-specific-setup)).

### Core Requirements (For Python Recipes)

| Software | Minimum Version | Check Version | Install |
|----------|-----------------|-------------------|---------|
| **Python** | 3.10 | `python --version` | [python.org](https://www.python.org/downloads/) or `brew install python@3.10` (macOS) |
| **pip** | 24.0 | `pip --version` | Usually bundled with Python; upgrade with `pip install --upgrade pip` |
| **git** | 2.20+ | `git --version` | [git-scm.com](https://git-scm.com/downloads) |

### API Access

All recipes require a **Meta Model API account and API key**:

1. Create an account at [dev.meta.ai](https://dev.meta.ai/)
2. Generate an API key from your account dashboard
3. Store the key as an environment variable (keep it out of source code):

**Linux / macOS:**
```bash
export MODEL_API_KEY="LLM|{numeric_id}|{secret}"
```

**Windows (PowerShell):**
```powershell
$env:MODEL_API_KEY="LLM|{numeric_id}|{secret}"
```

## Quick Start (Python)

### 1. Clone the Repository

```bash
git clone https://github.com/meta-models/meta-model-cookbook.git
cd meta-model-cookbook
```

### 2. Set Up a Virtual Environment

Using `venv` (recommended):

```bash
python -m venv venv
# Activate (Linux/macOS):
source venv/bin/activate
# Activate (Windows):
venv\Scripts\activate
```

Or using `conda`:

```bash
conda create -n cookbook python=3.10
conda activate cookbook
```

### 3. Install Python Dependencies

Most recipes are self-contained with their own `requirements.txt` or `pyproject.toml`. Install globally for quick exploration:

```bash
pip install openai pytest pydantic
```

Or install all extras (recommended for full access to all recipes):

```bash
pip install openai pytest pydantic pygame pandas pillow requests
```

To install dependencies for a specific recipe:

```bash
cd 03_use_cases/04_doc_generation
pip install -r requirements.txt
```

## Running Recipes

### Python Notebooks (Jupyter)

Install Jupyter (if not already installed):

```bash
pip install jupyter
```

Start the Jupyter server:

```bash
jupyter notebook
```

Navigate to a recipe like `01_api_fundamentals/01_chat_completions.ipynb`, open it, and run cells in order.

### Python Scripts

Most recipes include standalone `.py` scripts. Run directly:

```bash
# Simple chat example:
python 01_api_fundamentals/01_chat_completions.py

# Recipe with dependencies:
cd 03_use_cases/10_perception_grounding
python perception_grounding.py --image https://example.com/image.jpg
```

### Python Projects with Tests

Some recipes are full projects with test suites:

```bash
cd 02_agent_patterns/01_agent_loop_basics/agent-loop-target
pytest                          # Run all tests
pytest tests/test_grades.py     # Run a specific test
pytest -v                       # Verbose output
```

### JavaScript Recipes

For recipes with `package.json` (e.g., `02_agent_patterns/03_managing_context/proxy_build/`):

```bash
cd 02_agent_patterns/03_managing_context/proxy_build
npm install
npm run build   # or check package.json for available scripts
```

### Swift/macOS Recipes

The `13_macos_cua` (macOS computer-use agent) requires Swift and macOS:

```bash
cd 03_use_cases/13_macos_cua
make build          # Build debug binary
make run --help     # See available commands
make check          # Lint, build, and test
```

See `03_use_cases/13_macos_cua/Makefile` for all available targets.

## Environment Variables

Set these before running recipes:

| Variable | Purpose | Default | Example |
|----------|---------|---------|---------|
| `MODEL_API_KEY` | API authentication | **Required** | `LLM\|12345\|secret_key` |
| `MUSE_MODEL` | Model to use | `muse-spark-1.1` | `muse-spark-1.1` |
| `OPENAI_API_BASE` | Model API endpoint | `https://api.meta.ai/v1` | (usually not needed) |

## Troubleshooting

### Python: "ModuleNotFoundError: No module named 'openai'"

**Solution:** Install the OpenAI SDK:
```bash
pip install openai
```

### Python: "No module named 'pytest'"

**Solution:** Install pytest for the recipe's test suite:
```bash
pip install pytest
```

### "MODEL_API_KEY not found" or API authentication fails

**Solution:** Ensure the environment variable is set and contains a valid token:
```bash
# Check it's set:
echo $MODEL_API_KEY          # Linux/macOS
echo %MODEL_API_KEY%          # Windows cmd
Write-Output $env:MODEL_API_KEY  # Windows PowerShell
```

### Port conflicts (for recipes running local servers)

If a recipe starts a web server and complains "Address already in use":

1. Find the process using the port (e.g., port 8000):
   ```bash
   # macOS/Linux:
   lsof -i :8000
   # Windows:
   netstat -ano | findstr :8000
   ```

2. Kill the process or use a different port (check recipe docs for `--port` flag).

### Jupyter "Permission denied" on Linux

```bash
chmod +x venv/bin/jupyter
```

### Git clone fails with "fatal: could not read Username..."

Ensure you have git credentials configured or use an SSH key:
```bash
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```

## Project Structure

```
meta-model-cookbook/
├── 01_api_fundamentals/        # API primitives (notebooks & scripts)
├── 02_agent_patterns/          # Agent loop recipes (agent, reasoning, context mgmt)
├── 03_use_cases/               # End-to-end patterns (charts, games, browser, etc.)
├── 04_muse_code/               # Muse Code agent recipes
├── docs/                       # Documentation (this file)
├── README.md                   # Main overview
└── LICENSE                     # License info
```

Each recipe folder contains:
- **README.md**: Recipe description and goals
- **\*.ipynb** or **\*.py**: Runnable code (notebooks or scripts)
- **requirements.txt** or **pyproject.toml**: Dependencies (if not using global install)
- **tests/**: Test suite (if applicable)

## Quick Reference: Common Commands

```bash
# Activate virtual environment
source venv/bin/activate          # Linux/macOS
venv\Scripts\activate              # Windows

# Install and upgrade tools
pip install --upgrade pip
pip install openai pytest

# Run a Python script
python script.py

# Run tests
pytest                             # All tests
pytest -k pattern                  # Tests matching pattern

# Start Jupyter notebook
jupyter notebook

# Check environment variable
echo $MODEL_API_KEY               # Linux/macOS
$env:MODEL_API_KEY                # Windows PowerShell

# Build Swift project
make build                         # In 03_use_cases/13_macos_cua/
```

## Next Steps

1. **Read the main [README.md](../README.md)** for a curated list of recipes by topic.
2. **Pick a recipe** that matches your interest (API fundamentals, agents, use cases, etc.).
3. **Follow the recipe's README** for any additional setup or options.
4. **Run tests or notebooks** to verify your environment is working.

## Getting Help

- **Recipe-specific issues:** See the recipe's `README.md` for troubleshooting and context.
- **API issues:** Check [dev.meta.ai](https://dev.meta.ai/) docs and your API key status.
- **Python/tool issues:** Consult the tool's official documentation (Python.org, Jupyter docs, etc.).
- **Project issues:** File an issue on the [GitHub repository](https://github.com/meta-models/meta-model-cookbook).

## Additional Resources

- [Meta Model API Documentation](https://dev.meta.ai/)
- [OpenAI Python SDK](https://github.com/openai/openai-python)
- [Pytest Documentation](https://docs.pytest.org/)
- [Jupyter Documentation](https://jupyter.org/documentation)

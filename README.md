# JP-PL Dictionary Compiler

Automated data pipeline that checks for updates on `japonski-pomocnik.pl`, scrapes the dictionary PDF, parses its content, and compiles it into an offline SQLite database with NHK pitch accent notation and Leeds vocabulary frequency rankings.

## Local execution

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
# JP-PL Dictionary Compiler

Automated data pipeline that checks for updates on `japonski-pomocnik.pl`, scrapes the dictionary PDF, parses its content, and compiles it into an offline SQLite database with NHK pitch accent notation and Leeds vocabulary frequency rankings.

## Local execution

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt

## Credits & data sources

This project compiles data from several open-source resources:

- **Dictionary Data**: Polish-Japanese dictionary compiled by Fryderyk Mazurek ([japonski-pomocnik.pl](https://www.japonski-pomocnik.pl) / [JaponskiPomocnik GitHub](https://github.com/dedyk/JaponskiPomocnik)), licensed under [GNU GPL v3.0](https://www.gnu.org/licenses/gpl-3.0.html).
- **Pitch Accent Dataset**: Derived from the NHK Pitch Accent Dictionary via [hlorenzi/jisho-open](https://github.com/hlorenzi/jisho-open).
- **JLPT Word Lists**: Compiled from [jamsinclair/open-anki-jlpt-decks](https://github.com/jamsinclair/open-anki-jlpt-decks) and [elzup/jlpt-word-list](https://github.com/elzup/jlpt-word-list) (MIT License).
- **Word Frequency Data**: Leeds Japanese Frequency List from [hingston/japanese](https://github.com/hingston/japanese).
- **PDF Extraction**: Built using [PyMuPDF](https://github.com/pymupdf/PyMuPDF) (AGPL-3.0).

## License

This compiler script and pipeline are released under the [GNU General Public License v3.0](LICENSE).
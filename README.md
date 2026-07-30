# JP-PL Dictionary Compiler

Automated data pipeline that polls the open-source [JaponskiPomocnik repository](https://github.com/dedyk/JaponskiPomocnik) for dictionary updates, downloads the raw structured vocabulary dataset (`word.csv`), and compiles it into an offline SQLite database enriched with NHK pitch accent notation, Leeds vocabulary frequency rankings, and JLPT level tags.

## Local execution

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate   # On Windows: venv\Scripts\activate

2. Download the latest upstream dataset and compile the database:
   ```bash
   # Downloads word.csv from upstream and compiles dictionary.db
   python check_version.py --force true
   python parsed_dict_to_sqldb.py 20260702
   python validate_db.py

## Credits & data sources

This project compiles data from several open-source resources:

- **Dictionary Data**: Polish-Japanese dictionary compiled by Fryderyk Mazurek ([japonski-pomocnik.pl](https://www.japonski-pomocnik.pl) / [JaponskiPomocnik GitHub](https://github.com/dedyk/JaponskiPomocnik)), licensed under [GNU GPL v3.0](https://www.gnu.org/licenses/gpl-3.0.html).
- **Pitch Accent Dataset**: Derived from the NHK Pitch Accent Dictionary via [hlorenzi/jisho-open](https://github.com/hlorenzi/jisho-open).
- **JLPT Word Lists**: Compiled from [jamsinclair/open-anki-jlpt-decks](https://github.com/jamsinclair/open-anki-jlpt-decks) and [elzup/jlpt-word-list](https://github.com/elzup/jlpt-word-list) (MIT License).
- **Word Frequency Data**: Leeds Japanese Frequency List from [hingston/japanese](https://github.com/hingston/japanese).
- **PDF Extraction**: Built using [PyMuPDF](https://github.com/pymupdf/PyMuPDF) (AGPL-3.0).

## License

This compiler script and pipeline are released under the [GNU General Public License v3.0](LICENSE).
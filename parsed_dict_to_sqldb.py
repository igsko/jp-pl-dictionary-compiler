import sqlite3
import json
import urllib.request
import ssl
import hashlib
import re

def get_stable_id(kanji, kana, romaji, translation_preview):
    """
    Generates a highly stable, collision-free, deterministic 63-bit 
    positive integer ID based on the entry's Japanese headings
    and a first word of the Polish translation as a semantic identifier

    Protects ID against changes to the word order in the PDF e.g. 
    adding/removing homographs
    and against typos/modifications further down in the definition
    """
    first_word = "unknown"
    if translation_preview:
        # split the translation at spaces and commas and take the first term
        tokens = re.split(r'[\s,\/]+', translation_preview.strip().lower())
        if tokens and tokens[0]:
            first_word = tokens[0]

    # combine the unique characteristics of the entry
    key = f"{kanji or ''}#{kana}#{romaji}#{first_word}"
    
    # generate a SHA-256 hash
    h = hashlib.sha256(key.encode('utf-8')).digest()
    
    # convert the first 8 bytes of the hash into an unsigned 64-bit integer
    unsigned_val = int.from_bytes(h[:8], byteorder='big')
    
    # constrain to a positive 63-bit signed integer to prevent SQLite overflow
    return unsigned_val & 0x7FFFFFFFFFFFFFFF

def to_hiragana(text):
    """Converts Katakana characters to Hiragana for uniform alignment matching."""
    if not text:
        return ""
    result = []
    for char in text:
        code = ord(char)
        if 0x30A1 <= code <= 0x30F6:
            result.append(chr(code - 0x60))
        else:
            result.append(char)
    return "".join(result)

def clean_pitch_reading(text):
    """Strips NHK pitch arrow symbols to isolate the clean Hiragana reading."""
    return text.replace('ꜛ', '').replace('ꜜ', '').replace('*', '').replace('~', '').strip()

# modify the build function signature to accept the version string
def build_sqlite_db_with_pitch(source_json, db_path, version_string="unknown"):
    ssl_context = ssl._create_unverified_context()

    # download the Leeds Japanese Word Frequency list
    print("Downloading Japanese frequency list...")
    freq_url = "https://raw.githubusercontent.com/hingston/japanese/master/44998-japanese-words.txt"
    freq_data = {}
    try:
        req = urllib.request.Request(freq_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ssl_context) as response:
            raw_lines = response.read().decode('utf-8').splitlines()
            for rank, word in enumerate(raw_lines, 1):
                word_clean = word.strip()
                if word_clean and word_clean not in freq_data:
                    freq_data[word_clean] = rank
        print(f"Loaded {len(freq_data)} ranked Japanese vocabulary words successfully!")
    except Exception as e:
        print(f"Could not load frequency list: {e}. Defaulting to unranked (999999).")

    # download the NHK Pitch Accent dataset from Lorenzi's jisho repo
    print("Downloading NHK Pitch Accent dataset...")
    pitch_url = "https://raw.githubusercontent.com/hlorenzi/jisho-open/main/backend/src/data/pitch_accent.txt"
    pitch_data = {}
    try:
        req = urllib.request.Request(pitch_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ssl_context) as response:
            pitch_lines = response.read().decode('utf-8').splitlines()
            for line in pitch_lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split(';')
                if len(parts) >= 3 and parts[0] == 'nhk':
                    writing = parts[1].strip()
                    reading_with_arrows = parts[2].strip()
                    clean_reading = clean_pitch_reading(reading_with_arrows)
                    
                    norm_writing = to_hiragana(writing)
                    norm_reading = to_hiragana(clean_reading)
                    
                    # Store multiple fallback keys for maximum lookup success
                    pitch_data[(writing, norm_reading)] = reading_with_arrows
                    pitch_data[(norm_writing, norm_reading)] = reading_with_arrows
                    
        print(f"Loaded {len(pitch_data)} pitch accent mappings successfully!")
    except Exception as e:
        print(f"Could not load pitch accent dataset: {e}. Defaulting to no pitch.")
    
    # add the metadata table structure
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("DROP TABLE IF EXISTS entries")
    cursor.execute("DROP TABLE IF EXISTS search_index")
    cursor.execute("DROP TABLE IF EXISTS metadata")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY,
            kanji TEXT,
            kana TEXT,
            romaji TEXT,
            translation TEXT,
            frequency_rank INTEGER,
            pitch_accent TEXT,
            full_json TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS search_index (
            key TEXT,
            entry_id INTEGER,
            FOREIGN KEY(entry_id) REFERENCES entries(id)
        )
    """)
    
    # insert the database version into the metadata table
    cursor.execute("INSERT INTO metadata (key, value) VALUES ('version', ?)", (version_string,))
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_search_key ON search_index(key)")
    
    with open(source_json, 'r', encoding='utf-8') as f:
        dictionary = json.load(f)
        
    print("Populating database...")
    for entry in dictionary:
        primary_jap_raw = entry["headwords"][0]["japanese"]
        primary_rom = entry["headwords"][0]["romaji"]
        
        parts = [p.strip() for p in primary_jap_raw.split(',')]
        if len(parts) >= 2:
            kanji, kana = parts[0], parts[1]
        else:
            kanji, kana = None, parts[0]
            
        norm_kana = to_hiragana(kana)

        translations = []
        for m in entry["meanings"]:
            translations.extend(m["translations"])
        translation_preview = ", ".join(translations[:3])

        # generate a stable id
        stable_id = get_stable_id(kanji, kana, primary_rom, translation_preview)

        # determine frequency rank (
        # only lookup kanji, fallback to kana if kana-only
        if kanji:
            rank = freq_data.get(kanji, 999999)
        else:
            rank = freq_data.get(kana, 999999)
            
        # determine pitch accent 
        # map using unified multi-key lookup
        pitch_accent = None
        if kanji:
            pitch_accent = pitch_data.get((kanji, norm_kana))
            if not pitch_accent:
                # fallback: try normalized kanji
                pitch_accent = pitch_data.get((to_hiragana(kanji), norm_kana))
        else:
            # kana-only words e.g., "シャーシ"
            pitch_accent = pitch_data.get((norm_kana, norm_kana))

        # insert the entry with the stable id
        cursor.execute(
            "INSERT INTO entries (id, kanji, kana, romaji, translation, frequency_rank, pitch_accent, full_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (stable_id, kanji, kana, primary_rom, translation_preview, rank, pitch_accent, json.dumps(entry, ensure_ascii=False))
        )
        
        keys = set()
        if kanji: keys.add(kanji.lower().strip())
        keys.add(kana.lower().strip())
        keys.add(primary_rom.lower().strip())
        for t in translations:
            keys.add(t.lower().strip())
            
        for key in keys:
            if key:
                cursor.execute("INSERT INTO search_index (key, entry_id) VALUES (?, ?)", (key, stable_id))
                
    conn.commit()
    cursor.execute("VACUUM")
    conn.close()
    print("Database compiled successfully!")

# execute the compiler
if __name__ == "__main__":
    import sys
    # read the version string if passed as a command line argument
    version = sys.argv[1] if len(sys.argv) > 1 else "manual_build"
    build_sqlite_db_with_pitch("extracted_dictionary.json", "dictionary.db", version)
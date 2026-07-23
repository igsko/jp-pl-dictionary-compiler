import sqlite3
import json
import urllib.request
import ssl
import hashlib
import re

def get_stable_id(kanji, kana, romaji, occurrence=0):
    """
    Generates a highly stable, collision-free, deterministic 63-bit 
    positive integer ID based on the entry's headwords and a sequential
    occurence counter for homographs.
    """
    # combine the unique characteristics of the entry
    key = f"{kanji or ''}#{kana}#{romaji}#{occurrence}"
    
    # generate a SHA-256 hash
    h = hashlib.sha256(key.encode('utf-8')).digest()
    
    # convert the first 8 bytes of the hash into an unsigned 64-bit integer
    unsigned_val = int.from_bytes(h[:8], byteorder='big')
    
    # constrain to a positive 53-bit signed integer to prevent JS precision loss
    return unsigned_val & 0x1FFFFFFFFFFFFF

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

def load_jlpt_data():
    """
    Downloads JLPT vocabulary datasets (N5 to N1) and returns a lookup dictionary.
    Keys can be (kanji_or_kana, norm_reading) tuples or plain kanji/kana strings.
    Values are integer JLPT levels (5=N5, 4=N4, 3=N3, 2=N2, 1=N1).
    """
    ssl_context = ssl._create_unverified_context()
    print("Downloading JLPT vocabulary datasets...")
    jlpt_data = {}

    sources = [
        ("open-anki-jlpt-decks", "https://raw.githubusercontent.com/jamsinclair/open-anki-jlpt-decks/main/src/n{level}.csv"),
        ("jlpt-word-list", "https://raw.githubusercontent.com/elzup/jlpt-word-list/master/src/n{level}.csv")
    ]

    for source_name, url_template in sources:
        success = True
        temp_data = {}
        for level in [5, 4, 3, 2, 1]:
            url = url_template.format(level=level)
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, context=ssl_context) as response:
                    raw_text = response.read().decode('utf-8')
                    lines = raw_text.splitlines()
                    if not lines:
                        continue

                    header = [h.strip().lower() for h in lines[0].split(',')]
                    expr_idx = 0
                    read_idx = 1

                    if 'expression' in header:
                        expr_idx = header.index('expression')
                    elif 'word' in header:
                        expr_idx = header.index('word')
                    elif 'kanji' in header:
                        expr_idx = header.index('kanji')

                    if 'reading' in header:
                        read_idx = header.index('reading')
                    elif 'kana' in header:
                        read_idx = header.index('kana')

                    start_row = 1 if ('expression' in header or 'word' in header or 'kanji' in header) else 0

                    for line in lines[start_row:]:
                        parts = [p.strip() for p in line.split(',')]
                        if len(parts) <= max(expr_idx, read_idx):
                            continue

                        expression = parts[expr_idx]
                        reading = parts[read_idx]

                        if not expression:
                            continue

                        clean_expr = re.sub(r'[\(\（].*?[\)\）]', '', expression).strip()
                        clean_read = re.sub(r'[\(\（].*?[\)\）]', '', reading).strip() if reading else ""

                        norm_expr = to_hiragana(clean_expr)
                        norm_read = to_hiragana(clean_read) if clean_read else norm_expr

                        if (clean_expr, norm_read) not in temp_data:
                            temp_data[(clean_expr, norm_read)] = level
                        if (norm_expr, norm_read) not in temp_data:
                            temp_data[(norm_expr, norm_read)] = level
                        if clean_expr not in temp_data:
                            temp_data[clean_expr] = level

            except Exception as e:
                print(f"Warning: Failed to fetch JLPT level N{level} from {source_name}: {e}")
                success = False
                break

        if success and len(temp_data) > 0:
            jlpt_data = temp_data
            print(f"Loaded {len(jlpt_data)} JLPT vocabulary mappings from {source_name}!")
            return jlpt_data

    # backup source: Bluskyo/JLPT_Vocabulary JSON
    try:
        json_url = "https://raw.githubusercontent.com/Bluskyo/JLPT_Vocabulary/master/JLPT_vocab_ALL.json"
        req = urllib.request.Request(json_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=ssl_context) as response:
            data = json.loads(response.read().decode('utf-8'))
            for word, entries in data.items():
                clean_word = re.sub(r'[\(\（].*?[\)\）]', '', word).strip()
                norm_word = to_hiragana(clean_word)
                for item in entries:
                    reading = item.get("reading", "")
                    clean_read = re.sub(r'[\(\（].*?[\)\）]', '', reading).strip()
                    norm_read = to_hiragana(clean_read) if clean_read else norm_word
                    lvl = item.get("level")
                    if isinstance(lvl, int) and 1 <= lvl <= 5:
                        jlpt_data[(clean_word, norm_read)] = lvl
                        jlpt_data[(norm_word, norm_read)] = lvl
                        if clean_word not in jlpt_data:
                            jlpt_data[clean_word] = lvl
        print(f"Loaded {len(jlpt_data)} JLPT vocabulary mappings from JSON backup source!")
    except Exception as e:
        print(f"Could not load JLPT dataset from any source: {e}. Defaulting to no JLPT tags.")

    return jlpt_data

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
            # map each Japanese word to its frequency rank
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
                # Ensure the line has enough columns and only process entries originating from the 'nhk' source
                if len(parts) >= 3 and parts[0] == 'nhk':
                    writing = parts[1].strip() # extract the writing kanji/kana
                    reading_with_arrows = parts[2].strip() # extract the reading - NHK pitch arrows
                    clean_reading = clean_pitch_reading(reading_with_arrows) #remove non-phonetic pitch/accent symbols
                    
                    # normalize katakana to hiragana in both writing and reading
                    norm_writing = to_hiragana(writing)
                    norm_reading = to_hiragana(clean_reading)
                    
                    # Store multiple fallback keys for maximum lookup success
                    pitch_data[(writing, norm_reading)] = reading_with_arrows
                    pitch_data[(norm_writing, norm_reading)] = reading_with_arrows
                    
        print(f"Loaded {len(pitch_data)} pitch accent mappings successfully!")
    except Exception as e:
        print(f"Could not load pitch accent dataset: {e}. Defaulting to no pitch.")

    # download JLPT level dataset
    jlpt_data = load_jlpt_data()
    
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
            jlpt INTEGER,
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
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_search_composite ON search_index(key, entry_id)")
    
    with open(source_json, 'r', encoding='utf-8') as f:
        dictionary = json.load(f)

    # keeps track of sequential homograph counts during db compilation
    seen_counts = {}
        
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

        # create a unique key based on the headword components
        hw_key = f"{kanji or ''}#{kana}#{primary_rom}"

        # retrieve the current occurrence count and increment it
        occurrence = seen_counts.get(hw_key, 0)
        seen_counts[hw_key] = occurrence + 1

        translations = []
        for m in entry["meanings"]:
            translations.extend(m["translations"])
        translation_preview = ", ".join(translations[:3])

        # generate a stable id
        stable_id = get_stable_id(kanji, kana, primary_rom, occurrence)

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

        # determine jlpt level
        jlpt_level = None
        if kanji:
            jlpt_level = jlpt_data.get((kanji, norm_kana))
            if jlpt_level is None:
                jlpt_level = jlpt_data.get((to_hiragana(kanji), norm_kana))
            if jlpt_level is None:
                jlpt_level = jlpt_data.get(kanji)
        else:
            jlpt_level = jlpt_data.get((kana, norm_kana))
            if jlpt_level is None:
                jlpt_level = jlpt_data.get((norm_kana, norm_kana))
            if jlpt_level is None:
                jlpt_level = jlpt_data.get(kana)

        if jlpt_level is not None:
            entry["jlpt"] = jlpt_level

        # insert the entry with the stable id
        cursor.execute(
            "INSERT INTO entries (id, kanji, kana, romaji, translation, frequency_rank, pitch_accent, jlpt, full_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (stable_id, kanji, kana, primary_rom, translation_preview, rank, pitch_accent, jlpt_level, json.dumps(entry, ensure_ascii=False))
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
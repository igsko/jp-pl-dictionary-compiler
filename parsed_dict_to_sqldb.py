import sqlite3
import json
import urllib.request
import ssl
import hashlib
import re
import sys
import time
import xml.etree.ElementTree as ET

# mapping internal POS codes to standard polish tags for Musubi's parser
def map_pos_string(pos_str):
    """
    Maps English JMdict POS strings to standard Polish labels
    matching Musubi's grammar tag parser (e.g. 'noun' -> 'rzeczownik').

    Args:
        pos_str (str): Raw POS string from XML (e.g., 'noun (common) (futsuumeishi)').

    Returns:
        str | None: Normalized Polish POS string, or None if unmapped.
    """
    if not pos_str: return None
    pos_str = pos_str.lower().strip()
    if 'noun' in pos_str and 'adjectival' not in pos_str: return 'rzeczownik'
    if 'verb' in pos_str: return 'czasownik'
    if 'adjective' in pos_str or 'adjectival' in pos_str: return 'przymiotnik'
    if 'adverb' in pos_str: return 'przysłówek'
    if 'pronoun' in pos_str: return 'zaimek'
    if 'interjection' in pos_str: return 'wykrzyknik'
    if 'conjunction' in pos_str: return 'spójnik'
    if 'prefix' in pos_str: return 'przedrostek'
    if 'suffix' in pos_str: return 'przyrostek'
    if 'counter' in pos_str: return 'klasyfikator'
    if 'number' in pos_str: return 'liczebnik'
    if 'expression' in pos_str: return 'wyrażenie'
    return pos_str

def ensure_valid_xml(xml_path):
    """Sanitizes word2.xml by ensuring there is exactly one XML header and one root element."""
    with open(xml_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # if multiple headers/roots are detected, clean up the XML structure in-place
    if content.count("<?xml") > 1 or content.count("<JMdict>") > 1:
        print("Detected raw concatenated XML. Sanitizing XML structure...")

        # strip all XML declarations
        content = re.sub(r'<\?xml.*?\?>', '', content, flags=re.DOTALL)

        # strip all intermediate <JMdict> root tags
        content = content.replace('<JMdict>', '').replace('</JMdict>', '')

        # re-wrap in a single root element
        clean_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<JMdict>\n' + content + '\n</JMdict>'
        
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(clean_xml)
        print("word2.xml structure sanitized successfully!")

def get_stable_id(kanji, kana, romaji, occurrence=0):
    """
    Generates a deterministic 53-bit unsigned integer ID derived from a SHA-256 hash.
    
    Why 53 bits?
    JavaScript's `Number.MAX_SAFE_INTEGER` is 2^53 - 1 (9,007,199,254,740,991).
    Restricting integer IDs to 53 bits prevents IEEE 754 precision truncation
    when IDs are passed over IPC to the Svelte frontend.

    Args:
        kanji (str | None): Kanji representation of the headword.
        kana (str): Kana reading.
        romaji (str): Romaji transcription.
        occurrence (int): A number to ensure unique IDs for duplicate entries.

    Returns:
        int: Deterministic 53-bit positive integer ID.
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
    """Converts Katakana characters to Hiragana for uniform alignment matching.

    Args:
        text (str): Input Japanese text.

    Returns:
        str: Converted Hiragana text.
    """
    if not text:
        return ""
    result = []
    for char in text:
        code = ord(char)
        # shift Katakana unicode range (0x30A1-0x30F6) down to Hiragana (0x3041-0x3096)
        if 0x30A1 <= code <= 0x30F6:
            result.append(chr(code - 0x60))
        else:
            result.append(char)
    return "".join(result)

def clean_pitch_reading(text):
    """
    Strips NHK pitch arrow notation symbols (ꜛ, ꜜ, *, ~) to isolate clean Hiragana.

    Args:
        text (str): Raw NHK pitch accent text.

    Returns:
        str: Clean Hiragana reading.
    """
    return text.replace('ꜛ', '').replace('ꜜ', '').replace('*', '').replace('~', '').strip()

def load_jlpt_data():
    """
    Downloads JLPT vocabulary datasets (N5 to N1) and returns a lookup dictionary.

    Returns:
        dict: Mapping of (word, reading) tuples or plain words to JLPT levels (5=N5 .. 1=N1).
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

                    if 'expression' in header: expr_idx = header.index('expression')
                    elif 'word' in header: expr_idx = header.index('word')
                    elif 'kanji' in header: expr_idx = header.index('kanji')

                    if 'reading' in header: read_idx = header.index('reading')
                    elif 'kana' in header: read_idx = header.index('kana')

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

                        if (clean_expr, norm_read) not in temp_data: temp_data[(clean_expr, norm_read)] = level
                        if (norm_expr, norm_read) not in temp_data: temp_data[(norm_expr, norm_read)] = level
                        if clean_expr not in temp_data: temp_data[clean_expr] = level

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

def build_sqlite_db(source_xml, db_path, version_string="unknown"):
    """
    Main compilation routine:
    1. Downloads external enrichment datasets (frequency rankings, pitch accent, JLPT levels).
    2. Configures SQLite connection PRAGMAs.
    3. Parses `word2.xml` and constructs structured JSON entry payloads.
    4. Performs batch record insertions and creates the search index after data insertion.
    5. Saves all changes and optimizes the final database file size.

    Args:
        source_xml (str): Input XML file path (`word2.xml`).
        db_path (str): Output SQLite database file path (`dictionary.db`).
        version_string (str): Version metadata string (e.g., '20260702').
    """
    start_time = time.time()
    ssl_context = ssl._create_unverified_context()

    # -------------------------------------------------------------------------
    # DOWNLOAD EXTERNAL DATASETS FOR ENRICHMENT
    # -------------------------------------------------------------------------

    # A. download the Leeds Japanese Word Frequency list
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

    # B. download the NHK Pitch Accent dataset from Lorenzi's jisho repo
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

    # C. download JLPT level dataset
    jlpt_data = load_jlpt_data()

    # -------------------------------------------------------------------------
    # DATABASE INITIALIZATION
    # -------------------------------------------------------------------------

    # add the metadata table structure
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # OPTIMIZATION: in-memory SQLite pragmas for bulk insertion
    cursor.execute("PRAGMA synchronous = OFF")
    cursor.execute("PRAGMA journal_mode = MEMORY")
    cursor.execute("PRAGMA cache_size = 1000000")
    cursor.execute("PRAGMA temp_store = MEMORY")

    # reset schema tables
    cursor.execute("DROP TABLE IF EXISTS entries")
    cursor.execute("DROP TABLE IF EXISTS search_index")
    cursor.execute("DROP TABLE IF EXISTS metadata")
    
    cursor.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")

    cursor.execute("""
        CREATE TABLE entries (
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
        CREATE TABLE search_index (
            key TEXT,
            entry_id INTEGER,
            FOREIGN KEY(entry_id) REFERENCES entries(id)
        )
    """)
    
    # save database version
    cursor.execute("INSERT INTO metadata (key, value) VALUES ('version', ?)", (version_string,))

    # -------------------------------------------------------------------------
    # SANITIZE & PARSE XML
    # -------------------------------------------------------------------------
    ensure_valid_xml(source_xml)

    print(f"Parsing XML database from {source_xml}...")
    tree = ET.parse(source_xml)
    root = tree.getroot()
    entries_elements = root.findall('entry')
    total_entries = len(entries_elements)

    print(f"Processing {total_entries} entries...")

    xml_lang_attr = "{http://www.w3.org/XML/1998/namespace}lang"
    # keeps track of sequential homograph counts during db compilation
    seen_counts = {}

    # batch buffers for executemany inserts to improve performance
    entries_batch = []
    search_index_batch = []
    BATCH_SIZE = 10000

    parse_start_time = time.time()

    # -------------------------------------------------------------------------
    # MAIN INGESTION LOOP
    # -------------------------------------------------------------------------
    for idx, entry in enumerate(entries_elements, 1):
        # A: extract kanji elements (<k_ele><keb>)
        kanjis = [k.findtext('keb').strip() for k in entry.findall('k_ele') if k.findtext('keb')]

        # B: extract reading elements (<r_ele><reb> & <romaji>)
        readings = []
        for r in entry.findall('r_ele'):
            reb = r.findtext('reb')
            rom = r.findtext('romaji')
            if reb:
                readings.append((reb.strip(), rom.strip() if rom else ""))
        if not readings:
            continue

        primary_kanji = kanjis[0] if kanjis else None
        primary_kana, primary_romaji = readings[0]

        primary_jap = f"{primary_kanji}, {primary_kana}" if primary_kanji else primary_kana

        # build headwords list, including alternate readings/spellings
        headwords_list = [{
            "japanese": primary_jap,
            "romaji": primary_romaji,
            "note": None
        }]

        # append alternative readings (e.g. 'もん' / 'モノ')
        for reb, rom in readings[1:]:
            alt_jap = f"{primary_kanji}, {reb}" if primary_kanji else reb
            headwords_list.append({
                "japanese": alt_jap,
                "romaji": rom,
                "note": None
            })

        #append alternative kanji spellings
        for k_text in kanjis[1:]:
            alt_jap = f"{k_text}, {primary_kana}"
            headwords_list.append({
                "japanese": alt_jap,
                "romaji": primary_romaji,
                "note": None
            })

        # C: extract meanings (<sense>)
        meanings_list=[]
        all_glosses_for_preview = []

        for s_idx, sense in enumerate(entry.findall('sense'), 1):
            # extract Polish translations
            pol_glosses = []
            for g in sense.findall('gloss'):
                lang = g.attrib.get(xml_lang_attr) or g.attrib.get('xml:lang')
                if lang == 'pol' and g.text and g.text.strip():
                    pol_glosses.append(g.text.strip())

            # fallback to English if no Polish translation
            if not pol_glosses:
                for g in sense.findall('gloss'):
                    lang = g.attrib.get(xml_lang_attr) or g.attrib.get('xml:lang')
                    if lang == 'eng' and g.text and g.text.strip():
                        pol_glosses.append(g.text.strip())

            if not pol_glosses:
                continue

            all_glosses_for_preview.extend(pol_glosses)

            # map POS tags and deduplicate
            pos_tags_raw = [map_pos_string(p.text) for p in sense.findall('pos') if p.text and map_pos_string(p.text)]
            pos_tags = list(dict.fromkeys(pos_tags_raw))  # remove duplicates while preserving order

            # extract usage notes (<s_inf>)
            s_infs = []
            for s in sense.findall('s_inf'):
                lang = s.attrib.get(xml_lang_attr) or s.attrib.get('xml:lang')
                if (lang == 'pol' or not lang) and s.text and s.text.strip():
                    s_infs.append(s.text.strip())

            # extract cross-references (<xref>)     
            xrefs = [x.text.strip() for x in sense.findall('xref') if x.text and x.text.strip()]

            metadata = []
            if pos_tags:
                metadata.extend(pos_tags)
            if s_infs:
                metadata.extend(s_infs)
            if xrefs:
                metadata.extend([f"zobacz również {xref}" for xref in xrefs])

            meanings_list.append({
                "index": s_idx,
                "translations": pol_glosses,
                "metadata": metadata
            })

        if not meanings_list:
            continue

        # short summary preview for search results list
        translation_preview = ", ".join(all_glosses_for_preview[:3])

        # generate stable collision-free ID
        hw_key = f"{primary_kanji or ''}#{primary_kana}#{primary_romaji}"
        occurrence = seen_counts.get(hw_key, 0)
        seen_counts[hw_key] = occurrence + 1

        stable_id = get_stable_id(primary_kanji, primary_kana, primary_romaji, occurrence) 
        norm_kana = to_hiragana(primary_kana)

        # D: enrich with frequency rank, pitch accent, and JLPT level
        if primary_kanji:
            rank = freq_data.get(primary_kanji, 999999)
            pitch_accent = pitch_data.get((primary_kanji, norm_kana)) or pitch_data.get((to_hiragana(primary_kanji), norm_kana))
            jlpt_level = jlpt_data.get((primary_kanji, norm_kana)) or jlpt_data.get((to_hiragana(primary_kanji), norm_kana)) or jlpt_data.get(primary_kanji)
        else:
            rank = freq_data.get(primary_kana, 999999)
            pitch_accent = pitch_data.get((norm_kana, norm_kana))
            jlpt_level = jlpt_data.get((primary_kana, norm_kana)) or jlpt_data.get((norm_kana, norm_kana)) or jlpt_data.get(primary_kana)

        entry_json = {
            "headwords": headwords_list,
            "meanings": meanings_list
        }

        if jlpt_level is not None:
            entry_json["jlpt"] = jlpt_level

        # queue entry record
        entries_batch.append((
            stable_id, primary_kanji, primary_kana, primary_romaji, 
            translation_preview, rank, pitch_accent, jlpt_level, 
            json.dumps(entry_json, ensure_ascii=False)
        ))

        # queue search index keys (kanji, kana, romaji, readings, glosses)
        keys = set()
        if primary_kanji: keys.add(primary_kanji.lower().strip())
        keys.add(primary_kana.lower().strip())
        if primary_romaji: keys.add(primary_romaji.lower().strip())
        for r_text, r_rom in readings[1:]:
            keys.add(r_text.lower().strip())
            if r_rom: keys.add(r_rom.lower().strip())
        for g_text in all_glosses_for_preview:
            keys.add(g_text.lower().strip())

        for key in keys:
            if key:
                cursor.execute("INSERT INTO search_index (key, entry_id) VALUES (?, ?)", (key, stable_id))

        # E: BATCH EXECUTION: flush batches every 10k items
        if len(entries_batch) >= BATCH_SIZE:
            cursor.executemany(
                "INSERT INTO entries (id, kanji, kana, romaji, translation, frequency_rank, pitch_accent, jlpt, full_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                entries_batch
            )
            cursor.executemany(
                "INSERT INTO search_index (key, entry_id) VALUES (?, ?)",
                search_index_batch
            )
            entries_batch.clear()
            search_index_batch.clear()

        # progress meter
        if idx % 10000 == 0 or idx == total_entries:
            elapsed = time.time() - parse_start_time
            speed = idx / elapsed if elapsed > 0 else 0
            percent = (idx / total_entries) * 100
            print(f"Progress: [{idx:,} / {total_entries:,}] ({percent:.1f}%) - {speed:,.0f} entries/sec")

    # -------------------------------------------------------------------------
    # FLUSH REMAINING BATCHES & DEFERRED B-TREE INDEX CREATION
    # -------------------------------------------------------------------------
    if entries_batch:
        cursor.executemany(
            "INSERT INTO entries (id, kanji, kana, romaji, translation, frequency_rank, pitch_accent, jlpt, full_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            entries_batch
        )
    if search_index_batch:
        cursor.executemany(
            "INSERT INTO search_index (key, entry_id) VALUES (?, ?)",
            search_index_batch
        )

    # SPEED OPTIMIZATION: construct composite search index AFTER all rows are inserted
    print("Building search index B-tree...")
    index_start_time = time.time()
    cursor.execute("CREATE INDEX idx_search_composite ON search_index(key, entry_id)")
    print(f"Index built in {time.time() - index_start_time:.2f} seconds.")

    # -------------------------------------------------------------------------
    # COMMIT & CLEANUP
    # -------------------------------------------------------------------------
    print("Committing transactions to disk...")
    conn.commit()

    print("Compacting and defragmenting SQLite database (VACUUM)...")
    vacuum_start_time = time.time()
    cursor.execute("VACUUM")
    print(f"Database compacted in {time.time() - vacuum_start_time:.2f} seconds.")
    conn.close()

    total_time = time.time() - start_time
    print(f"Database compiled successfully in {total_time:.2f} seconds!")

# execute the compiler
if __name__ == "__main__":
    import sys
    # read the version string if passed as a command line argument
    version = sys.argv[1] if len(sys.argv) > 1 else "manual_build"
    build_sqlite_db("word2.xml", "dictionary.db", version)
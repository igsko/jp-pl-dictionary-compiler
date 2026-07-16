import sqlite3
import sys

def validate():
    db_path = "dictionary.db"
    print(f"--- Starting database validation for: {db_path} ---")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Checking existence of key tables
        tables = [t[0] for t in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        required_tables = ["entries", "search_index", "metadata"]
        for table in required_tables:
            if table not in tables:
                print(f"CRITICAL ERROR: Missing required table '{table}'")
                sys.exit(1)
        print("✓ All required tables are present.")

        # Version validation in the metadata table
        version = cursor.execute("SELECT value FROM metadata WHERE key='version'").fetchone()
        if not version or not version[0] or version[0] == "unknown":
            print("CRITICAL ERROR: Metadata table lacks a valid version tag.")
            sys.exit(1)
        print(f"✓ Found valid database version tag: {version[0]}")

        # Minimal number of records validation
        # setting the safety threshold at 10,000 entries
        entry_count = cursor.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        if entry_count < 10000:
            print(f"CRITICAL ERROR: Entry count is suspiciously low ({entry_count} entries).")
            sys.exit(1)
        print(f"✓ Entry count check passed: {entry_count} entries found.")

        # Checking the search index
        index_count = cursor.execute("SELECT COUNT(*) FROM search_index").fetchone()[0]
        if index_count < 15000:
            print(f"CRITICAL ERROR: Search index count is suspiciously low ({index_count} indices).")
            sys.exit(1)
        print(f"✓ Search index count check passed: {index_count} indices found.")

        # Anchor words verification
        # we check if common jp words exist and have compiled correctly
        anchors = ["日本語", "気", "本"]
        for anchor in anchors:
            res = cursor.execute("SELECT id, kana, translation FROM entries WHERE kanji=?", (anchor,)).fetchone()
            if not res:
                print(f"CRITICAL ERROR: Anchor word '{anchor}' was not compiled into the database.")
                sys.exit(1)
            
            # check if the translation is not empty
            if not res[2] or len(res[2].strip()) < 2:
                print(f"CRITICAL ERROR: Anchor word '{anchor}' has a corrupted or empty translation preview.")
                sys.exit(1)
        print("✓ Anchor words parsed and verified successfully.")

        # Checking structural JSON integrity
        sample_json_str = cursor.execute("SELECT full_json FROM entries LIMIT 1").fetchone()[0]
        import json
        try:
            sample_json = json.loads(sample_json_str)
            if "headwords" not in sample_json or "meanings" not in sample_json:
                raise ValueError("Missing structured fields inside full_json.")
        except Exception as json_err:
            print(f"CRITICAL ERROR: Failed to parse or validate full_json payload structure: {json_err}")
            sys.exit(1)
        print("✓ Full JSON schema payload checked and validated.")

        print("=== DATABASE VALIDATION PASSED SUCCESSFULLY! ===")
        conn.close()

    except Exception as e:
        print(f"CRITICAL UNEXPECTED ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    validate()
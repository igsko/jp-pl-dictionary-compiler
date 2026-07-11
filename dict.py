import fitz
import re
import json

def extract_raw_text(pdf_path, exclude_attribution_page=True):
    """
    Extracts text from the PDF, dynamically finding the start of Chapter 3 
    and omitting the last page.
    """
    doc = fitz.open(pdf_path)
    all_pages = []
    
    # extract text from every page
    for page in doc:
        all_pages.append(page.get_text("text"))
    
    # find the start of chapter 3
    start_page_idx = 0
    for idx, page_text in enumerate(all_pages):
        # Look for the characteristic main header of Chapter 3
        if "Rozdział 3" in page_text and "Spis słów" in page_text:
            start_page_idx = idx
            print(f"-> Chapter 3 detected starting at PDF page {start_page_idx + 1}")
            break
    else:
        print("-> Warning: Could not dynamically find the Chapter 3 header. Defaulting to page 1.")

    # slice pages from chapter 3 start, up to the second-to-last page
    end_page_idx = -1 if exclude_attribution_page else None
    target_pages = all_pages[start_page_idx:end_page_idx]
    
    print(f"-> Processing {len(target_pages)} pages of dictionary entries (discarded {start_page_idx} index pages).")
    
    return "\n".join(target_pages)

def clean_dictionary_text(text):
    """Removes headers, footers, and page-break artifacts."""
    # remove page headers on all pages e.g., "3.1. A ROZDZIAŁ 3. SPIS SŁÓW"
    text = re.sub(r'(?:\d+\.\d+\.\s+[A-ZŚĆŹŻŁÓa-z]\s+)?ROZDZIAŁ\s+\d+\.\s+SPIS\s+SŁÓW', '', text)
    text = re.sub(r'Słownik\s+Japońsko-Polski', '', text)
    
    # remove standalone page numbers e.g., "1055" on its own line
    text = re.sub(r'^\s*\d{1,4}\s*$', '', text, flags=re.MULTILINE)

    # clean up line-break hyphenation e.g., "prze-\nstrzeni" -> "przestrzeni"
    text = re.sub(r'(\w+)-\n\s*(\w+)', r'\1\2', text)
    # handle trailing comma hyphenations "na-,\nzywania" -> "nazywania,"
    text = re.sub(r'(\w+)-\s*,\s*\n\s*(\w+)', r'\1\2,', text)
    
    # normalize multiple newlines to clean up spacing
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text

def parse_entry(entry_text):
    """Parses an individual raw entry block into a structured dictionary."""
    if "Znaczenie" not in entry_text:
        return None

    # split into headwords and definitions
    parts = re.split(r'\nZnaczenie\s+', entry_text, maxsplit=1)
    headword_section = parts[0].strip()
    meaning_section = parts[1].strip() if len(parts) > 1 else ""

    parsed_entry = {
        "headwords": [],
        "meanings": []
    }

    # parse headwords
    for line in headword_section.split('\n'):
        line = line.strip()
        if not line:
            continue
        # split by the last comma to isolate romaji from kanji/kana/notes
        if ',' in line:
            japanese_part, romaji = line.rsplit(',', 1)
            # check for parenthetical notes within the japanese part
            note_match = re.search(r'\(([^)]+)\)', japanese_part)
            note = note_match.group(1).strip() if note_match else None
            clean_japanese = re.sub(r'\s*\([^)]+\)', '', japanese_part).strip()

            parsed_entry["headwords"].append({
                "japanese": clean_japanese,
                "romaji": romaji.strip(),
                "note": note
            })

    # parse meanings
    # match standard numbers 1,2 or Unicode circled numbers ①,② at the start of a line
    meaning_chunks = re.split(r'\n(?=(?:\d+|[\u2460-\u2473]))\s*', "\n" + meaning_section)

    for chunk in meaning_chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        lines = chunk.split('\n')
        first_line = lines[0].strip()

        # extract the index "1" or "①"
        index_match = re.match(r'^(\d+|[\u2460-\u2473])\s*(.*)', first_line)
        if index_match:
            index_str = index_match.group(1)
            remaining_text = index_match.group(2).strip()
            lines[0] = remaining_text
        else:
            index_str = "1"

        # convert unicode circled numbers to standard integers if possible
        if ord(index_str[0]) in range(0x2460, 0x2469):
            index_val = ord(index_str[0]) - 0x245F
        else:
            index_val = int(index_str) if index_str.isdigit() else 1

        meaning_obj = {
            "index": index_val,
            "translations": [],
            "metadata": []
        }

        # helper for stitching sentence continuations together
        def add_translation(text_to_add):
            if not meaning_obj["translations"]:
                meaning_obj["translations"].append(text_to_add)
            else:
                last = meaning_obj["translations"][-1]
                # if the line starts with lowercase, or the previous line does not end with terminal punctuation
                # merge them into a single paragraph instead of splitting them with commas
                if text_to_add[0].islower() or (last and last[-1] not in ['.', '!', '?']):
                    merged = last.rstrip() + " " + text_to_add
                    merged = re.sub(r'\s+', ' ', merged)
                    meaning_obj["translations"][-1] = merged
                else:
                    meaning_obj["translations"].append(text_to_add)

        # parse lines into translations or bullet point attributes
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith('·') or line.startswith('.'):
                # clean the bullet points
                cleaned_meta = re.sub(r'^[·\.]\s*', '', line).strip()
                # filter out page number + column header leaks (eg. "17. AR" or "17 AR")
                if re.match(r'^\d+\.?\s*[A-ZŚĆŹŻŁÓA-Za-z]+$', cleaned_meta):
                    continue
                # length guard:
                # if the tag is too long, treat it as part of the translation text
                if len(cleaned_meta) <= 30:
                    meaning_obj["metadata"].append(cleaned_meta)
                else:
                    add_translation(cleaned_meta)
            else:
                add_translation(line)

        parsed_entry["meanings"].append(meaning_obj)

    return parsed_entry

def process_pdf_dictionary(pdf_path, output_json_path):
    print("Reading PDF...")
    raw_text = extract_raw_text(pdf_path)
    
    print("Cleaning text stream...")
    cleaned_text = clean_dictionary_text(raw_text)
    
    # split the clean text into entries using the "Słowo " delimiter
    print("Splitting entries...")
    raw_entries = re.split(r'\nSłowo\s+', cleaned_text)
    
    parsed_dictionary = []
    
    for raw_entry in raw_entries:
        parsed = parse_entry(raw_entry)
        if parsed and parsed["headwords"]:
            parsed_dictionary.append(parsed)
            
    print(f"Successfully parsed {len(parsed_dictionary)} entries.")
    
    # write to a clean JSON file
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(parsed_dictionary, f, ensure_ascii=False, indent=2)
    print(f"Data saved to {output_json_path}")

# run the parser
process_pdf_dictionary("dictionary-sample.pdf", "extracted_dictionary.json")

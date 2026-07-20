import os
import re
import urllib.request
import json
import ssl
import argparse

def check():
    ssl_context = ssl._create_unverified_context()

    parser = argparse.ArgumentParser(description="Check dictionary version and download PDF")
    parser.add_argument("--force", type=str, default="false", help="Force rebuild ('true' || 'false')")
    parser.add_argument("--custom-version", type=str, default="", help="Optional custom version override")
    args = parser.parse_args()
    
    # scrape the website for the latest version string
    url = "https://www.japonski-pomocnik.pl/wordDictionary"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    scraped_version = ""
    try:
        with urllib.request.urlopen(req, context=ssl_context) as response:
            html = response.read().decode('utf-8')
            # find 'wersja', then up to 100 characters, then 8 digits
            match = re.search(r'Wersja.{0,100}?(\d{8})', html, re.IGNORECASE | re.DOTALL)
            if match:
                scraped_version = match.group(1)
                print(f"Latest website version: {scraped_version}")
    except Exception as e:
        print(f"Error scraping website: {e}")

    # if a custom version tag is supplied, override the scraped version
    if args.custom_version.strip():
        scraped_version = args.custom_version.strip()
        print(f"Applying custom version tag override: {scraped_version}")
    elif not scraped_version:
        print("Could not find version string on website and no custom version supplied")
        return

    # get the latest release tag from GitHub's API
    # default to "igsko/jp-pl-dictionary-compiler" if GITHUB_REPOSITORY environment is not set
    repo = os.environ.get("GITHUB_REPOSITORY", "igsko/jp-pl-dictionary-compiler")
    github_url = f"https://api.github.com/repos/{repo}/releases/latest"
    gh_req = urllib.request.Request(github_url, headers={'User-Agent': 'Mozilla/5.0'})
    
    latest_tag = ""
    try:
        with urllib.request.urlopen(gh_req, context=ssl_context) as response:
            data = json.loads(response.read().decode('utf-8'))
            latest_tag = data.get("tag_name", "") # e.g. "v20260702"
            print(f"Latest GitHub Release tag: {latest_tag}")
    except Exception as e:
        print(f"No previous release found on GitHub or error fetching: {e}")

    # extract just the 8digit date from latest github release tag e.g. "v20260702l" -> "20260702"
    latest_version_base = ""
    if latest_tag:
        match_date = re.search(r'\d{8}', latest_tag)
        if match_date:
            latest_version_base = match_date.group(0)
            print(f"Parsed base version from GitHub: {latest_version_base}")

    new_version = "false"

    # Trigger the database compilation pipeline only if the scraped website version
    # is strictly newer than the base date of the latest GitHub release.
    # Using a '>' comparison prevents automated cron builds from 
    # executing a downgrade release (e.g., publishing '20260702') when a manual 
    # hotfix build with an alphabetical suffix (e.g., 'v20260702l') is already active.
    if scraped_version and (not latest_version_base or scraped_version > latest_version_base):
        print("New version detected! Preparing database pipeline...")
        new_version = "true"
        
        # download the full PDF from the website directly
        pdf_url = "https://www.japonski-pomocnik.pl/wordDictionary/dictionary-full.pdf"
        print(f"Downloading PDF from {pdf_url}...")
        pdf_req = urllib.request.Request(pdf_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(pdf_req, context=ssl_context) as pdf_resp:
            with open("dictionary-sample.pdf", "wb") as f:
                f.write(pdf_resp.read())
        print("PDF downloaded successfully!")
    else:
        print("Database is already up-to-date or GitHub has a newer manual build. Skipping compilation.")

    # write output variables for the gitHub actions workflow runner
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"new_version={new_version}\n")
            f.write(f"scraped_version={scraped_version}\n")

if __name__ == "__main__":
    check()
import os
import re
import urllib.request
import json
import ssl

def check():
    ssl_context = ssl._create_unverified_context()
    
    # scrape the website for the latest version string
    url = "https://www.japonski-pomocnik.pl/wordDictionary"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, context=ssl_context) as response:
            html = response.read().decode('utf-8')
            # find 'wersja', then up to 100 characters, then 8 digits
            match = re.search(r'Wersja.{0,100}?(\d{8})', html, re.IGNORECASE | re.DOTALL)
            if not match:
                print("Could not find version string on website.")
                # print diagnostic information
                print("\n--- DIAGNOSTIC INFO ---")
                print(f"response status: {response.status}")
                print(f"headers: {response.headers}")
                print("HTML snippet, first 1000 chars:")
                print(html[:1000])
                print("-----------------------\n")
                return
            scraped_version = match.group(1)
            print(f"Latest website version: {scraped_version}")
    except Exception as e:
        print(f"Error scraping website: {e}")
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

    # compare and set outputs
    expected_tag = f"v{scraped_version}"
    new_version = "false"
    
    if latest_tag != expected_tag:
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
        print("Database is already up-to-date. Skipping compilation.")

    # write output variables for the gitHub actions workflow runner
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"new_version={new_version}\n")
            f.write(f"scraped_version={scraped_version}\n")

if __name__ == "__main__":
    check()
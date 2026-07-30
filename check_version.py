import os
import re
import urllib.request
import json
import ssl
import argparse
import sys

def check():
    ssl_context = ssl._create_unverified_context()

    parser = argparse.ArgumentParser(description="Check dictionary version and download PDF")
    parser.add_argument("--force", type=str, default="false", help="Force rebuild ('true' || 'false')")
    parser.add_argument("--custom-version", type=str, default="", help="Optional custom version override")
    args = parser.parse_args()

    # upstream data source
    upstream_repo = "dedyk/JaponskiPomocnik"
    file_path = "db/word.csv"

    # default to "igsko/jp-pl-dictionary-compiler" if GITHUB_REPOSITORY environment is not set
    my_repo = os.environ.get("GITHUB_REPOSITORY", "igsko/jp-pl-dictionary-compiler")
    
    # check github for the latest version string
    api_url = f"https://api.github.com/repos/{upstream_repo}/commits?path={file_path}&per_page=1"
    req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
    scraped_version = ""

    try:
        with urllib.request.urlopen(req, context=ssl_context) as response:
            commits = json.loads(response.read().decode('utf-8'))
            if commits:
                commit_msg = commits[0]['commit']['message']
                match = re.search(r'(\d{8})', commit_msg)
                if match:
                    scraped_version = match.group(1)
                else:
                    commit_date = commits[0]['commit']['committer']['date']
                    scraped_version = commit_date[:10].replace("-", "")
                
                print(f"Latest upstream DB ver: {scraped_version}")
    except Exception as e:
        print(f"ERROR: Error fetching from GitHub API: {e}")
        sys.exit(1)

    # if a custom version tag is supplied, override the scraped version
    if args.custom_version.strip():
        scraped_version = args.custom_version.strip()
        print(f"Applying custom version tag override: {scraped_version}")
    elif not scraped_version:
        print("ERROR: Could not find version string upstream and no custom version supplied")
        sys.exit(1)

    # get the latest release tag from GitHub's API
    github_url = f"https://api.github.com/repos/{my_repo}/releases/latest"
    gh_req = urllib.request.Request(github_url, headers={'User-Agent': 'Mozilla/5.0'})
    
    latest_version_base = ""
    try:
        with urllib.request.urlopen(gh_req, context=ssl_context) as response:
            data = json.loads(response.read().decode('utf-8'))
            latest_tag = data.get("tag_name", "") # e.g. "v20260702"
            match_date = re.search(r'\d{8}', latest_tag)
            if match_date:
                latest_version_base = match_date.group(0)
                print(f"Parsed base version from GitHub: {latest_version_base}")
    except Exception as e:
        print(f"Notice: No previous release found on GitHub or error fetching: {e}")

    new_version = "false"
    force_build = str(args.force).lower() in ["true", "1", "yes"]
    if force_build:
        print("Force build flag is TRUE. Forcing database compilation pipeline...")

    # Trigger the database compilation pipeline only if the scraped website version
    # is strictly newer than the base date of the latest GitHub release,
    # or when compilation forced by the user.
    # executing a downgrade release (e.g., publishing '20260702') when a manual 
    # hotfix build with an alphabetical suffix (e.g., 'v20260702l') is already active.
    if force_build or (scraped_version and (not latest_version_base or scraped_version > latest_version_base)):
        print("New version detected! Preparing database pipeline...")
        new_version = "true"
        
        # download the raw CSV
        csv_url = f"https://raw.githubusercontent.com/{upstream_repo}/master/{file_path}"
        print(f"Downloading data from {csv_url}...")
        csv_req = urllib.request.Request(csv_url, headers={'User-Agent': 'Mozilla/5.0'})

        try:
            with urllib.request.urlopen(csv_req, context=ssl_context) as csv_resp:
                with open("word.csv", "wb") as f:
                    f.write(csv_resp.read())
            print("CSV downloaded successfully!")
        except Exception as e:
            print(f"ERROR: Failed to download CSV from {csv_url}: {e}")
            sys.exit(1)
    else:
        print("Database is already up-to-date. Skipping compilation.")

    # write output variables for the gitHub actions workflow runner
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"new_version={new_version}\n")
            f.write(f"scraped_version={scraped_version}\n")

if __name__ == "__main__":
    check()
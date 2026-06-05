"""
Entry point: run_pipeline.py

Usage:
  python src/run_pipeline.py

Expects data in data/raw/. Writes public/index.json.
Set DATA_DIR env var to override raw data directory.
"""

import os
import sys

# Allow running from repo root or src/
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import pipeline
import index_build

DATA_DIR = os.environ.get("DATA_DIR", "data/raw")
OUT_PATH = os.environ.get("OUT_PATH", "public/index.json")

POSTINGS_FILE = os.path.join(DATA_DIR, "job_postings.csv")
SKILLS_FILE = os.path.join(DATA_DIR, "job_skills.csv")


def main():
    if not os.path.exists(POSTINGS_FILE):
        print(f"ERROR: {POSTINGS_FILE} not found.")
        print()
        print("Download the LinkedIn Job Postings dataset from Kaggle:")
        print("  https://www.kaggle.com/datasets/arshkon/linkedin-job-postings")
        print(f"Place job_postings.csv (and optionally job_skills.csv) in {DATA_DIR}/")
        sys.exit(1)

    print(f"Loading {POSTINGS_FILE} ...")
    skills_path = SKILLS_FILE if os.path.exists(SKILLS_FILE) else None
    raw_df = pipeline.load_linkedin(POSTINGS_FILE, skills_path)
    print(f"  Loaded {len(raw_df):,} rows spanning {raw_df['month'].nunique()} months")

    print("Running pipeline ...")
    clean_df = pipeline.run(raw_df)

    print("Building index ...")
    index = index_build.build_index(clean_df)
    index_build.write_index(index, OUT_PATH)

    n_skills_with_data = sum(
        1 for v in index["skills"].values()
        if any(s["count"] > 0 for s in v["series"])
    )
    print(f"  Skills with data: {n_skills_with_data}/{len(index['skills'])}")
    print(f"  Data through:     {index['data_through']}")
    print(f"  Generated at:     {index['generated_at']}")
    print("Done.")


if __name__ == "__main__":
    main()

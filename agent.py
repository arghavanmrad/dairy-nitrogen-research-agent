
import requests
import pandas as pd
from pathlib import Path

SEARCHES = [
    '"dairy cow" AND nitrogen',
    '"dairy cattle" AND "nitrogen use efficiency"',
    '"dairy cow" AND "alternative protein"',
    '"dairy cattle" AND protein AND emissions'
]

API_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

def collect_literature():
    records = []

    for query in SEARCHES:
        params = {
            "query": query,
            "format": "json",
            "pageSize": 100,
            "resultType": "core"
        }

        response = requests.get(API_URL, params=params, timeout=60)
        response.raise_for_status()

        articles = response.json().get("resultList", {}).get("result", [])

        for article in articles:
            records.append({
                "title": article.get("title", ""),
                "year": article.get("pubYear", ""),
                "authors": article.get("authorString", ""),
                "journal": article.get("journalTitle", ""),
                "doi": article.get("doi", ""),
                "pmid": article.get("pmid", ""),
                "pmcid": article.get("pmcid", ""),
                "abstract": article.get("abstractText", ""),
                "source": article.get("source", ""),
                "query": query
            })

    df = pd.DataFrame(records)

    if df.empty:
        print("No articles found.")
        return

    df = df.drop_duplicates(subset=["title"])
    output = Path("output")
    output.mkdir(exist_ok=True)

    df.to_csv(
        output / "dairy_nitrogen_literature.csv",
        index=False,
        encoding="utf-8-sig"
    )

    df.to_excel(
        output / "dairy_nitrogen_literature.xlsx",
        index=False
    )

    print(f"Collected {len(df)} unique articles.")

if __name__ == "__main__":
    collect_literature()

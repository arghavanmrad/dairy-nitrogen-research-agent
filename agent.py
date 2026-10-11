
import re
import time
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from pathlib import Path

API = "https://www.ebi.ac.uk/europepmc/webservices/rest"
OUT = Path("output")
OUT.mkdir(exist_ok=True)

QUERIES = [
    '"dairy cow" AND nitrogen',
    '"dairy cattle" AND "nitrogen use efficiency"',
    '"dairy cow" AND "alternative protein"',
    '"dairy cattle" AND protein AND emissions',
    '"dairy cow" AND "rapeseed meal"',
    '"dairy cow" AND "soybean meal"',
    '"dairy cow" AND canola AND nitrogen',
    '"dairy cow" AND "amino acid" AND nitrogen'
]

VARIABLES = {
    "milk_yield": r"milk yield|milk production|kg milk",
    "milk_protein": r"milk protein|protein yield",
    "nitrogen_intake": r"nitrogen intake|N intake|N consumed",
    "nitrogen_efficiency": r"nitrogen use efficiency|nitrogen efficiency|N efficiency",
    "milk_nitrogen": r"milk nitrogen|nitrogen in milk|milk N",
    "urinary_nitrogen": r"urinary nitrogen|urine nitrogen|urinary N",
    "fecal_nitrogen": r"fecal nitrogen|faecal nitrogen|fecal N",
    "manure_nitrogen": r"manure nitrogen|nitrogen excretion",
    "mun": r"milk urea nitrogen|MUN",
    "bun": r"blood urea nitrogen|BUN",
    "dry_matter_intake": r"dry matter intake|DMI",
    "crude_protein": r"crude protein|dietary CP|CP content",
    "feed_efficiency": r"feed efficiency|feed conversion",
    "body_weight": r"body weight|live weight",
    "alternative_protein": (
        r"rapeseed|canola meal|soybean meal|soybean|"
        r"lupin|pea protein|faba bean|insect meal|"
        r"yeast protein|alternative protein|sunflower meal"
    ),
    "statistics": r"standard error|SEM|SE\b|SD\b|standard deviation|P\s*[<=>]\s*0?\.\d+"
}

NUMBER = re.compile(
    r"(?<![A-Za-z])[-+]?\d+(?:,\d{3})*(?:\.\d+)?"
    r"\s*(?:%|kg|g|mg|mmol|mol|L|d|day|days|h|"
    r"week|weeks|cow|cows|g/kg|kg/day|g/day)?",
    re.I
)

def clean_text(element):
    return " ".join("".join(element.itertext()).split())

def tags_for(text):
    found = []
    for name, pattern in VARIABLES.items():
        if re.search(pattern, text, re.I):
            found.append(name)
    return ";".join(found)

def get_articles(query):
    params = {
        "query": query,
        "format": "json",
        "pageSize": 100,
        "resultType": "core"
    }
    response = requests.get(API + "/search", params=params, timeout=60)
    response.raise_for_status()
    return response.json().get("resultList", {}).get("result", [])

def extract_full_text(article):
    pmcid = article.get("pmcid", "")
    if not pmcid:
        return [], [], "no_pmcid"

    url = f"{API}/{pmcid}/fullTextXML"

    try:
        response = requests.get(url, timeout=60)
        if response.status_code != 200:
            return [], [], f"full_text_unavailable_{response.status_code}"

        root = ET.fromstring(response.content)
    except Exception as exc:
        return [], [], f"error_{type(exc).__name__}"

    paragraphs = []
    tables = []

    for section in root.iter():
        if section.tag.split("}")[-1] != "sec":
            continue

        heading = ""
        for child in list(section):
            if child.tag.split("}")[-1] == "title":
                heading = clean_text(child)
                break

        for child in section.iter():
            if child.tag.split("}")[-1] == "p":
                text = clean_text(child)
                if text:
                    paragraphs.append((heading, text))

    for wrap in root.iter():
        if wrap.tag.split("}")[-1] != "table-wrap":
            continue

        caption = ""
        for child in list(wrap):
            if child.tag.split("}")[-1] == "caption":
                caption = clean_text(child)

        for table in wrap.iter():
            if table.tag.split("}")[-1] != "tr":
                continue

            cells = []
            for cell in list(table):
                if cell.tag.split("}")[-1] in ("td", "th"):
                    cells.append(clean_text(cell))

            if cells:
                tables.append({
                    "table_caption": caption,
                    "row_text": " | ".join(cells)
                })

    return paragraphs, tables, "full_text_retrieved"

def main():
    articles_by_id = {}

    for query in QUERIES:
        print("Searching:", query)
        try:
            results = get_articles(query)
            for article in results:
                key = (
                    article.get("pmcid")
                    or article.get("doi")
                    or article.get("pmid")
                    or article.get("title", "")
                )
                if key:
                    if key not in articles_by_id:
                        articles_by_id[key] = article
                    articles_by_id[key].setdefault(
                        "matched_queries", []
                    ).append(query)
        except Exception as exc:
            print("Search error:", type(exc).__name__)

    literature = []
    numeric_candidates = []
    table_rows = []

    for index, article in enumerate(articles_by_id.values(), 1):
        title = article.get("title", "")
        pmcid = article.get("pmcid", "")
        doi = article.get("doi", "")
        abstract = article.get("abstractText", "")

        print(f"Article {index}/{len(articles_by_id)}:", title[:70])

        paragraphs, tables, status = extract_full_text(article)

        literature.append({
            "title": title,
            "year": article.get("pubYear", ""),
            "authors": article.get("authorString", ""),
            "journal": article.get("journalTitle", ""),
            "doi": doi,
            "pmid": article.get("pmid", ""),
            "pmcid": pmcid,
            "abstract": abstract,
            "full_text_status": status,
            "matched_queries": "; ".join(
                article.get("matched_queries", [])
            )
        })

        article_id = pmcid or article.get("pmid", "") or doi

        # Candidate numerical statements from full text
        for section, paragraph in paragraphs:
            tags = tags_for(paragraph)
            numbers = NUMBER.findall(paragraph)

            if tags and numbers:
                numeric_candidates.append({
                    "article_id": article_id,
                    "title": title,
                    "doi": doi,
                    "pmcid": pmcid,
                    "section": section,
                    "variables_detected": tags,
                    "numbers_detected": "; ".join(numbers),
                    "evidence_text": paragraph,
                    "source_level": "full_text_paragraph",
                    "verified": False
                })

        # Candidate values from table rows
        for table in tables:
            row = table["row_text"]
            tags = tags_for(row)
            numbers = NUMBER.findall(row)

            if tags and numbers:
                table_rows.append({
                    "article_id": article_id,
                    "title": title,
                    "doi": doi,
                    "pmcid": pmcid,
                    "table_caption": table["table_caption"],
                    "variables_detected": tags,
                    "numbers_detected": "; ".join(numbers),
                    "table_row": row,
                    "source_level": "full_text_table",
                    "verified": False
                })

        # Abstract-only candidates, kept separate from full-text data
        if abstract and not paragraphs:
            tags = tags_for(abstract)
            numbers = NUMBER.findall(abstract)
            if tags and numbers:
                numeric_candidates.append({
                    "article_id": article_id,
                    "title": title,
                    "doi": doi,
                    "pmcid": pmcid,
                    "section": "Abstract",
                    "variables_detected": tags,
                    "numbers_detected": "; ".join(numbers),
                    "evidence_text": abstract,
                    "source_level": "abstract_only",
                    "verified": False
                })

        time.sleep(0.2)

    pd.DataFrame(literature).to_csv(
        OUT / "literature.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(numeric_candidates).to_csv(
        OUT / "numeric_candidates.csv",
        index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(table_rows).to_csv(
        OUT / "table_candidates.csv",
        index=False, encoding="utf-8-sig"
    )

    print("Finished.")
    print("Articles:", len(literature))
    print("Numerical text candidates:", len(numeric_candidates))
    print("Table-row candidates:", len(table_rows))

if __name__ == "__main__":
    main()

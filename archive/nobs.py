from bs4 import BeautifulSoup
import re
import pandas as pd

# Load the saved HTML tables from the all_calendars.txt file
with open("all_calendars.txt", "r", encoding="utf-8") as file:
    raw_html = file.read()

# Prepare regex
case_number_regex = re.compile(r"\d+:\d{2}-[a-z]{2}-\d{5}-[A-Z]+(?:-\d+)?", re.IGNORECASE)
date_regex = re.compile(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}")
time_regex = re.compile(r"^\d{1,2}:\d{2}[AP]M")
civil_criminal_regex = re.compile(r"-cv-|-cr-", re.IGNORECASE)

# Split tables by comment markers to keep judge context
chunks = re.split(r'(<!-- Source: .*?-->)', raw_html)
parsed_rows = []

# Iterate in pairs: comment, table
for i in range(1, len(chunks), 2):
    comment = chunks[i]
    table_html = chunks[i + 1]

    # Extract judge name from URL
    judge_url_match = re.search(r"<!-- Source: (.*?) -->", comment)
    judge_url = judge_url_match.group(1).strip() if judge_url_match else ""
    judge_name_match = re.search(r"/([^/]+)$", judge_url)
    judge_name = judge_name_match.group(1).replace("-", " ").replace(".aspx", "").strip() if judge_name_match else ""

    soup_table = BeautifulSoup(table_html, "html.parser")
    tds = soup_table.find_all("td")

    current_date = ""
    current_hearing_type = ""

    for td in tds:
        lines = td.get_text("\n", strip=True).split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Date line
            if date_regex.match(line):
                current_date = line
                continue

            # Hearing type
            if line.startswith("-"):
                current_hearing_type = line.strip("- ")
                continue

            # Time + case line
            if time_regex.match(line):
                parts = line.split(" ", 1)
                time_part = parts[0]
                rest = parts[1] if len(parts) > 1 else ""

                case_match = case_number_regex.search(rest)
                if not case_match:
                    continue

                case_number = case_match.group(0)
                after_case = rest[case_match.end():].strip(" -")

                # Split parties
                parties = re.split(r"\s+v\.?\s+|\s+vs\.?\s+", after_case)
                plaintiff = parties[0].strip() if len(parties) > 0 else ""
                defendant = parties[1].strip() if len(parties) > 1 else ""

                # Determine purpose
                purpose = "other"
                purpose_match = civil_criminal_regex.search(case_number)
                if purpose_match:
                    tag = purpose_match.group(0).lower()
                    if "cv" in tag:
                        purpose = "civil"
                    elif "cr" in tag:
                        purpose = "criminal"

                parsed_rows.append({
                    "Judge": judge_name,
                    "Date": current_date,
                    "Time": time_part,
                    "CaseNumber": case_number,
                    "Plaintiff": plaintiff,
                    "Defendant": defendant,
                    "HearingType": current_hearing_type,
                    "Purpose": purpose
                })

# Save to TSV
df = pd.DataFrame(parsed_rows)
output_path = "calendar_output.tsv"
df.to_csv(output_path, sep="\t", index=False)
print(f"✅ Done. Parsed {len(df)} rows and saved to {output_path}")
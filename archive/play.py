from bs4 import BeautifulSoup

with open("all_calendars.txt", "r", encoding="utf-8") as file:
    html = file.read()

soup = BeautifulSoup(html, "html.parser")
calendar_tables = soup.find_all("table", class_="Calendar")

print(f"🧪 Found {len(calendar_tables)} tables in the file.")

for i, table in enumerate(calendar_tables):
    lines = [td.get_text(" ", strip=True) for td in table.find_all("td") if td.get_text(strip=True)]
    print(f"\n📄 Table {i+1} ({len(lines)} lines):")
    for line in lines:
        print("•", line)
    
    if i == 2:  # Just print the first 3 tables
        break

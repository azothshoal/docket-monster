import os
import re

INPUT_FILE = "all_calendars.txt"
OUTPUT_DIR = "calendar_chunks"
CHUNKS = 10  # Adjust number of desired chunks

# Create output directory if it doesn't exist
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Read entire file
with open(INPUT_FILE, "r", encoding="utf-8") as f:
    text = f.read()

# Split on case-insensitive </table> closing tag
table_chunks = re.split(r"</table>", text, flags=re.IGNORECASE)
table_chunks = [chunk.strip() + "\n</TABLE>" for chunk in table_chunks if chunk.strip()]

# Safety check
if len(table_chunks) < CHUNKS:
    print(f"⚠️ Only found {len(table_chunks)} tables. Reducing chunk count to match.")
    CHUNKS = len(table_chunks)

# Calculate chunk size
chunk_size = len(table_chunks) // CHUNKS + (len(table_chunks) % CHUNKS > 0)

# Write chunks to files
for i in range(0, len(table_chunks), chunk_size):
    chunk_number = (i // chunk_size) + 1
    filename = f"calendar_chunk_{chunk_number}.txt"
    output_path = os.path.join(OUTPUT_DIR, filename)
    chunk_tables = table_chunks[i:i + chunk_size]

    with open(output_path, "w", encoding="utf-8") as out_file:
        out_file.write("\n\n".join(chunk_tables))

    print(f"✅ Wrote {filename} with {len(chunk_tables)} tables")

import os
import requests
import time
import csv
from bs4 import BeautifulSoup
import pandas as pd
import re
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
load_dotenv()

# Configure API key for Google Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Direct calendar URLs and their associated judge names
CALENDAR_URLS = [
    {"judge": "Judge William Alsup", "url": "https://apps.cand.uscourts.gov/CEO/cfd.aspx?7137"},
    # Add more judges with their respective IDs
    # {"judge": "Judge Edward Chen", "url": "https://apps.cand.uscourts.gov/CEO/cfd.aspx?7XXX"},
    # {"judge": "Judge Laurel Beeler", "url": "https://apps.cand.uscourts.gov/CEO/cfd.aspx?7XXX"},
]

def extract_calendar_from_direct_url(judge_info):
    """Extract calendar data from direct calendar URL"""
    print(f"Processing calendar for {judge_info['judge']}...")
    
    try:
        # Add headers to mimic a browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://apps.cand.uscourts.gov/'
        }
        
        response = requests.get(judge_info['url'], headers=headers, timeout=30)
        if response.status_code != 200:
            print(f"Error: Received status code {response.status_code}")
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find the main table with calendar data
        # Based on the HTML structure in the link you shared
        hearings = []
        
        # Process the calendar date by date
        current_date = None
        current_time = None
        
        # Look through all rows in the table
        for row in soup.find_all(['tr', 'td']):
            # Check if this row has a date (usually bold or has specific formatting)
            date_element = row.find('b') or row.find('strong')
            if date_element and re.search(r'\w+day,\s+\w+\s+\d+\s+20\d\d', date_element.text):
                current_date = date_element.text.strip()
                continue
            
            # Check for time (usually at the start of hearings)
            time_match = re.search(r'(\d{1,2}:\d{2}[AP]M)', row.text) if row.text else None
            if time_match:
                current_time = time_match.group(1)
                continue
            
            # Check for case information
            case_match = re.search(r'(\d:\d{2}[-\w]+-\w+)', row.text) if row.text else None
            if case_match and current_date and current_time:
                case_number = case_match.group(1)
                
                # Try to extract parties from the text
                text = row.text.strip()
                parts = text.split(case_number, 1)
                if len(parts) > 1:
                    remainder = parts[1].strip()
                    
                    # Try to separate parties and hearing type
                    if ' v. ' in remainder:
                        party_info = remainder.split(' v. ')
                        party1 = party_info[0].strip()
                        remaining = party_info[1].strip()
                        
                        # Further split to get party2 and hearing_type
                        motion_keywords = ['Motion', 'Conference', 'Hearing', 'Status', 'Trial']
                        split_point = -1
                        
                        for keyword in motion_keywords:
                            if keyword in remaining:
                                split_point = remaining.find(keyword)
                                break
                        
                        if split_point > 0:
                            party2 = remaining[:split_point].strip()
                            hearing_type = remaining[split_point:].strip()
                        else:
                            party2 = remaining
                            hearing_type = ""
                    else:
                        # If no "v." found, make best guess at parsing
                        party1 = "USA" if remainder.startswith("USA") else ""
                        party2 = remainder.replace("USA v. ", "").split("Motion")[0].strip() if party1 else remainder
                        
                        # Extract hearing type from remaining text
                        if "Motion" in remainder:
                            hearing_type = remainder[remainder.find("Motion"):].strip()
                        elif "Conference" in remainder:
                            hearing_type = remainder[remainder.find("Conference"):].strip()
                        elif "Hearing" in remainder:
                            hearing_type = remainder[remainder.find("Hearing"):].strip()
                        elif "Trial" in remainder:
                            hearing_type = remainder[remainder.find("Trial"):].strip()
                        else:
                            hearing_type = ""
                    
                    hearing = {
                        'judge_name': judge_info['judge'],
                        'location': 'San Francisco',  # Default, adjust if location is in the page
                        'date': current_date,
                        'time': current_time,
                        'case_number': case_number,
                        'party1': party1,
                        'party2': party2,
                        'hearing_type': hearing_type,
                        'hearing_details': ''
                    }
                    hearings.append(hearing)
        
        print(f"✓ Extracted {len(hearings)} hearings")
        return hearings
    except Exception as e:
        print(f"✗ Error extracting data: {e}")
        return []

def enhance_data_with_gemini(hearings_batch):
    """Use Gemini to enhance and clean up the extracted data"""
    if not hearings_batch:
        return []
    
    try:
        # Convert the batch to JSON for easier handling
        import json
        hearings_json = json.dumps(hearings_batch, indent=2)
        
        model = genai.GenerativeModel('gemini-2.0-pro')
        
        prompt = f"""
        Here is a batch of court hearing data in JSON format:
        
        {hearings_json}
        
        For each hearing entry, please:
        
        1. Clean up and normalize any inconsistent data
        2. For the "hearing_type" field, identify specific motion types like:
           - Motion for Summary Judgment
           - Motion to Dismiss
           - Motion for Preliminary Injunction
           - Status Conference
           - Case Management Conference
           - etc.
        3. For the "hearing_details" field, add any additional context or purpose information
        
        Return the enhanced data as a clean JSON array with the same structure but improved values.
        """
        
        response = model.generate_content(prompt)
        
        # Extract JSON from the response
        text = response.text
        json_match = re.search(r'```(?:json)?\s*(\[[\s\S]*?\])\s*```', text)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = text
        
        # Parse the enhanced data
        enhanced_data = json.loads(json_str)
        print(f"✓ Successfully enhanced {len(enhanced_data)} entries")
        
        return enhanced_data
    except Exception as e:
        print(f"✗ Error enhancing data: {e}")
        return hearings_batch  # Return original data if enhancement fails

def main():
    all_hearing_data = []
    
    # Process each judge's calendar
    for judge_info in CALENDAR_URLS:
        hearings = extract_calendar_from_direct_url(judge_info)
        
        # Process in batches of 50 hearings to avoid token limits
        batch_size = 50
        for i in range(0, len(hearings), batch_size):
            batch = hearings[i:i+batch_size]
            if batch:
                enhanced_batch = enhance_data_with_gemini(batch)
                all_hearing_data.extend(enhanced_batch)
        
        # Add a small delay to avoid overwhelming the server
        time.sleep(2)
    
    # Save all data to CSV
    if all_hearing_data:
        df = pd.DataFrame(all_hearing_data)
        df.to_csv("calendar_data.csv", index=False)
        print(f"✓ Combined data saved to calendar_data.csv")
    else:
        print("No data extracted.")

if __name__ == "__main__":
    main()
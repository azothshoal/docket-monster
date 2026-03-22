import dotenv from 'dotenv';
import path from 'path';
import fs from 'fs';
import { GoogleGenerativeAI } from '@google/generative-ai';

const envPath = path.resolve(process.cwd(), '.env');
dotenv.config({ path: envPath });

async function processCalendarPDF(pdfPath: string): Promise<void> {
  // Validate environment variables
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    throw new Error("GEMINI_API_KEY is not set in the environment variables.");
  }
  console.log("API key found ✓");

  // Check if the PDF file exists
  if (!fs.existsSync(pdfPath)) {
    throw new Error(`PDF file not found at: ${pdfPath}`);
  }
  console.log(`PDF file found at: ${pdfPath} ✓`);

  try {
    // Read the PDF file as binary data
    const pdfData = fs.readFileSync(pdfPath);
    console.log(`Successfully read PDF file (${pdfData.length} bytes) ✓`);
    
    // Dynamically calculate the current week based on execution date
    const currentDate = new Date();
    const startOfWeek = new Date(currentDate);
    startOfWeek.setDate(currentDate.getDate() - currentDate.getDay()); // Sunday of current week
    startOfWeek.setHours(0, 0, 0, 0); // Start of day

    const endOfWeek = new Date(startOfWeek);
    endOfWeek.setDate(startOfWeek.getDate() + 6); // Saturday of current week
    endOfWeek.setHours(23, 59, 59, 999); // End of day

    // Format dates in multiple formats for clarity
    const formatDateFull = (date: Date): string => {
      return date.toLocaleDateString('en-US', { 
        weekday: 'long', 
        month: 'long', 
        day: 'numeric', 
        year: 'numeric' 
      });
    };

    const formatDateCompact = (date: Date): string => {
      return date.toLocaleDateString('en-US', { 
        month: 'short', 
        day: 'numeric', 
        year: 'numeric' 
      });
    };

    const weekdayNames = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
    const todayName = weekdayNames[currentDate.getDay()];

    const startDateFull = formatDateFull(startOfWeek);
    const endDateFull = formatDateFull(endOfWeek);
    const startDateCompact = formatDateCompact(startOfWeek);
    const endDateCompact = formatDateCompact(endOfWeek);
    const todayFull = formatDateFull(currentDate);

    console.log(`Today is ${todayFull}`);
    console.log(`Filtering for current week: ${startDateFull} to ${endDateFull}`);
    
    // Construct prompt for Gemini with clear date filtering logic
    const prompt = `
    ***CRITICAL DATE FILTERING REQUIREMENT***
    TODAY IS ${todayName.toUpperCase()}, ${todayFull.toUpperCase()}.
    CURRENT WEEK: ${startDateFull.toUpperCase()} TO ${endDateFull.toUpperCase()}

    I'm sending you a court calendar PDF. Extract ONLY hearings that occur within the CURRENT WEEK:
    FROM: ${startDateCompact} (Start of current week)
    TO: ${endDateCompact} (End of current week)

    DATE FILTERING RULES:
    - ANY hearing with a date BEFORE ${startDateCompact} must be EXCLUDED
    - ANY hearing with a date AFTER ${endDateCompact} must be EXCLUDED
    - ONLY include hearings where the date falls WITHIN the range ${startDateCompact} to ${endDateCompact} (inclusive)

    For each hearing that falls within the current week, extract:
    1. Judge name
    2. Location (assume San Francisco if not specified)
    3. Date
    4. Time
    5. Case number
    6. Party 1 (plaintiff/prosecutor)
    7. Party 2 (defendant/respondent)
    8. Hearing type (Civil/Criminal based on case number)
    9. Purpose of the hearing (if determinable)

    OUTPUT FORMAT:
    - Create a valid TSV with headers: judge_name\tlocation\tdate\ttime\tcase_number\tparty1\tparty2\thearing_details\tHearingType\tPurpose
    - Use TABS, not commas, as separators between fields
    - You can freely use commas within field values since fields are separated by tabs

    EXAMPLE DATE COMPARISON:
    - If a hearing is scheduled for a date before ${startDateCompact}, DO NOT include it
    - If a hearing is scheduled for a date on or after ${startDateCompact} AND on or before ${endDateCompact}, INCLUDE it
    - If a hearing is scheduled for a date after ${endDateCompact}, DO NOT include it

    CRITICAL: Double-check all dates to ensure ONLY hearings from THIS WEEK (${startDateCompact} to ${endDateCompact}) are included.
    `;

    // Initialize Gemini model with the latest version
    const genAI = new GoogleGenerativeAI(apiKey);
    const model = genAI.getGenerativeModel({ 
      model: "gemini-1.5-flash",  // Updated to use recommended model
      generationConfig: {
        maxOutputTokens: 8192,
        temperature: 0.1,
      }
    });
    
    console.log("Sending PDF to Gemini...");
    
    // Convert the PDF to base64
    const pdfBase64 = pdfData.toString('base64');
    
    // Use the FilesPart approach for file handling
    const result = await model.generateContent({
      contents: [
        {
          parts: [
            { text: prompt },
            {
              inlineData: {
                mimeType: "application/pdf",
                data: pdfBase64
              }
            }
          ]
        }
      ]
    });
    
    const text = result.response.text();
    
    // Remove any markdown formatting or extra text the model might add
    let cleanedText = text.replace(/```csv\s*|\s*```/g, '');
    
    // Save the extracted data as TSV
    const outputPath = path.join(process.cwd(), 'calendar_data_from_pdf.tsv');
    fs.writeFileSync(outputPath, cleanedText);
    console.log(`Extracted data saved to: ${outputPath} ✓`);
    
    // Preview the first few lines
    const previewLines = cleanedText.split('\n').slice(0, 5).join('\n');
    console.log("\nPreview of extracted data:");
    console.log(previewLines);
    
  } catch (error) {
    console.error("Error processing PDF with Gemini:", error);
    throw error;
  }
}

(async () => {
  try {
    const pdfPath = path.join(process.cwd(), 'Example2.pdf');
    await processCalendarPDF(pdfPath);
  } catch (error) {
    console.error("Failed to process PDF:", error);
    process.exit(1);
  }
})();
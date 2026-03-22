import fs from "fs";
import path from "path";
import { GoogleGenerativeAI } from "@google/generative-ai";
import dotenv from "dotenv";
dotenv.config();

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY!);
const delay = (ms: number) => new Promise((res) => setTimeout(res, ms));

const parseChunkToCSV = async (text: string, chunkName: string): Promise<string[]> => {
  const model = genAI.getGenerativeModel({ model: "gemini-1.5-pro" });

  const prompt = `You are helping extract structured data from court calendar files for the Northern District of California.

The contents of this file are below. Your job is to output only a CSV with these column headers:
Judge, Location, Date, Time, CaseNumber, Plaintiff, Defendant, HearingType, Purpose

Only return valid calendar rows. Do not return the header multiple times. Do not return extra prose. Do not make up any rows if the file is empty.

If a field like Defendant or CaseNumber is missing, leave it blank. Do not hallucinate. CaseNumbers may sometimes have an extra trailing dash and number, like 3:13-cr-00794-WHA-1. This is valid.

Infer whether Purpose is "criminal" or "civil" based on the CaseNumber: if it contains '-cr-', it's criminal. If it contains '-cv-', it's civil. If you can't tell, leave it blank.

If HearingType contains multiple lines, use a semicolon between them (not line breaks). If HearingDetails is the same as HearingType, just include one HearingType column. Consolidate them if both exist.

This content came from a file labeled: ${chunkName}

--- File contents ---
${text}`;

  try {
    const result = await model.generateContent([prompt]);
    const response = await result.response;
    const csv = response.text().trim();
    return csv.split("\n").filter((line) => line.includes(",") || line.includes("\t"));
  } catch (error: any) {
    console.error(`❌ Failed on ${chunkName}:`, error);
    return [];
  }
};

const processCalendarChunks = async () => {
  const chunksDir = path.join(process.cwd(), "calendar_chunks");
  const files = fs.readdirSync(chunksDir).filter((file) => file.endsWith(".txt"));

  let csvData = "Judge\tLocation\tDate\tTime\tCaseNumber\tPlaintiff\tDefendant\tHearingType\tPurpose\n";

  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    const fullPath = path.join(chunksDir, file);
    console.log(`🟡 Processing ${file} (${i + 1}/${files.length})...`);

    const text = fs.readFileSync(fullPath, "utf-8");
    const parsedLines = await parseChunkToCSV(text, file);

    for (const line of parsedLines) {
      if (!line.toLowerCase().startsWith("judge")) {
        csvData += `${line}\n`;
      }
    }

    if (i < files.length - 1) {
      console.log(`⏳ Waiting 30 seconds before next chunk...`);
      await delay(30000);
    }
  }

  const outputPath = path.join(process.cwd(), "onlycals.csv");
  fs.writeFileSync(outputPath, csvData);
  console.log(`✅ CSV saved to ${outputPath}`);
};

processCalendarChunks();

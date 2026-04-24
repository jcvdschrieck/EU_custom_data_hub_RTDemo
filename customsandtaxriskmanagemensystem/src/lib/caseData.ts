// Case-based data model: orders grouped into cases by seller, country, declared VAT category, similar products

export interface Order {
  id: string;
  salesOrderId: string;
  productDescription: string;
  itemValue: number;
  riskScore: number;
  date: string;
  vatPercent: number;
  vatValue: number;
  // VAT product subcategory code from the transaction (e.g. EL-07).
  // Nullable on historical / seeded cases that pre-date the field.
  vatSubcategoryCode?: string | null;
}

export interface ActivityEntry {
  id: string;
  timestamp: string;
  type: "action" | "status_update" | "risk_update" | "note";
  description: string;
  by: string;
}

export interface CaseActivities {
  [caseId: string]: ActivityEntry[];
}

export type CaseStatus =
  | "New"
  | "Under Review by Customs"
  | "Under Review by Tax"
  | "Reviewed by Tax"
  | "AI Investigation in Progress"
  | "Requested Input by Deemed Importer"
  | "Closed";

export type AISuggestedAction = "Recommend Control" | "Recommend Release" | "Submit for Tax Review" | "Request Input from Deemed Importer";

export type ActionTaken = "Recommend Control" | "Recommend Release" | "Submitted for Tax Review" | "Input Requested";

export interface Case {
  id: string;
  caseName: string;
  orders: Order[];
  seller: string;
  declaredCategory: string;
  aiSuggestedCategory: string;
  countryOfOrigin: string;
  countryOfDestination: string;
  riskScore: number;
  riskLevel: "High" | "Medium" | "Low";
  status: CaseStatus;
  aiSuggestedAction: AISuggestedAction;
  actionTaken?: ActionTaken;
  closedDate?: string;
  notes?: string;
  // Per-engine risk scores (0-1, from backend assessment outcomes)
  engineVatRatio?: number;
  engineMlWatchlist?: number;
  engineIeSellerWatchlist?: number;
  engineDescriptionVagueness?: number;
  // AI agent analysis (from LLM-based VAT fraud detection)
  aiAnalysis?: string | null;
  // Legislation references cited by the agent (populated on the case
  // when the VAT Fraud Detection agent returns). Displayed inline in
  // the Tax Authority VAT Assessment Summary.
  aiLegislationRefs?: Array<{
    ref?: string;
    source?: string;
    section?: string;
    url?: string;
    page?: number | string | null;
    paragraph?: string | null;
  }> | null;
  // Slide-1 customs recommendation rationale (computed on backend in
  // _compute_customs_recommendation — matches aiSuggestedAction). Same
  // string powers the list-view tooltip and the detail-view AI panel.
  aiCustomsAnalysis?: string | null;
  // Slide-1 tax recommendation + rationale (computed on backend in
  // _compute_tax_recommendation). Used by the Tax Authority detail view.
  aiSuggestedTaxAction?: "Confirm Risk" | "No/Limited Risk" | "AI Uncertain" | null;
  aiTaxAnalysis?: string | null;
  // Communication log (from backend — includes AI agent entries)
  communication?: Array<{ date: string; from: string; action: string; message: string }>;
}

function getAISuggestedAction(riskScore: number, riskLevel: string): AISuggestedAction {
  if (riskScore >= 85) return "Recommend Control";
  if (riskScore >= 70) return "Submit for Tax Review";
  if (riskScore >= 55) return "Request Input from Deemed Importer";
  return "Recommend Release";
}

function getRiskLevel(score: number): "High" | "Medium" | "Low" {
  if (score >= 65) return "High";
  if (score >= 40) return "Medium";
  return "Low";
}

// Ongoing (non-closed) cases
export const mockCases: Case[] = [
  {
    id: "C-26-001",
    caseName: "Wireless Earbuds misclassified as Educational Material",
    orders: [
      { id: "O-70482", salesOrderId: "SO-26-70482", productDescription: "Wireless Earbuds — Bluetooth 5.3", itemValue: 145, riskScore: 85, date: "2026-04-06", vatPercent: 0, vatValue: 0 },
      { id: "O-70490", salesOrderId: "SO-26-70490", productDescription: "Wireless Earbuds — Noise Cancelling", itemValue: 142, riskScore: 83, date: "2026-04-06", vatPercent: 0, vatValue: 0 },
      { id: "O-70501", salesOrderId: "SO-26-70501", productDescription: "Wireless Earbuds — Sports Model", itemValue: 98, riskScore: 81, date: "2026-04-05", vatPercent: 0, vatValue: 0 },
    ],
    seller: "ShenZhen TechGoods Ltd",
    declaredCategory: "Educational Material",
    aiSuggestedCategory: "Consumer Electronics",
    countryOfOrigin: "CN",
    countryOfDestination: "IE",
    riskScore: 88,
    riskLevel: "High",
    status: "New",
    aiSuggestedAction: "Recommend Control",
  },
  {
    id: "C-26-002",
    caseName: "Smart Watches declared as Educational Material",
    orders: [
      { id: "O-70479", salesOrderId: "SO-26-70479", productDescription: "Smart Watch — Fitness Tracker Model", itemValue: 120, riskScore: 82, date: "2026-04-06", vatPercent: 0, vatValue: 0 },
      { id: "O-70485", salesOrderId: "SO-26-70485", productDescription: "Smart Watch — GPS Sports Edition", itemValue: 189, riskScore: 84, date: "2026-04-05", vatPercent: 0, vatValue: 0 },
    ],
    seller: "ShenZhen TechGoods Ltd",
    declaredCategory: "Educational Material",
    aiSuggestedCategory: "Consumer Electronics",
    countryOfOrigin: "CN",
    countryOfDestination: "IE",
    riskScore: 85,
    riskLevel: "High",
    status: "New",
    aiSuggestedAction: "Recommend Control",
  },
  {
    id: "C-26-003",
    caseName: "Electric Brain Game Console — Education or Electronics?",
    orders: [
      { id: "O-70510", salesOrderId: "SO-26-70510", productDescription: "Electric Brain Game Console — Memory Training", itemValue: 79, riskScore: 76, date: "2026-04-05", vatPercent: 0, vatValue: 0 },
      { id: "O-70518", salesOrderId: "SO-26-70518", productDescription: "Electric Brain Game Console — Logic Puzzles", itemValue: 85, riskScore: 74, date: "2026-04-04", vatPercent: 0, vatValue: 0 },
      { id: "O-70525", salesOrderId: "SO-26-70525", productDescription: "Electric Brain Game Console — Math Challenge", itemValue: 72, riskScore: 73, date: "2026-04-04", vatPercent: 0, vatValue: 0 },
      { id: "O-70530", salesOrderId: "SO-26-70530", productDescription: "Electric Brain Game Console — Kids Edition", itemValue: 65, riskScore: 71, date: "2026-04-03", vatPercent: 0, vatValue: 0 },
    ],
    seller: "Guangzhou DigitalMart Co.",
    declaredCategory: "Educational Material",
    aiSuggestedCategory: "Consumer Electronics",
    countryOfOrigin: "CN",
    countryOfDestination: "IE",
    riskScore: 76,
    riskLevel: "High",
    status: "New",
    aiSuggestedAction: "Submit for Tax Review",
  },
  {
    id: "C-26-004",
    caseName: "Drone Cameras classified as Imaging Equipment",
    orders: [
      { id: "O-70465", salesOrderId: "SO-26-70465", productDescription: "Drone Camera — DJI Compatible 4K", itemValue: 145, riskScore: 84, date: "2026-04-05", vatPercent: 0, vatValue: 0 },
      { id: "O-70472", salesOrderId: "SO-26-70472", productDescription: "Drone Camera — Aerial Photography Pro", itemValue: 148, riskScore: 86, date: "2026-04-04", vatPercent: 0, vatValue: 0 },
    ],
    seller: "HK Aerial Systems Ltd",
    declaredCategory: "Imaging & Drones",
    aiSuggestedCategory: "Consumer Electronics",
    countryOfOrigin: "HK",
    countryOfDestination: "IE",
    riskScore: 84,
    riskLevel: "High",
    status: "New",
    aiSuggestedAction: "Submit for Tax Review",
  },
  {
    id: "C-26-005",
    caseName: "Digital Course Reader — Education or Consumer Electronics?",
    orders: [
      { id: "O-70540", salesOrderId: "SO-26-70540", productDescription: "Digital Course Reader — E-Ink 10\"", itemValue: 145, riskScore: 68, date: "2026-04-03", vatPercent: 0, vatValue: 0 },
      { id: "O-70545", salesOrderId: "SO-26-70545", productDescription: "Digital Course Reader — Student Edition", itemValue: 139, riskScore: 66, date: "2026-04-02", vatPercent: 0, vatValue: 0 },
      { id: "O-70552", salesOrderId: "SO-26-70552", productDescription: "Digital Course Reader — Backlit Model", itemValue: 148, riskScore: 70, date: "2026-04-02", vatPercent: 0, vatValue: 0 },
    ],
    seller: "Taiwan ConnectPro Inc.",
    declaredCategory: "Educational Material",
    aiSuggestedCategory: "Consumer Electronics",
    countryOfOrigin: "TW",
    countryOfDestination: "IE",
    riskScore: 68,
    riskLevel: "High",
    status: "New",
    aiSuggestedAction: "Request Input from Deemed Importer",
  },
  {
    id: "C-26-006",
    caseName: "Headphones Classroom Set — Education or Audio?",
    orders: [
      { id: "O-70560", salesOrderId: "SO-26-70560", productDescription: "Headphones Classroom Set — 30 Pack", itemValue: 149, riskScore: 72, date: "2026-04-03", vatPercent: 0, vatValue: 0 },
      { id: "O-70567", salesOrderId: "SO-26-70567", productDescription: "Headphones Classroom Set — 15 Pack w/ Case", itemValue: 145, riskScore: 69, date: "2026-04-02", vatPercent: 0, vatValue: 0 },
    ],
    seller: "ShenZhen TechGoods Ltd",
    declaredCategory: "Educational Material",
    aiSuggestedCategory: "Computer Accessories",
    countryOfOrigin: "CN",
    countryOfDestination: "IE",
    riskScore: 71,
    riskLevel: "High",
    status: "New",
    aiSuggestedAction: "Submit for Tax Review",
  },
  {
    id: "C-26-007",
    caseName: "Barbie Dolls declared as Educational Toys",
    orders: [
      { id: "O-70580", salesOrderId: "SO-26-70580", productDescription: "Barbie Dreamhouse — Deluxe Edition", itemValue: 145, riskScore: 62, date: "2026-04-01", vatPercent: 0, vatValue: 0 },
      { id: "O-70585", salesOrderId: "SO-26-70585", productDescription: "Barbie Tennis Doll — Sports Collection", itemValue: 29, riskScore: 58, date: "2026-04-01", vatPercent: 0, vatValue: 0 },
      { id: "O-70590", salesOrderId: "SO-26-70590", productDescription: "Barbie Classic Doll — Vintage Edition", itemValue: 35, riskScore: 60, date: "2026-03-31", vatPercent: 0, vatValue: 0 },
    ],
    seller: "Guangzhou DigitalMart Co.",
    declaredCategory: "Educational Material",
    aiSuggestedCategory: "Toys & Games",
    countryOfOrigin: "CN",
    countryOfDestination: "IE",
    riskScore: 62,
    riskLevel: "Medium",
    status: "New",
    aiSuggestedAction: "Request Input from Deemed Importer",
  },
  {
    id: "C-26-008",
    caseName: "Psychology Textbooks — Legitimate Educational?",
    orders: [
      { id: "O-70600", salesOrderId: "SO-26-70600", productDescription: "Psychology 101 — Student Edition", itemValue: 45, riskScore: 52, date: "2026-03-31", vatPercent: 0, vatValue: 0 },
      { id: "O-70605", salesOrderId: "SO-26-70605", productDescription: "Basic Psychology Course Book — 3rd Ed.", itemValue: 38, riskScore: 50, date: "2026-03-30", vatPercent: 0, vatValue: 0 },
    ],
    seller: "Seoul BeautyTech Co.",
    declaredCategory: "Educational Material",
    aiSuggestedCategory: "Educational Material",
    countryOfOrigin: "KR",
    countryOfDestination: "IE",
    riskScore: 52,
    riskLevel: "Medium",
    status: "New",
    aiSuggestedAction: "Recommend Release",
  },
  {
    id: "C-26-009",
    caseName: "iPhone Models declared as Phone Accessories",
    orders: [
      { id: "O-70620", salesOrderId: "SO-26-70620", productDescription: "iPhone 13 (128 GB) Black", itemValue: 149, riskScore: 91, date: "2026-04-06", vatPercent: 0, vatValue: 0 },
      { id: "O-70625", salesOrderId: "SO-26-70625", productDescription: "iPhone 14 (256GB) White", itemValue: 148, riskScore: 93, date: "2026-04-05", vatPercent: 0, vatValue: 0 },
      { id: "O-70630", salesOrderId: "SO-26-70630", productDescription: "iPhone 9 (64gb) White", itemValue: 139, riskScore: 89, date: "2026-04-04", vatPercent: 0, vatValue: 0 },
    ],
    seller: "ShenZhen TechGoods Ltd",
    declaredCategory: "Phone Accessories",
    aiSuggestedCategory: "Consumer Electronics",
    countryOfOrigin: "CN",
    countryOfDestination: "IE",
    riskScore: 92,
    riskLevel: "High",
    status: "New",
    aiSuggestedAction: "Recommend Control",
  },
  {
    id: "C-26-010",
    caseName: "LED Face Masks as Beauty Devices",
    orders: [
      { id: "O-70640", salesOrderId: "SO-26-70640", productDescription: "LED Face Mask — Anti-Aging Therapy", itemValue: 89, riskScore: 55, date: "2026-04-03", vatPercent: 0, vatValue: 0 },
      { id: "O-70645", salesOrderId: "SO-26-70645", productDescription: "LED Face Mask — Acne Treatment Model", itemValue: 95, riskScore: 53, date: "2026-04-02", vatPercent: 0, vatValue: 0 },
    ],
    seller: "Seoul BeautyTech Co.",
    declaredCategory: "Beauty & Personal Care",
    aiSuggestedCategory: "Consumer Electronics",
    countryOfOrigin: "KR",
    countryOfDestination: "IE",
    riskScore: 55,
    riskLevel: "Medium",
    status: "New",
    aiSuggestedAction: "Request Input from Deemed Importer",
  },
  {
    id: "C-26-011",
    caseName: "Fitness Trackers declared as Wearables",
    orders: [
      { id: "O-70660", salesOrderId: "SO-26-70660", productDescription: "Fitness Tracker — Wristband HR Monitor", itemValue: 49, riskScore: 81, date: "2026-04-02", vatPercent: 0, vatValue: 0 },
      { id: "O-70665", salesOrderId: "SO-26-70665", productDescription: "Fitness Tracker — GPS Running Watch", itemValue: 129, riskScore: 79, date: "2026-04-01", vatPercent: 0, vatValue: 0 },
      { id: "O-70670", salesOrderId: "SO-26-70670", productDescription: "Fitness Tracker — Sleep & Activity Band", itemValue: 39, riskScore: 77, date: "2026-03-31", vatPercent: 0, vatValue: 0 },
    ],
    seller: "ShenZhen TechGoods Ltd",
    declaredCategory: "Wearables",
    aiSuggestedCategory: "Consumer Electronics",
    countryOfOrigin: "CN",
    countryOfDestination: "IE",
    riskScore: 80,
    riskLevel: "High",
    status: "New",
    aiSuggestedAction: "Submit for Tax Review",
  },
  {
    id: "C-26-012",
    caseName: "Interactive Learning Tablets — Consumer or Educational?",
    orders: [
      { id: "O-70680", salesOrderId: "SO-26-70680", productDescription: "Interactive Learning Tablet — Kids 7\"", itemValue: 119, riskScore: 64, date: "2026-04-01", vatPercent: 0, vatValue: 0 },
      { id: "O-70685", salesOrderId: "SO-26-70685", productDescription: "Interactive Learning Tablet — Pre-School", itemValue: 99, riskScore: 61, date: "2026-03-31", vatPercent: 0, vatValue: 0 },
    ],
    seller: "Guangzhou DigitalMart Co.",
    declaredCategory: "Educational Material",
    aiSuggestedCategory: "Consumer Electronics",
    countryOfOrigin: "CN",
    countryOfDestination: "IE",
    riskScore: 63,
    riskLevel: "Medium",
    status: "New",
    aiSuggestedAction: "Request Input from Deemed Importer",
  },
  {
    id: "C-26-013",
    caseName: "Power Banks — Underdeclared Value",
    orders: [
      { id: "O-70700", salesOrderId: "SO-26-70700", productDescription: "Power Bank — 20000mAh Fast Charge", itemValue: 35, riskScore: 79, date: "2026-03-30", vatPercent: 0, vatValue: 0 },
      { id: "O-70705", salesOrderId: "SO-26-70705", productDescription: "Power Bank — 10000mAh Slim", itemValue: 22, riskScore: 76, date: "2026-03-29", vatPercent: 0, vatValue: 0 },
    ],
    seller: "Bangkok PowerTech Co.",
    declaredCategory: "Power & Charging",
    aiSuggestedCategory: "Consumer Electronics",
    countryOfOrigin: "TH",
    countryOfDestination: "IE",
    riskScore: 78,
    riskLevel: "High",
    status: "New",
    aiSuggestedAction: "Submit for Tax Review",
  },
  {
    id: "C-26-014",
    caseName: "Vacuum Cleaners as Home Appliances",
    orders: [
      { id: "O-70720", salesOrderId: "SO-26-70720", productDescription: "Vacuum Cleaner — Handheld Cordless Pro", itemValue: 145, riskScore: 74, date: "2026-04-02", vatPercent: 0, vatValue: 0 },
      { id: "O-70725", salesOrderId: "SO-26-70725", productDescription: "Vacuum Cleaner — Handheld Cordless Lite", itemValue: 129, riskScore: 72, date: "2026-04-01", vatPercent: 0, vatValue: 0 },
    ],
    seller: "Hanoi HomeAppliance JSC",
    declaredCategory: "Home Appliances",
    aiSuggestedCategory: "Consumer Electronics",
    countryOfOrigin: "VN",
    countryOfDestination: "IE",
    riskScore: 74,
    riskLevel: "High",
    status: "New",
    aiSuggestedAction: "Submit for Tax Review",
  },
  {
    id: "C-26-015",
    caseName: "Coding Robots declared as Educational Material",
    orders: [
      { id: "O-70740", salesOrderId: "SO-26-70740", productDescription: "Coding Robot Kit — STEM Education", itemValue: 149, riskScore: 67, date: "2026-03-30", vatPercent: 0, vatValue: 0 },
      { id: "O-70745", salesOrderId: "SO-26-70745", productDescription: "Coding Robot Kit — Beginner Pack", itemValue: 89, riskScore: 65, date: "2026-03-29", vatPercent: 0, vatValue: 0 },
      { id: "O-70750", salesOrderId: "SO-26-70750", productDescription: "Coding Robot Kit — Advanced Sensors", itemValue: 145, riskScore: 69, date: "2026-03-28", vatPercent: 0, vatValue: 0 },
    ],
    seller: "ShenZhen TechGoods Ltd",
    declaredCategory: "Educational Material",
    aiSuggestedCategory: "Consumer Electronics",
    countryOfOrigin: "CN",
    countryOfDestination: "IE",
    riskScore: 67,
    riskLevel: "High",
    status: "New",
    aiSuggestedAction: "Request Input from Deemed Importer",
  },
];

// Closed cases (separate)
export const mockClosedCases: Case[] = [];

// Helper: all cases combined for stat calculations
export const allCases = [...mockCases, ...mockClosedCases];

// ── Live case accessor ─────────────────────────────────────────────────
// Returns backend cases when connected, otherwise mock data.
import { isBackendConnected, getAllBackendCases } from "./backendCaseStore";

export function getLiveCases(): Case[] {
  if (isBackendConnected()) return getAllBackendCases();
  return mockCases;
}

export function getLiveClosedCases(): Case[] {
  if (isBackendConnected()) {
    return getAllBackendCases().filter(c => c.status === "Closed");
  }
  return mockClosedCases;
}

// Generate the two pre-arrival activities every case should start with:
// 1) Risk engine evaluated the orders to a risk score
// 2) Case was created in the system
export function getInitialActivitiesForCase(c: Case): ActivityEntry[] {
  // Earliest order date drives the synthetic timestamps for the initial activities.
  const earliest = c.orders
    .map((o) => o.date)
    .sort()[0] ?? new Date().toISOString().split("T")[0];
  const baseDate = `${earliest} 08:00`;
  const createdDate = `${earliest} 08:05`;
  return [
    {
      id: `init-risk-${c.id}`,
      timestamp: baseDate,
      type: "risk_update",
      description: `Risk engine evaluated orders to score ${c.riskScore} (${c.riskLevel}).`,
      by: "Risk Engine",
    },
    {
      id: `init-created-${c.id}`,
      timestamp: createdDate,
      type: "note",
      description: `Case created with ${c.orders.length} associated orders.`,
      by: "System",
    },
  ];
}

// Mock activity logs per case — auto-generated initial activities for every case.
export const mockActivities: CaseActivities = Object.fromEntries(
  allCases.map((c) => [c.id, getInitialActivitiesForCase(c)])
);

// Mock similar/previous cases for correlation — each seller has multiple historical entries
export const mockPreviousCases = [
  // ShenZhen TechGoods Ltd
  { caseId: "C-25-S01", caseName: "Wireless Earbuds — Bluetooth (prior)", actionTaken: "Recommend Control" as const, riskScore: 88, riskLevel: "High" as const, seller: "ShenZhen TechGoods Ltd", countryOfOrigin: "CN", countryOfDestination: "IE", productDescription: "Wireless Earbuds — Bluetooth", declaredCategory: "Educational Material", aiCategory: "Consumer Electronics" },
  { caseId: "C-25-S02", caseName: "Smart Watches as Educational (prior)", actionTaken: "Recommend Control" as const, riskScore: 84, riskLevel: "High" as const, seller: "ShenZhen TechGoods Ltd", countryOfOrigin: "CN", countryOfDestination: "IE", productDescription: "Smart Watch — Fitness Tracker", declaredCategory: "Educational Material", aiCategory: "Consumer Electronics" },
  { caseId: "C-25-S03", caseName: "Fitness Trackers (prior)", actionTaken: "Recommend Control" as const, riskScore: 81, riskLevel: "High" as const, seller: "ShenZhen TechGoods Ltd", countryOfOrigin: "CN", countryOfDestination: "IE", productDescription: "Fitness Tracker — Wristband", declaredCategory: "Wearables", aiCategory: "Consumer Electronics" },
  { caseId: "C-25-S04", caseName: "Headphones Classroom Set (prior)", actionTaken: "Submitted for Tax Review" as any, riskScore: 70, riskLevel: "High" as const, seller: "ShenZhen TechGoods Ltd", countryOfOrigin: "CN", countryOfDestination: "IE", productDescription: "Headphones Classroom Set", declaredCategory: "Educational Material", aiCategory: "Computer Accessories" },

  // Guangzhou DigitalMart Co.
  { caseId: "C-25-G01", caseName: "Brain Game Console (prior)", actionTaken: "Submitted for Tax Review" as any, riskScore: 75, riskLevel: "High" as const, seller: "Guangzhou DigitalMart Co.", countryOfOrigin: "CN", countryOfDestination: "IE", productDescription: "Electric Brain Game Console", declaredCategory: "Educational Material", aiCategory: "Consumer Electronics" },
  { caseId: "C-25-G02", caseName: "Barbie Dolls (prior)", actionTaken: "Recommend Release" as const, riskScore: 58, riskLevel: "Medium" as const, seller: "Guangzhou DigitalMart Co.", countryOfOrigin: "CN", countryOfDestination: "IE", productDescription: "Barbie Doll — Classic", declaredCategory: "Educational Material", aiCategory: "Toys & Games" },
  { caseId: "C-25-G03", caseName: "Learning Tablets (prior)", actionTaken: "Submitted for Tax Review" as any, riskScore: 64, riskLevel: "Medium" as const, seller: "Guangzhou DigitalMart Co.", countryOfOrigin: "CN", countryOfDestination: "IE", productDescription: "Interactive Learning Tablet", declaredCategory: "Educational Material", aiCategory: "Consumer Electronics" },

  // HK Aerial Systems Ltd
  { caseId: "C-25-H01", caseName: "Drone Cameras (prior)", actionTaken: "Recommend Control" as const, riskScore: 86, riskLevel: "High" as const, seller: "HK Aerial Systems Ltd", countryOfOrigin: "HK", countryOfDestination: "IE", productDescription: "Drone Camera — Aerial 4K", declaredCategory: "Imaging & Drones", aiCategory: "Consumer Electronics" },
  { caseId: "C-25-H02", caseName: "Action Cameras (prior)", actionTaken: "Recommend Control" as const, riskScore: 83, riskLevel: "High" as const, seller: "HK Aerial Systems Ltd", countryOfOrigin: "HK", countryOfDestination: "IE", productDescription: "Action Camera — Waterproof 4K", declaredCategory: "Imaging & Drones", aiCategory: "Consumer Electronics" },
  { caseId: "C-25-H03", caseName: "Drone Accessories (prior)", actionTaken: "Submitted for Tax Review" as any, riskScore: 72, riskLevel: "High" as const, seller: "HK Aerial Systems Ltd", countryOfOrigin: "HK", countryOfDestination: "IE", productDescription: "Drone Camera — Compact", declaredCategory: "Imaging & Drones", aiCategory: "Consumer Electronics" },

  // Taiwan ConnectPro Inc.
  { caseId: "C-25-T01", caseName: "E-Readers (prior)", actionTaken: "Recommend Release" as const, riskScore: 55, riskLevel: "Medium" as const, seller: "Taiwan ConnectPro Inc.", countryOfOrigin: "TW", countryOfDestination: "IE", productDescription: "Digital Course Reader — E-Ink", declaredCategory: "Educational Material", aiCategory: "Educational Material" },
  { caseId: "C-25-T02", caseName: "E-Readers Backlit (prior)", actionTaken: "Submitted for Tax Review" as any, riskScore: 67, riskLevel: "High" as const, seller: "Taiwan ConnectPro Inc.", countryOfOrigin: "TW", countryOfDestination: "IE", productDescription: "Digital Course Reader — Backlit", declaredCategory: "Educational Material", aiCategory: "Consumer Electronics" },
  { caseId: "C-25-T03", caseName: "Student Tablets (prior)", actionTaken: "Recommend Release" as const, riskScore: 52, riskLevel: "Medium" as const, seller: "Taiwan ConnectPro Inc.", countryOfOrigin: "TW", countryOfDestination: "IE", productDescription: "Digital Course Reader — Student", declaredCategory: "Educational Material", aiCategory: "Educational Material" },

  // Seoul BeautyTech Co.
  { caseId: "C-25-K01", caseName: "Psychology Textbooks (prior)", actionTaken: "Recommend Release" as const, riskScore: 48, riskLevel: "Medium" as const, seller: "Seoul BeautyTech Co.", countryOfOrigin: "KR", countryOfDestination: "IE", productDescription: "Psychology 101 — Student", declaredCategory: "Educational Material", aiCategory: "Educational Material" },
  { caseId: "C-25-K02", caseName: "LED Face Masks (prior)", actionTaken: "Recommend Release" as const, riskScore: 53, riskLevel: "Medium" as const, seller: "Seoul BeautyTech Co.", countryOfOrigin: "KR", countryOfDestination: "IE", productDescription: "LED Face Mask — Anti-Aging", declaredCategory: "Beauty & Personal Care", aiCategory: "Consumer Electronics" },
  { caseId: "C-25-K03", caseName: "Course Books (prior)", actionTaken: "Recommend Release" as const, riskScore: 45, riskLevel: "Medium" as const, seller: "Seoul BeautyTech Co.", countryOfOrigin: "KR", countryOfDestination: "IE", productDescription: "Basic Psychology Course Book", declaredCategory: "Educational Material", aiCategory: "Educational Material" },

  // Bangkok PowerTech Co.
  { caseId: "C-25-B01", caseName: "Power Banks (prior)", actionTaken: "Recommend Control" as const, riskScore: 79, riskLevel: "High" as const, seller: "Bangkok PowerTech Co.", countryOfOrigin: "TH", countryOfDestination: "IE", productDescription: "Power Bank — 20000mAh", declaredCategory: "Power & Charging", aiCategory: "Consumer Electronics" },
  { caseId: "C-25-B02", caseName: "Power Banks Slim (prior)", actionTaken: "Submitted for Tax Review" as any, riskScore: 72, riskLevel: "High" as const, seller: "Bangkok PowerTech Co.", countryOfOrigin: "TH", countryOfDestination: "IE", productDescription: "Power Bank — Slim", declaredCategory: "Power & Charging", aiCategory: "Consumer Electronics" },
  { caseId: "C-25-B03", caseName: "Chargers (prior)", actionTaken: "Recommend Control" as const, riskScore: 76, riskLevel: "High" as const, seller: "Bangkok PowerTech Co.", countryOfOrigin: "TH", countryOfDestination: "IE", productDescription: "Power Bank — Fast Charge", declaredCategory: "Power & Charging", aiCategory: "Consumer Electronics" },

  // Hanoi HomeAppliance JSC
  { caseId: "C-25-V01", caseName: "Vacuum Cleaners (prior)", actionTaken: "Submitted for Tax Review" as any, riskScore: 73, riskLevel: "High" as const, seller: "Hanoi HomeAppliance JSC", countryOfOrigin: "VN", countryOfDestination: "IE", productDescription: "Vacuum Cleaner — Handheld Cordless", declaredCategory: "Home Appliances", aiCategory: "Consumer Electronics" },
  { caseId: "C-25-V02", caseName: "Vacuum Cleaners Lite (prior)", actionTaken: "Recommend Release" as const, riskScore: 60, riskLevel: "Medium" as const, seller: "Hanoi HomeAppliance JSC", countryOfOrigin: "VN", countryOfDestination: "IE", productDescription: "Vacuum Cleaner — Lite", declaredCategory: "Home Appliances", aiCategory: "Home Appliances" },
  { caseId: "C-25-V03", caseName: "Cordless Appliances (prior)", actionTaken: "Submitted for Tax Review" as any, riskScore: 70, riskLevel: "High" as const, seller: "Hanoi HomeAppliance JSC", countryOfOrigin: "VN", countryOfDestination: "IE", productDescription: "Vacuum Cleaner — Cordless Pro", declaredCategory: "Home Appliances", aiCategory: "Consumer Electronics" },
];

// Mock correlated cases for "Correlate" tab — similar products with same declared category
export const mockCorrelatedCases = [
  { caseId: "C-26-CR01", caseName: "Bluetooth Headphones as Educational Material", riskScore: 82, riskLevel: "High" as const, seller: "Dongguan AudioTech Ltd", countryOfOrigin: "CN", countryOfDestination: "IE", productDescription: "Bluetooth Headphones — Over-Ear Studio", declaredCategory: "Educational Material", detected: true },
  { caseId: "C-26-CR02", caseName: "Fitness Trackers as Educational Material", riskScore: 79, riskLevel: "High" as const, seller: "ShenZhen WearTech Co.", countryOfOrigin: "CN", countryOfDestination: "DE", productDescription: "Fitness Tracker — Heart Rate Monitor", declaredCategory: "Educational Material", detected: false },
  { caseId: "C-26-CR03", caseName: "Tablet PCs as Educational Material", riskScore: 91, riskLevel: "High" as const, seller: "Shenzhen TabletWorld Ltd", countryOfOrigin: "CN", countryOfDestination: "IE", productDescription: "Tablet PC — 10 inch Android", declaredCategory: "Educational Material", detected: true },
  { caseId: "C-26-CR04", caseName: "Smart Speakers as Educational Material", riskScore: 74, riskLevel: "High" as const, seller: "Guangzhou SmartHome Inc.", countryOfOrigin: "CN", countryOfDestination: "FR", productDescription: "Smart Speaker — Voice Assistant", declaredCategory: "Educational Material", detected: false },
  { caseId: "C-26-CR05", caseName: "Action Cameras as Imaging & Drones", riskScore: 86, riskLevel: "High" as const, seller: "HK Aerial Systems Ltd", countryOfOrigin: "HK", countryOfDestination: "IE", productDescription: "Action Camera — Waterproof 4K", declaredCategory: "Imaging & Drones", detected: true },
];

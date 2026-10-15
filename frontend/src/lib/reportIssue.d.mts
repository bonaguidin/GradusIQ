export type ReportKind = 'bug' | 'feature';

export const REPORT_URL: string;
export const REPORT_LIMITS: Readonly<{
  maxScreenshots: number;
  maxScreenshotBytes: number;
  maxTotalBytes: number;
  maxImageDimension: number;
  minDescription: number;
  maxDescription: number;
}>;
export const REPORT_KINDS: ReadonlyArray<{ value: ReportKind; label: string }>;

export interface ReportFields {
  kind: ReportKind;
  description: string;
  email: string;
  name?: string;
  page?: string;
  userAgent?: string;
  website?: string;
}

export function validateReport(fields: { description: string; email: string }): {
  description?: string;
  email?: string;
};
export function screenshotFits(existingSizes: number[], size: number): 'ok' | 'count' | 'size' | 'total';
export function fitWithin(width: number, height: number, max?: number): { width: number; height: number };
export function buildReportFormData(
  fields: ReportFields,
  screenshots?: Array<{ blob: Blob; name: string }>,
): FormData;
export type ReportResult = { ok: true } | { ok: false; message: string };
export function normalizeReportResponse(status: number, body: unknown): ReportResult;

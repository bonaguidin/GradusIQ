import type { FitHiringSignal } from '../types/analysis';

export interface HiringSignalLineResult {
  variant: 'signal' | 'empty';
  text: string;
}

export declare function hiringSignalLine(
  hiringSignal: FitHiringSignal | null | undefined,
): HiringSignalLineResult | null;

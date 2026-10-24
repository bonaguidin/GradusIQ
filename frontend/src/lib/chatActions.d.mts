export interface ChatAction {
  label: string;
  to?: string;
  dashboard?: string;
  scrollTo?: string;
  dialog?: 'report-issue';
  accountOnly?: boolean;
}

export declare const CHAT_ACTIONS: Record<string, ChatAction>;
export declare const MAX_CHAT_ACTIONS: number;
export declare function usableActions(ids: unknown, who: { demo: boolean }): string[];

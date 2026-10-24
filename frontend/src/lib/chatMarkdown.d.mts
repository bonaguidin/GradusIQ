export type ChatInline =
  | { type: 'text'; text: string }
  | { type: 'strong' | 'em'; children: ChatInline[] }
  | { type: 'code'; text: string }
  | { type: 'link'; href: string; children: ChatInline[] };

export type ChatBlock =
  | { type: 'p'; lines: ChatInline[][] }
  | { type: 'ul' | 'ol'; items: ChatInline[][] };

export declare function parseInline(text: string): ChatInline[];

export declare function parseChatMarkdown(source: string): ChatBlock[];

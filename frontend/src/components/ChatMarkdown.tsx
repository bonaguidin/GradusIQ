import { Fragment } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { parseChatMarkdown } from '../lib/chatMarkdown.mjs';
import type { ChatInline } from '../lib/chatMarkdown.mjs';

function renderInline(nodes: ChatInline[]): ReactNode {
  return nodes.map((node, i) => {
    switch (node.type) {
      case 'text':
        return <Fragment key={i}>{node.text}</Fragment>;
      case 'strong':
        return <strong key={i}>{renderInline(node.children)}</strong>;
      case 'em':
        return <em key={i}>{renderInline(node.children)}</em>;
      case 'code':
        return <code key={i}>{node.text}</code>;
      case 'link':
        // An in-app path stays in the single-page app (and keeps the chat
        // panel open); anything else is https only (see chatMarkdown.mjs).
        return node.href.startsWith('/') ? (
          <Link key={i} to={node.href}>{renderInline(node.children)}</Link>
        ) : (
          <a key={i} href={node.href} target="_blank" rel="noopener noreferrer">{renderInline(node.children)}</a>
        );
    }
  });
}

/** An assistant reply as paragraphs and lists. Never sets HTML directly. */
export function ChatMarkdown({ text }: { text: string }) {
  return (
    <>
      {parseChatMarkdown(text).map((block, i) => {
        if (block.type === 'p') {
          return (
            <p key={i}>
              {block.lines.map((line, j) => (
                <Fragment key={j}>
                  {j > 0 && <br />}
                  {renderInline(line)}
                </Fragment>
              ))}
            </p>
          );
        }
        const List = block.type;
        return (
          <List key={i}>
            {block.items.map((item, j) => <li key={j}>{renderInline(item)}</li>)}
          </List>
        );
      })}
    </>
  );
}

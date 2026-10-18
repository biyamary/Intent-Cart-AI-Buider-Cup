import ReactMarkdown from 'react-markdown'
import { Search, Sparkles } from 'lucide-react'
import { safeWebUrl, type ChatMessage } from '../lib/conversations'

const searchFramePolicy = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; base-uri 'none'; form-action 'none'">`

export function AgentMessage({
  message,
  agentName = 'IntentCart assistant',
  icon,
}: {
  message: ChatMessage
  agentName?: string
  icon?: React.ReactNode
}) {
  const fromUser = message.role === 'user'
  return (
    <article className={`chat-message ${fromUser ? 'from-user' : 'from-assistant'}`}>
      <div className="message-author">
        {!fromUser && (icon || <Sparkles size={14} />)}
        <strong>{fromUser ? 'You' : agentName}</strong>
        <time dateTime={new Date(message.created_at * 1000).toISOString()}>
          {new Date(message.created_at * 1000).toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
          })}
        </time>
      </div>
      {fromUser ? (
        <p className="user-message-text">{message.text}</p>
      ) : message.status === 'error' ? (
        <div className="notice error">{message.text}</div>
      ) : (
        <>
          <div className="agent-markdown">
            <ReactMarkdown
              skipHtml
              components={{
                a: ({ href, children }) => {
                  const url = safeWebUrl(href)
                  return url ? (
                    <a href={url} target="_blank" rel="noopener noreferrer">
                      {children}
                    </a>
                  ) : (
                    <span>{children}</span>
                  )
                },
                img: ({ alt }) => <span>{alt}</span>,
              }}
            >
              {message.text}
            </ReactMarkdown>
          </div>
          {(message.search_queries.length > 0 || message.sources.length > 0) && (
            <div className="search-attribution">
              <span className="search-label">
                <Search size={13} /> Used Google Search
              </span>
              {message.sources.length > 0 && (
                <ol className="source-links">
                  {message.sources.map((source, index) => (
                    <li key={`${source.url}-${index}`}>
                      <a href={safeWebUrl(source.url)} target="_blank" rel="noopener noreferrer">
                        {index + 1}. {source.title} ↗
                      </a>
                    </li>
                  ))}
                </ol>
              )}
              {message.citations.length > 0 && (
                <details>
                  <summary>See supporting sources</summary>
                  <ul className="citation-details">
                    {message.citations.map((citation, index) => (
                      <li key={index}>
                        <p>{citation.text}</p>
                        <div>
                          {citation.source_indices.map(
                            (sourceIndex) =>
                              message.sources[sourceIndex] && (
                                <a
                                  key={sourceIndex}
                                  href={safeWebUrl(message.sources[sourceIndex].url)}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                >
                                  Source {sourceIndex + 1} ↗
                                </a>
                              ),
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
          {message.search_entry_point && (
            <iframe
              className="search-suggestions"
              title="Google Search suggestions"
              sandbox="allow-popups allow-popups-to-escape-sandbox"
              referrerPolicy="no-referrer"
              srcDoc={searchFramePolicy + message.search_entry_point}
            />
          )}
        </>
      )}
    </article>
  )
}

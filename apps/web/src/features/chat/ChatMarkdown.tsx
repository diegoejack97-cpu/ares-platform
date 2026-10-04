import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Model output is untrusted: no HTML, remote images, or executable links. */
export function ChatMarkdown({ children }: { children: string }) {
  return (
    <div className="chat-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        allowedElements={[
          "p",
          "br",
          "strong",
          "em",
          "del",
          "blockquote",
          "ul",
          "ol",
          "li",
          "h1",
          "h2",
          "h3",
          "h4",
          "h5",
          "h6",
          "hr",
          "pre",
          "code",
          "a",
          "table",
          "thead",
          "tbody",
          "tr",
          "th",
          "td",
        ]}
        urlTransform={(url) => {
          if (/^https?:\/\//i.test(url)) return url;
          if (/^\/(?!\/)/.test(url) && !url.includes("\\")) return url;
          if (url.startsWith("#")) return url;
          return "";
        }}
        components={{
          h1: ({ children }) => <h3>{children}</h3>,
          h2: ({ children }) => <h3>{children}</h3>,
          h3: ({ children }) => <h3>{children}</h3>,
          h4: ({ children }) => <h4>{children}</h4>,
          h5: ({ children }) => <h4>{children}</h4>,
          h6: ({ children }) => <h4>{children}</h4>,
          a: ({ href, children }) =>
            href ? (
              <a href={href} rel="noopener noreferrer">
                {children}
              </a>
            ) : (
              <span>{children}</span>
            ),
          table: ({ children }) => (
            <div className="chat-table-frame">
              <div
                className="chat-table-scroll"
                role="region"
                aria-label="Dados da resposta"
                tabIndex={0}
              >
                <table>{children}</table>
              </div>
              <p className="chat-table-hint">
                Deslize a tabela para ver as outras colunas.
              </p>
            </div>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

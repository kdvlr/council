import React, { useEffect, useId, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Check, Copy, Download } from 'lucide-react';

interface MermaidBlockProps {
  chart: string;
  isDark: boolean;
}

const MermaidBlock: React.FC<MermaidBlockProps> = ({ chart, isDark }) => {
  const rawId = useId().replace(/[^a-zA-Z0-9]/g, '');
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const mermaid = (await import('mermaid')).default;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          theme: isDark ? 'dark' : 'default',
        });
        const renderId = `mmd-${rawId}-${Math.random().toString(36).slice(2, 7)}`;
        const { svg: rendered } = await mermaid.render(renderId, chart.trim());
        if (!cancelled) {
          setSvg(rendered);
          setFailed(false);
        }
      } catch {
        if (!cancelled) {
          setFailed(true);
        }
      }
    }, 280);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [chart, isDark, rawId]);

  if (svg && !failed) {
    return (
      <div
        className="my-4 overflow-x-auto rounded-2xl p-4 md3-card-lowest flex justify-center"
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    );
  }

  return (
    <pre className="my-3 overflow-x-auto rounded-2xl p-3.5 text-xs font-mono-code md3-card-lowest text-[var(--md-on-surface-variant)]">
      <code>{chart}</code>
    </pre>
  );
};

interface CodeCopyBtnProps {
  text: string;
}

const CodeCopyBtn: React.FC<CodeCopyBtnProps> = ({ text }) => {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };
  return (
    <button
      type="button"
      onClick={handleCopy}
      className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium md3-btn-tonal cursor-pointer"
      title="Copy code"
    >
      {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
};

export const CopyMarkdownButton: React.FC<{
  markdown: string;
  label?: string;
  filename?: string;
  showDownload?: boolean;
}> = ({ markdown, label = 'Copy MD', filename = 'council-output.md', showDownload = true }) => {
  const [copied, setCopied] = useState(false);

  const onCopy = async () => {
    await navigator.clipboard.writeText(markdown);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  const onDownload = () => {
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="inline-flex items-center gap-1.5">
      <button
        type="button"
        onClick={onCopy}
        disabled={!markdown}
        className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium md3-btn-tonal cursor-pointer disabled:opacity-40"
      >
        {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
        {copied ? 'Copied' : label}
      </button>
      {showDownload && (
        <button
          type="button"
          onClick={onDownload}
          disabled={!markdown}
          className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium md3-card-high hover:brightness-105 cursor-pointer disabled:opacity-40"
          title="Download Markdown file"
        >
          <Download className="w-3.5 h-3.5" />
          .md
        </button>
      )}
    </div>
  );
};

interface MarkdownViewerProps {
  content: string;
  isDark: boolean;
  className?: string;
}

export const MarkdownViewer: React.FC<MarkdownViewerProps> = ({
  content,
  isDark,
  className = '',
}) => {
  if (!content) {
    return null;
  }

  return (
    <div className={`md-prose ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          code({ className: codeClass, children, ...props }) {
            const match = /language-(\w+)/.exec(codeClass || '');
            const codeString = String(children).replace(/\n$/, '');
            const lang = match?.[1]?.toLowerCase() || '';

            if (lang === 'mermaid') {
              return <MermaidBlock chart={codeString} isDark={isDark} />;
            }

            const isBlock = Boolean(match) || codeString.includes('\n');
            if (isBlock) {
              return (
                <div className="my-3.5 rounded-2xl overflow-hidden border border-[var(--md-outline-variant)] bg-[var(--md-surface-container-lowest)]">
                  <div className="flex items-center justify-between px-3.5 py-1.5 border-b border-[var(--md-outline-variant)] bg-[var(--md-surface-container-low)]">
                    <span className="text-[11px] font-mono-code uppercase tracking-wider text-[var(--md-on-surface-variant)]">
                      {lang || 'text'}
                    </span>
                    <CodeCopyBtn text={codeString} />
                  </div>
                  <SyntaxHighlighter
                    style={isDark ? oneDark : oneLight}
                    language={lang || 'text'}
                    PreTag="div"
                    customStyle={{
                      margin: 0,
                      padding: '0.9rem 1rem',
                      fontSize: '0.83rem',
                      background: 'transparent',
                    }}
                  >
                    {codeString}
                  </SyntaxHighlighter>
                </div>
              );
            }

            return (
              <code className={codeClass} {...props}>
                {children}
              </code>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};

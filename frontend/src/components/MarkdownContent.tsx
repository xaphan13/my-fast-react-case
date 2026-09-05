// Вставка готового серверного HTML статьи (article.content).
// dangerouslySetInnerHTML допустим только здесь: backend рендерит markdown
// через доверенный движок `python-markdown` (см. md_articles/schema_art.py).

import { useEffect } from 'react';

interface MarkdownContentProps {
  html: string;
}

export default function MarkdownContent({ html }: MarkdownContentProps) {
  useEffect(() => {
    // (window as any) — hljs подключён с CDN как глобал (см. index.html).
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hljs = (window as any).hljs;
    // Регистрация алиасов меток code-fence, которых нет в hljs 11.12.0:
    // — до первого highlightAll(), иначе первый рендер пропустит алиасы;
    // — idемпотентно при смене html (registerAliases безопасно вызывать повторно).
    if (hljs?.registerAliases) {
      hljs.registerAliases('env', { languageName: 'ini' });
      hljs.registerAliases(['jinja2', 'vue'], { languageName: 'xml' });
      hljs.registerAliases(['txt', 'text'], { languageName: 'plaintext' });
      hljs.registerAliases(['js', 'jsx'], { languageName: 'javascript' });
      hljs.registerAliases('make', { languageName: 'makefile' });
      hljs.registerAliases('Dockerfile', { languageName: 'dockerfile' });
      hljs.registerAliases('toml', { languageName: 'ini' });
    }
    hljs?.highlightAll();
  }, [html]);

  // eslint-disable-next-line react/no-danger
  return <div className="markdown-content" dangerouslySetInnerHTML={{ __html: html }} />;
}
/** Lightweight markdown-like renderer for Knowledge Base articles. */

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function inlineFormat(text: string): string {
  let out = escapeHtml(text)
  out = out.replace(/\*\*(.+?)\*\*/g, '<strong class="font-semibold text-foreground">$1</strong>')
  out = out.replace(/\*(.+?)\*/g, '<em class="italic text-foreground/90">$1</em>')
  return out
}

function isTableRow(line: string): boolean {
  return line.trim().startsWith('|') && line.trim().endsWith('|')
}

function isTableSeparator(line: string): boolean {
  return /^\|[\s\-:|]+\|$/.test(line.trim())
}

function parseTableRow(line: string): string[] {
  return line
    .trim()
    .slice(1, -1)
    .split('|')
    .map((cell) => cell.trim())
}

function renderTable(rows: string[]): string {
  if (rows.length < 2) return rows.map((r) => `<p>${inlineFormat(r)}</p>`).join('')

  const headerCells = parseTableRow(rows[0]!)
  const bodyRows = rows.slice(2) // skip header + separator

  const thead = `<thead><tr>${headerCells.map((c) => `<th class="px-3 py-2 text-left font-semibold text-foreground border-b border-border">${inlineFormat(c)}</th>`).join('')}</tr></thead>`
  const tbody = `<tbody>${bodyRows
    .map(
      (row) =>
        `<tr class="border-b border-border/50">${parseTableRow(row)
          .map((c) => `<td class="px-3 py-2 text-muted-foreground">${inlineFormat(c)}</td>`)
          .join('')}</tr>`,
    )
    .join('')}</tbody>`

  return `<div class="my-4 overflow-x-auto rounded-lg border border-border"><table class="w-full text-sm">${thead}${tbody}</table></div>`
}

export function renderKnowledgeContent(content: string): string {
  const lines = content.split('\n')
  const html: string[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]!

    // Fenced code block
    if (line.trim().startsWith('```')) {
      const codeLines: string[] = []
      i++
      while (i < lines.length && !lines[i]!.trim().startsWith('```')) {
        codeLines.push(lines[i]!)
        i++
      }
      html.push(
        `<pre class="my-4 rounded-lg border border-border bg-secondary/60 p-4 text-xs font-mono text-foreground overflow-x-auto leading-relaxed">${escapeHtml(codeLines.join('\n'))}</pre>`,
      )
      i++
      continue
    }

    // Markdown table
    if (isTableRow(line)) {
      const tableLines: string[] = []
      while (i < lines.length && isTableRow(lines[i]!)) {
        tableLines.push(lines[i]!)
        i++
      }
      html.push(renderTable(tableLines))
      continue
    }

    // Empty line — paragraph break
    if (line.trim() === '') {
      i++
      continue
    }

    // Bullet list block
    if (/^[•\-]\s/.test(line.trim()) || line.trim().startsWith('• ')) {
      const items: string[] = []
      while (i < lines.length && (/^[•\-]\s/.test(lines[i]!.trim()) || lines[i]!.trim().startsWith('• '))) {
        items.push(lines[i]!.trim().replace(/^[•\-]\s*/, ''))
        i++
      }
      html.push(
        `<ul class="my-3 space-y-2 pl-1">${items.map((item) => `<li class="flex gap-2 text-sm text-muted-foreground leading-relaxed"><span class="text-primary mt-1.5 flex-shrink-0">•</span><span>${inlineFormat(item)}</span></li>`).join('')}</ul>`,
      )
      continue
    }

    // Numbered list block
    if (/^\d+\.\s/.test(line.trim())) {
      const items: string[] = []
      while (i < lines.length && /^\d+\.\s/.test(lines[i]!.trim())) {
        items.push(lines[i]!.trim().replace(/^\d+\.\s*/, ''))
        i++
      }
      html.push(
        `<ol class="my-3 space-y-2 pl-5 list-decimal">${items.map((item) => `<li class="text-sm text-muted-foreground leading-relaxed pl-1">${inlineFormat(item)}</li>`).join('')}</ol>`,
      )
      continue
    }

    // Regular paragraph — collect consecutive non-special lines
    const paraLines: string[] = []
    while (
      i < lines.length &&
      lines[i]!.trim() !== '' &&
      !lines[i]!.trim().startsWith('```') &&
      !isTableRow(lines[i]!) &&
      !/^[•\-]\s/.test(lines[i]!.trim()) &&
      !lines[i]!.trim().startsWith('• ') &&
      !/^\d+\.\s/.test(lines[i]!.trim())
    ) {
      paraLines.push(lines[i]!)
      i++
    }
    html.push(
      `<p class="text-sm text-muted-foreground leading-relaxed mb-4 last:mb-0">${inlineFormat(paraLines.join(' '))}</p>`,
    )
  }

  return html.join('')
}

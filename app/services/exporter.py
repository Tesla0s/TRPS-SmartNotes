import re
from markdown_pdf import MarkdownPdf, Section

def markdown_to_text(md: str) -> str:
    text = re.sub(r"- \[([xX])\]", "- [x]", md)
    text = re.sub(r"- \[\s+\]", "- [ ]", md)
    text = re.sub(r"^\s*---\s*$", "", text, flags=re.MULTILINE)
    return text

def export_pdf_markdown(path: str, title: str, content: str):
    md = content or ""
    
    if title and not re.search(r"^\s{0,3}#{1,2}\s+\S+", md.strip()):
        md = f"# {title.strip()}\n\n" + md

    lines = md.splitlines()
    new_lines = []
    
    task_pattern = re.compile(r"^(\s*)-\s*\[([ xX])\]\s*(.*)$")
    hr_pattern = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")

    for i, line in enumerate(lines):
        match_task = task_pattern.match(line)
        match_hr = hr_pattern.match(line)

        if match_task:
            indent, mark, text = match_task.groups()
            symbol = "☑" if mark.lower() == "x" else "☐"
            processed_line = f"{indent}{symbol} {text}  "

            if i > 0:
                prev_line = lines[i-1]
                is_prev_task = task_pattern.match(prev_line)
                is_prev_empty = not prev_line.strip()
                if not is_prev_task and not is_prev_empty:
                    new_lines.append("") 
            
            new_lines.append(processed_line)

        elif match_hr:
            if i > 0 and lines[i-1].strip():
                 new_lines.append("")
            
            new_lines.append(line)
            
        else:
            new_lines.append(line)

    final_md = "\n".join(new_lines)

    css = """
    @page { size: A4; margin: 16mm 18mm; }
    body { font-family: 'DejaVu Sans', 'Noto Sans', 'Segoe UI', Arial, sans-serif; font-size: 12pt; line-height: 1.5; }
    h1 { font-size: 20pt; margin: .5em 0 .4em; }
    h2 { font-size: 16pt; margin: .5em 0 .4em; }
    h3 { font-size: 14pt; margin: .4em 0 .3em; }
    
    /* Стиль для горизонтальной линии */
    hr { 
        display: block;
        height: 1px; 
        border: 0; 
        border-bottom: 1px solid #999; 
        margin: 1em 0; 
    }
    
    ul,ol { margin: .2em 0 .6em 1.2em; }
    li { margin: .15em 0; }
    
    blockquote { margin: .6em 0; padding-left: .8em; border-left: 3px solid #bbb; color: #333; }
    code, pre { font-family: 'DejaVu Sans Mono', 'Fira Code', 'Consolas', monospace; }
    pre { background: #f7f7f7; padding: 8pt; border-radius: 4pt; }
    
    table { border-collapse: collapse; margin: .6em 0; width: 100%; }
    th, td { border: 1px solid #bbb; padding: 6pt 8pt; vertical-align: top; }
    th { background: #efefef; }
    img { max-width: 100%; }
    """
    pdf = MarkdownPdf(toc_level=0, optimize=True)
    pdf.add_section(Section(final_md, paper_size="A4"), user_css=css)
    pdf.save(path)
from pathlib import Path

def extract_document(path:Path, kind:str):
    if kind=='txt': return path.read_text(encoding='utf-8',errors='ignore'), 1
    if kind=='pdf':
        from pypdf import PdfReader
        r=PdfReader(str(path)); text='\n\n'.join((p.extract_text() or '') for p in r.pages)
        return text, len(r.pages)
    if kind=='docx':
        from docx import Document
        d=Document(str(path)); return '\n'.join(p.text for p in d.paragraphs), 1
    raise ValueError('Unsupported document')

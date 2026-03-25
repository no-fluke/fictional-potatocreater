"""
convert_new_format.py
─────────────────────
Converts quiz files in the NEW markdown format (**Q.No: N** style)
into the bot-compatible TXT format used by parse_txt_file() in app.py.

NEW FORMAT (input):
    **PART-A (English Language)**

    **Q.No: 1**
    Question text line 1
    Question text line 2 (optional)

    Option 1
    Option 2
    Option 3
    Option 4

    ── or for passage questions ──

    **Q.No: 7**
    Read the following passage and answer the questions based on it:
    <long passage text>

    Actual question text?

    Option 1
    Option 2
    Option 3
    Option 4

    ── or for grammar/label questions ──

    **Q.No: 1**
    Identify the grammatical error.
    Inline sentence A. part1 B. part2

    A. part1
    B. part2
    C. part3
    D. part4

BOT FORMAT (output):
    1. Question text
    a) Option 1
    b) Option 2
    c) Option 3
    d) Option 4
    Correct option:-
    ex:

USAGE:
    # Convert a single file
    python convert_new_format.py input.txt output.txt

    # Convert and print to terminal
    python convert_new_format.py input.txt

    # Use as a module inside app.py
    from convert_new_format import parse_new_format
    questions = parse_new_format(file_content)
"""

import re
import sys
import os


# ── Option label map ──────────────────────────────────────────────────────────
OPTION_KEYS = ['a', 'b', 'c', 'd', 'e']

# ── Compiled patterns ─────────────────────────────────────────────────────────

# FIX 1: More robust Q.No splitter — allows optional leading whitespace and
# optional trailing whitespace/text after the closing **. Also handles
# variations like **Q.No:1** (no space) and **Q. No: 1**.
QNUM_SPLIT = re.compile(r'(?=[ \t]*\*\*Q\.?\s*No\s*:\s*\d+\*\*)', re.IGNORECASE)
QNUM_HEADER = re.compile(r'\*\*Q\.?\s*No\s*:\s*(\d+)\*\*', re.IGNORECASE)

# FIX 3: Safer uppercase option prefix — only strip A./B./C./D. when the WHOLE
# paragraph looks like an options list (i.e. every line starts with A–E dot).
# We check this per-paragraph rather than blindly stripping every line.
UPPER_OPT_LINE = re.compile(r'^([A-E])\.\s+(.+)$')

# Bold section header (not a Q.No line)
BOLD_HEADER = re.compile(r'^\s*\*\*([^*]+)\*\*\s*$')


def clean_line(line: str) -> str:
    """Strip markdown bold markers (**) and trailing whitespace."""
    line = re.sub(r'\*\*', '', line)
    return line.rstrip()


def _is_options_paragraph(para: list[str]) -> bool:
    """
    FIX 3 helper: Return True only when every line in the paragraph matches
    the uppercase 'A. text' pattern — meaning the whole paragraph is an
    A/B/C/D options block, not a question body that happens to mention 'A.'.
    Requires at least 2 lines to avoid single-line false positives.
    """
    if len(para) < 2:
        return False
    return all(UPPER_OPT_LINE.match(line) for line in para)


def _strip_upper_prefix(para: list[str]) -> list[str]:
    """Strip A./B./C./D. prefix from each line in a confirmed options paragraph."""
    return [UPPER_OPT_LINE.sub(r'\2', line).strip() for line in para]


def _get_section_before(content: str, pos: int) -> str:
    """
    FIX 4: Find the most recent bold section header BEFORE position `pos`
    in the content string (not just the very first one globally).
    Returns empty string if none found.
    """
    section = ''
    for line in content[:pos].split('\n'):
        m = BOLD_HEADER.match(line.strip())
        if m and 'Q.No' not in m.group(1) and 'Q. No' not in m.group(1):
            section = m.group(1).strip()
    return section


def parse_new_format(content: str) -> list[dict]:
    """
    Parse a markdown-style quiz file (**Q.No: N** format) and return a list
    of question dicts fully compatible with the existing parse_txt_file()
    output and quiz HTML templates.

    Handles all question types found in the document:
      • Single-line question + plain options (synonym, spelling, idiom, etc.)
      • Multi-line question body + plain options (fill-in-the-blank, grammar)
      • Uppercase-labelled options (A. / B. / C. / D.) — prefix is stripped
      • Passage-based questions (passage + question + options in 3 paragraphs)
      • Rearrangement questions (P/Q/R/S body + combo options like 'Q, R, P, S')
      • 3-option questions (answer field stays blank)

    Returns:
        List of dicts with keys: question, option_1..5, answer, solution_text,
        *_image fields, correct_score, negative_score, section.
        answer and solution_text are empty strings (not present in this format).
    """
    questions = []

    # FIX 1: Use the improved splitter that tolerates leading whitespace
    raw_blocks = QNUM_SPLIT.split(content)

    for block in raw_blocks:
        block_stripped = block.strip()
        if not block_stripped:
            continue

        lines_raw = block_stripped.split('\n')

        # Block must start with **Q.No: N** (possibly with leading spaces stripped)
        qnum_match = QNUM_HEADER.match(lines_raw[0].strip())
        if not qnum_match:
            continue
        qnum = int(qnum_match.group(1))

        # FIX 4: Determine section from the content BEFORE this block's position
        block_pos = content.find(lines_raw[0].strip())
        section = _get_section_before(content, max(block_pos, 0))

        # Clean all lines after the Q.No header line
        rest_lines = [clean_line(l) for l in lines_raw[1:]]

        # ── Split cleaned lines into paragraphs (separated by blank lines) ───
        paragraphs: list[list[str]] = []
        current: list[str] = []
        for l in rest_lines:
            if l.strip() == '':
                if current:
                    paragraphs.append(current)
                    current = []
            else:
                current.append(l.strip())
        if current:
            paragraphs.append(current)

        # Need at least 2 paragraphs: question body + options
        if len(paragraphs) < 2:
            continue

        # ── Options: LAST paragraph always ───────────────────────────────────
        options_raw = paragraphs[-1]

        # FIX 3: Only strip A./B./C./D. prefix when the entire paragraph
        # qualifies as an uppercase options block — prevents stripping text
        # from question bodies that happen to start with a capital letter + dot.
        if _is_options_paragraph(options_raw):
            options = _strip_upper_prefix(options_raw)
        else:
            options = [opt.strip() for opt in options_raw]

        # ── Question text: ALL paragraphs before the last ────────────────────
        # For 2-paragraph questions  → paragraphs[0]   = question body
        # For 3-paragraph questions  → paragraphs[0]   = passage/intro
        #                              paragraphs[1]   = actual question line
        # Both cases: join everything before last paragraph into question text
        question_parts: list[str] = []
        for para in paragraphs[:-1]:
            question_parts.extend(para)

        question_text = '<br>'.join(question_parts)

        # ── Build output dict ─────────────────────────────────────────────────
        question = {
            "question":       question_text,
            "option_1":       options[0] if len(options) > 0 else "",
            "option_2":       options[1] if len(options) > 1 else "",
            "option_3":       options[2] if len(options) > 2 else "",
            "option_4":       options[3] if len(options) > 3 else "",
            "option_5":       options[4] if len(options) > 4 else "",
            "answer":         "",   # not present in this format — fill manually
            "solution_text":  "",   # not present in this format — fill manually
            "question_image": "",
            "option_image_1": "", "option_image_2": "", "option_image_3": "",
            "option_image_4": "", "option_image_5": "",
            "solution_image": "",
            "correct_score":  "3",
            "negative_score": "1",
            "section":        section,
        }

        if question["question"] and question["option_1"]:
            questions.append(question)

    return questions


def to_bot_txt(questions: list[dict], start_number: int = 1) -> str:
    """
    Convert a list of question dicts back to the bot-compatible TXT format
    that parse_txt_file() in app.py can read.

    Output per question:
        N. Question text
        a) Option 1
        b) Option 2
        c) Option 3
        d) Option 4
        Correct option:-
        ex:

        (blank line between questions)
    """
    lines = []
    for i, q in enumerate(questions, start=start_number):
        # Question — replace <br> with newline for multi-line bodies
        q_text = q['question'].replace('<br>', '\n    ')
        lines.append(f"{i}. {q_text}")

        # Options — only write non-empty ones
        for j, key in enumerate(OPTION_KEYS):
            opt = q.get(f'option_{j+1}', '').strip()
            if opt:
                opt_text = opt.replace('<br>', '\n    ')
                lines.append(f"    {key}) {opt_text}")

        # Answer and explanation placeholders (blank = to be filled)
        answer_letter = ''
        if q.get('answer'):
            idx = int(q['answer']) - 1
            if 0 <= idx < len(OPTION_KEYS):
                answer_letter = OPTION_KEYS[idx]
        lines.append(f"Correct option:-{answer_letter}")
        lines.append(f"ex: {q.get('solution_text', '')}")
        lines.append('')   # blank line between questions

    return '\n'.join(lines)


def convert_file(input_path: str, output_path: str = None) -> None:
    """Read input file, parse, write bot-compatible TXT to output_path (or print)."""
    with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    questions = parse_new_format(content)

    if not questions:
        print(f"[WARNING] No questions parsed from: {input_path}")
        return

    result = to_bot_txt(questions)

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(result)
        print(f"[OK] {len(questions)} questions written to: {output_path}")
    else:
        print(f"[OK] {len(questions)} questions parsed from: {input_path}\n")
        print(result)


# ── Integration with app.py upload route ─────────────────────────────────────
# Add this import at the top of app.py:
#   from convert_new_format import parse_new_format
#
# Then in the /upload route, detect format and call the right parser:
#
#   content = file.read().decode('utf-8', errors='ignore')
#   if '**Q.No:' in content or '**Q. No:' in content:
#       questions = parse_new_format(content)
#   else:
#       questions = parse_txt_file(content)


# ── CLI entry point ───────────────────────────────────────────────────────────
if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    input_file  = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) >= 3 else None

    if not os.path.exists(input_file):
        print(f"[ERROR] File not found: {input_file}")
        sys.exit(1)

    convert_file(input_file, output_file)

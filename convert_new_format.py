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


def clean_line(line: str) -> str:
    """Strip markdown bold markers (**) and trailing whitespace/spaces."""
    line = re.sub(r'\*\*', '', line)
    return line.rstrip()


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

    # ── Detect section header (first **bold** line that is NOT a Q.No) ────────
    section = ''
    for line in content.split('\n'):
        m = re.match(r'^\s*\*\*([^*]+)\*\*\s*$', line.strip())
        if m and 'Q.No' not in m.group(1):
            section = m.group(1).strip()
            break

    # ── Split on Q.No markers, keeping the marker in each block ──────────────
    raw_blocks = re.split(r'(?=\*\*Q\.No:\s*\d+\*\*)', content)

    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue

        lines_raw = block.split('\n')

        # Block must start with **Q.No: N**
        qnum_match = re.match(r'\*\*Q\.No:\s*(\d+)\*\*', lines_raw[0].strip())
        if not qnum_match:
            continue
        qnum = int(qnum_match.group(1))

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

        # Strip uppercase A./B./C./D. prefix if present (grammar label questions)
        uppercase_prefix = re.compile(r'^[A-E]\.\s+')
        options: list[str] = [
            re.sub(uppercase_prefix, '', opt).strip()
            for opt in options_raw
        ]

        # ── Question text: ALL paragraphs before the last ────────────────────
        # For 2-paragraph questions  → paragraphs[0]   = question body
        # For 3-paragraph questions  → paragraphs[0]   = passage + intro
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
                # Replace <br> (Hindi sub-line) with newline+indent
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
#   from convert_new_format import parse_new_format as parse_new_format_file
#
# Then in the /upload route, detect format and call the right parser:
#
#   content = file.read().decode('utf-8', errors='ignore')
#   if '**Q.No:' in content:
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

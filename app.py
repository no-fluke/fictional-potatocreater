import os
import re
import json
import base64
import uuid
from io import BytesIO
from PIL import Image
from flask import Flask, render_template, request, jsonify, Response

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB
app.config['TEMP_QUIZ_DATA'] = {}  # temporary storage

# -------------------------------
# TXT PARSER (supports bilingual SSC-style format with English + Hindi)
# -------------------------------
def parse_txt_file(content):
    """
    Parse TXT quiz files exported from SSC CGL exam papers.

    Supported format per question block (separated by blank lines):
        26. Question text (English)
            Question text (Hindi)
            a) Option A
            फेंसिंग              ← optional Hindi sub-line per option
            b) Option B
            ...
        Correct option:-c
        ex: English explanation
        Hindi explanation        ← optional Hindi line after ex:

    Key fixes vs original parser:
      1. OPTION_PATTERN and STOP_QUESTION use lowercase-only (no re.IGNORECASE, no dot form)
         → prevents 'A. The committee B. submitted...' in question body being
           mistaken for an option (was breaking English grammar questions).
      2. Header/metadata blocks ([file name]:, Date:, PART-B) are skipped explicitly.
      3. Hindi explanation line after ex: is now captured in solution_text.
    """
    questions = []

    # Split on blank lines between question blocks
    blocks = re.split(r'\n\s*\n', content.strip())

    # ── Compiled patterns (defined once, reused per block) ─────────────────
    # Matches 'a) text' or '(a) text' — lowercase ONLY, no dot form.
    # Dot form 'a.' is intentionally excluded to avoid false matches on
    # question body lines like 'A. The committee B. has submitted their report'.
    OPTION_PATTERN = re.compile(r'^([a-e])\)\s*|^\(([a-e])\)\s*')

    # Same pattern used to detect where question text ends and options begin.
    STOP_QUESTION = re.compile(r'^[a-e]\)\s*|^\([a-e]\)\s*')

    # Used to check whether the line AFTER an option start is a Hindi sub-line
    # or the start of the next option/answer/explanation.
    STOP_OPTION_LOOKAHEAD = re.compile(
        r'^[a-e]\)|^\([a-e]\)|^Correct|^Answer:|^ex:', re.IGNORECASE
    )

    ANSWER_MAP = {'a': '1', 'b': '2', 'c': '3', 'd': '4', 'e': '5'}

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if len(lines) < 3:
            continue

        # Skip header/metadata blocks — they don't start with a question number
        # Examples: '[file name]: ...', 'Date : ...', 'PART-B (General Intelligence)'
        if not re.match(r'^\d+[\.\)]\s*|^Q[\.\s]*\d+', lines[0]):
            continue

        question = {
            "question": "",
            "option_1": "", "option_2": "", "option_3": "", "option_4": "", "option_5": "",
            "answer": "",
            "solution_text": "",
            "question_image": "",
            "option_image_1": "", "option_image_2": "", "option_image_3": "",
            "option_image_4": "", "option_image_5": "",
            "solution_image": "",
            "correct_score": "3",
            "negative_score": "1",
            "section": ""  # filled by caller for full-mock mode
        }

        current_line = 0

        # ── Extract question text ─────────────────────────────────────────
        # Strip leading question number (e.g. '26. ', 'Q.1 ', 'Q 1 ')
        question_text = re.sub(r'^(?:\d+[\.\)]\s*|Q[\.\s]*\d+\s+)', '', lines[0])
        question_lines = [question_text]
        current_line = 1

        # Absorb all continuation lines: bilingual Hindi line, multi-line statements,
        # Conclusions blocks, etc. Stop only when we hit a lowercase option marker.
        while current_line < len(lines) and not STOP_QUESTION.match(lines[current_line]):
            question_lines.append(lines[current_line])
            current_line += 1

        question["question"] = '<br>'.join(question_lines)

        # ── Extract options (up to 5) ─────────────────────────────────────
        option_count = 0
        while (current_line < len(lines)
               and option_count < 5
               and not re.match(r'^Correct|^Answer:|^ex:', lines[current_line], re.IGNORECASE)):

            if OPTION_PATTERN.match(lines[current_line]):
                option_key = f"option_{option_count + 1}"
                option_text = lines[current_line]
                current_line += 1

                # If the very next line is a Hindi translation of this option
                # (i.e. it does NOT start another option, answer, or explanation),
                # append it to this option's text.
                if (current_line < len(lines)
                        and not STOP_OPTION_LOOKAHEAD.match(lines[current_line])):
                    option_text += f"<br>{lines[current_line]}"
                    current_line += 1

                question[option_key] = option_text
                option_count += 1
            else:
                # Unexpected non-option line between options — skip it
                current_line += 1

        # ── Extract correct answer ────────────────────────────────────────
        while current_line < len(lines):
            line = lines[current_line]

            if re.match(r'^Correct\s*(?:option)?\s*[:-]', line, re.IGNORECASE):
                # Handles: 'Correct option:-c', 'Correct option: c', 'Correct:-c'
                m = re.search(r'[:\-]\s*([a-e])', line, re.IGNORECASE)
                if m:
                    question["answer"] = ANSWER_MAP.get(m.group(1).lower(), '1')

            elif re.match(r'^Answer\s*[:\-]', line, re.IGNORECASE):
                # Handles: 'Answer: (c)', 'Answer:-c', 'Answer: c'
                m = (re.search(r'\(([a-e])\)', line, re.IGNORECASE)
                     or re.search(r'[:\-]\s*([a-e])', line, re.IGNORECASE))
                if m:
                    question["answer"] = ANSWER_MAP.get(m.group(1).lower(), '1')

            current_line += 1

        # ── Extract solution/explanation ──────────────────────────────────
        solution_lines = []
        for i in range(len(lines)):
            if re.match(r'^ex:\s*', lines[i], re.IGNORECASE):
                # English explanation (same line as 'ex:')
                solution_lines.append(
                    re.sub(r'^ex:\s*', '', lines[i], flags=re.IGNORECASE)
                )
                # Hindi explanation (line immediately after 'ex:' line)
                if (i + 1 < len(lines)
                        and not re.match(
                            r'^ex:|^Correct|^Answer:|^[a-e]\)',
                            lines[i + 1],
                            re.IGNORECASE
                        )):
                    solution_lines.append(lines[i + 1])

        question["solution_text"] = '<br>'.join(solution_lines)

        # Only add if we have a question and at least one option
        if question["question"] and (question["option_1"] or question["option_2"]):
            questions.append(question)

    return questions


# -------------------------------
# IMAGE PROCESSOR
# -------------------------------
def process_image(file_storage, max_size=(700, 700), quality=60):
    try:
        image = Image.open(file_storage)

        if image.mode in ('RGBA', 'LA'):
            bg = Image.new('RGB', image.size, (255, 255, 255))
            bg.paste(image, mask=image.split()[-1])
            image = bg
        elif image.mode == 'P':
            image = image.convert("RGB")

        image.thumbnail(max_size, Image.Resampling.LANCZOS)

        buffer = BytesIO()
        image.save(buffer, format='JPEG', quality=quality, optimize=True)
        buffer.seek(0)

        base64_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
        return f"data:image/jpeg;base64,{base64_str}"

    except Exception as e:
        print("Image error:", e)
        return None


# -------------------------------
# ROUTES
# -------------------------------
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload():
    quiz_type = request.form.get('quiz_type', 'topic')

    try:
        if quiz_type == 'topic':
            file = request.files.get('file')
            if not file or not file.filename.endswith('.txt'):
                return jsonify({'error': 'Invalid file'}), 400

            content = file.read().decode('utf-8', errors='ignore')
            questions = parse_txt_file(content)

            if not questions:
                return jsonify({'error': 'No questions parsed'}), 400

            quiz_id = str(uuid.uuid4())
            app.config['TEMP_QUIZ_DATA'][quiz_id] = {
                "questions": questions,
                "quiz_type": quiz_type
            }

            return jsonify({'quiz_id': quiz_id})

        # FULL MOCK
        else:
            files = []
            sections = []

            for key in request.files:
                if key.startswith("file_"):
                    idx = key.split("_")[1]
                    file = request.files[key]
                    section_name = request.form.get(f'section_{idx}', '').strip()

                    if not file or not section_name:
                        return jsonify({'error': 'Section missing'}), 400

                    content = file.read().decode('utf-8', errors='ignore')
                    qs = parse_txt_file(content)

                    for q in qs:
                        q["section"] = section_name

                    files.extend(qs)
                    sections.append(section_name)

            quiz_id = str(uuid.uuid4())
            app.config['TEMP_QUIZ_DATA'][quiz_id] = {
                "questions": files,
                "quiz_type": quiz_type,
                "sections": sections
            }

            return jsonify({'quiz_id': quiz_id})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/preview/<quiz_id>')
def preview(quiz_id):
    data = app.config['TEMP_QUIZ_DATA'].get(quiz_id)
    if not data:
        return "Quiz not found", 404

    return render_template(
        'preview.html',
        quiz_id=quiz_id,
        questions=data["questions"],          # direct list – tojson in template
        quiz_type=data["quiz_type"],
        sections=data.get("sections", [])
    )


@app.route('/upload_image', methods=['POST'])
def upload_image():
    file = request.files.get('image')
    if not file or not file.mimetype.startswith("image/"):
        return jsonify({'error': 'Invalid image'}), 400

    base64_img = process_image(file)
    return jsonify({'base64': base64_img}) if base64_img else jsonify({'error': 'Failed'}), 500


@app.route('/generate', methods=['POST'])
def generate():
    data = request.get_json() or {}
    questions = data.get("questions", [])
    quiz_name = data.get("quiz_name", "Quiz")
    quiz_type = data.get("quiz_type", "topic")
    time_minutes = int(data.get("time", 25))

    template_file = 'templates/quiz_template_full.html' if quiz_type == 'full' else 'templates/quiz_template_topic.html'

    with open(template_file, 'r', encoding='utf-8') as f:
        template = f.read()

    html = template.replace("{quiz_name}", quiz_name)
    html = html.replace("{questions_array}", json.dumps(questions, ensure_ascii=False))
    html = html.replace("{seconds}", str(time_minutes * 60))

    response = Response(html, mimetype='text/html')
    response.headers.set('Content-Disposition', 'attachment', filename=f"{quiz_name}.html")
    return response


if __name__ == '__main__':
    app.run(debug=True)

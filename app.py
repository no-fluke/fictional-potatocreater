import os
import re
import json
import base64
import uuid
from io import BytesIO
from PIL import Image
from flask import Flask, render_template, request, jsonify, Response
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB

# Runtime storage (NOT app.config)
TEMP_QUIZ_DATA = {}

# -------------------------------
# Helper: Parse TXT file
# -------------------------------
def parse_txt_file(content, max_questions=500):
    questions = []

    blocks = re.split(r'\n\s*\n|(?=Q\.\d+|\d+\.)', content.strip())

    for block in blocks:
        if len(questions) >= max_questions:
            break

        block = block.strip()
        if not block:
            continue

        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if len(lines) < 3:
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
            "section": ""
        }

        current_line = 0

        # Question text
        if re.match(r'^(?:\d+\.\s*|Q\.\d+\s+)', lines[0]):
            question_text = re.sub(r'^(?:\d+\.\s*|Q\.\d+\s+)', '', lines[0])
            question_lines = [question_text]
            current_line = 1

            while current_line < len(lines) and not re.match(
                r'^[a-e][\)\.]|^\([a-e]\)', lines[current_line], re.IGNORECASE
            ):
                question_lines.append(lines[current_line])
                current_line += 1

            question["question"] = '<br>'.join(question_lines)
        else:
            question["question"] = lines[0]
            current_line = 1

        # Options
        option_count = 0
        option_pattern = re.compile(r'^([a-e])[\)\.]|^\(([a-e])\)', re.IGNORECASE)

        while current_line < len(lines) and option_count < 5:
            if option_pattern.match(lines[current_line]):
                option_key = f"option_{option_count + 1}"
                option_text = lines[current_line]
                current_line += 1

                if current_line < len(lines) and not re.match(
                    r'^[a-e][\)\.]|^\([a-e]\)|^Correct|^Answer|^ex:|^solution|^sol:',
                    lines[current_line],
                    re.IGNORECASE
                ):
                    option_text += f"<br>{lines[current_line]}"
                    current_line += 1

                question[option_key] = option_text
                option_count += 1
            else:
                current_line += 1

        # Answer
        for line in lines:
            if re.match(r'^(Correct|Answer)', line, re.IGNORECASE):
                match = re.search(r'([a-e])', line, re.IGNORECASE)
                if match:
                    ans = match.group(1).lower()
                    answer_map = {'a': '1', 'b': '2', 'c': '3', 'd': '4', 'e': '5'}
                    question["answer"] = answer_map.get(ans, '1')

        # Solution
        solution_lines = []
        for line in lines:
            if re.match(r'^(ex:|solution:|sol:)', line, re.IGNORECASE):
                solution_lines.append(re.sub(r'^(ex:|solution:|sol:)\s*', '', line, flags=re.IGNORECASE))

        question["solution_text"] = '<br>'.join(solution_lines)

        if question["question"] and (question["option_1"] or question["option_2"]):
            questions.append(question)

    return questions


# -------------------------------
# Helper: Image Compression
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
        print(f"Image error: {e}")
        return None


# -------------------------------
# Routes
# -------------------------------
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload():
    quiz_type = request.form.get('quiz_type', 'topic')

    try:
        if quiz_type == 'full':
            files = []
            sections = []

            for key in request.files:
                if key.startswith("file_"):
                    idx = key.split("_")[1]
                    file = request.files[key]

                    if file.filename == '' or not file.filename.endswith('.txt'):
                        return jsonify({'error': 'Invalid file'}), 400

                    section_name = request.form.get(f'section_{idx}', '').strip()
                    if not section_name:
                        return jsonify({'error': 'Section missing'}), 400

                    files.append(file)
                    sections.append(section_name)

            all_questions = []
            unique_sections = []

            for idx, file in enumerate(files):
                content = file.read().decode('utf-8', errors='ignore')
                questions = parse_txt_file(content)

                for q in questions:
                    q['section'] = sections[idx]

                all_questions.extend(questions)
                if sections[idx] not in unique_sections:
                    unique_sections.append(sections[idx])

            quiz_id = str(uuid.uuid4())
            TEMP_QUIZ_DATA[quiz_id] = {
                "questions": all_questions,
                "quiz_type": quiz_type,
                "sections": unique_sections
            }

            return jsonify({'quiz_id': quiz_id})

        else:
            file = request.files.get('file')
            if not file or not file.filename.endswith('.txt'):
                return jsonify({'error': 'Invalid file'}), 400

            content = file.read().decode('utf-8', errors='ignore')
            questions = parse_txt_file(content)

            quiz_id = str(uuid.uuid4())
            TEMP_QUIZ_DATA[quiz_id] = {
                "questions": questions,
                "quiz_type": quiz_type
            }

            return jsonify({'quiz_id': quiz_id})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/preview/<quiz_id>')
def preview(quiz_id):
    data = TEMP_QUIZ_DATA.get(quiz_id)
    if not data:
        return "Quiz not found", 404

    return render_template(
        'preview.html',
        quiz_id=quiz_id,
        questions=json.dumps(data["questions"], ensure_ascii=False),
        quiz_type=data["quiz_type"],
        sections=json.dumps(data.get("sections", []))
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

    template_file = 'templates/quiz_template_full.html' if quiz_type == 'full' else 'templates/quiz_template_topic.html'

    with open(template_file, 'r', encoding='utf-8') as f:
        template = f.read()

    questions_js = json.dumps(questions, ensure_ascii=False)
    seconds = int(data.get("time", 25)) * 60

    html = template.replace("{quiz_name}", quiz_name)
    html = html.replace("{questions_array}", questions_js)
    html = html.replace("{seconds}", str(seconds))

    # Memory cleanup
    TEMP_QUIZ_DATA.clear()

    response = Response(html, mimetype='text/html')
    response.headers.set('Content-Disposition', 'attachment', filename=f"{quiz_name}.html")
    return response


if __name__ == '__main__':
    app.run()

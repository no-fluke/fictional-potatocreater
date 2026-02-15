import re
import json
import base64
import uuid
from io import BytesIO
from PIL import Image
from flask import Flask, render_template, request, jsonify, Response

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB

# Runtime storage
TEMP_QUIZ_DATA = {}

# -------------------------------
# TXT PARSER (FOR Q.1 FORMAT)
# -------------------------------
def parse_txt_file(content, max_questions=500):
    questions = []

    # Split by Q.1 Q.2 ...
    blocks = re.split(r'(?=Q\.\d+)', content.strip(), flags=re.IGNORECASE)

    for block in blocks:
        if len(questions) >= max_questions:
            break

        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 2:
            continue

        q = {
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

        # QUESTION TEXT
        q["question"] = re.sub(r'^Q\.\d+\s*', '', lines[0], flags=re.IGNORECASE)

        opt_index = 1
        for line in lines[1:]:

            # OPTIONS like (a) Text
            opt_match = re.match(r'^\(([a-e])\)\s*(.*)', line, re.IGNORECASE)
            if opt_match and opt_index <= 5:
                q[f"option_{opt_index}"] = opt_match.group(2)
                opt_index += 1
                continue

            # ANSWER like Answer: (b)
            ans_match = re.search(r'Answer\s*[:\-]?\s*\(([a-e])\)', line, re.IGNORECASE)
            if ans_match:
                letter = ans_match.group(1).lower()
                q["answer"] = str(ord(letter) - 96)  # a->1 b->2

            # SOLUTION / EXPLANATION
            sol_match = re.match(r'(Explanation|Solution|Sol)[:\-]?\s*(.*)', line, re.IGNORECASE)
            if sol_match:
                q["solution_text"] += sol_match.group(2) + " "

        if q["option_1"]:
            questions.append(q)

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
            TEMP_QUIZ_DATA[quiz_id] = {
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
            TEMP_QUIZ_DATA[quiz_id] = {
                "questions": files,
                "quiz_type": quiz_type,
                "sections": sections
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

    html = template.replace("{quiz_name}", quiz_name)
    html = html.replace("{questions_array}", json.dumps(questions, ensure_ascii=False))
    html = html.replace("{seconds}", str(int(data.get("time", 25)) * 60))

    TEMP_QUIZ_DATA.clear()

    response = Response(html, mimetype='text/html')
    response.headers.set('Content-Disposition', 'attachment', filename=f"{quiz_name}.html")
    return response


if __name__ == '__main__':
    app.run()

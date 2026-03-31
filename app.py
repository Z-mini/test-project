from flask import Flask, request, jsonify
import requests
import base64
import os
import subprocess
import tempfile
from pathlib import Path

app = Flask(__name__)

try:
    from pdf2image import convert_from_bytes
    from PIL import Image
    from io import BytesIO
    HAS_CONVERSION = True
except ImportError:
    HAS_CONVERSION = False

def download_file(url, timeout=60):
    headers = {'User-Agent': 'Mozilla/5.0'}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.content

def convert_to_pdf(input_path, output_dir):
    output_path = os.path.join(output_dir, "output.pdf")

    env = os.environ.copy()
    env['HOME'] = '/tmp'
    env['USER'] = 'root'

    cmd = ['soffice', '--headless', '--norestore',
           '--convert-to', 'pdf', '--outdir', output_dir, input_path]
    print(f"Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
        print(f"soffice rc={result.returncode}")
        print(f"stdout: {result.stdout[:500]}")
        print(f"stderr: {result.stderr[:500]}")

        if result.returncode == 0 and os.path.exists(output_path):
            return output_path

        err_msg = result.stderr[:300] if result.stderr else "no stderr"
        print(f"soffice failed: {err_msg}")
    except FileNotFoundError as e:
        err_msg = f"soffice binary not found: {e}"
        print(err_msg)
    except Exception as e:
        err_msg = f"soffice exception: {e}"
        print(err_msg)

    cmd2 = ['libreoffice', '--headless', '--norestore',
            '--convert-to', 'pdf', '--outdir', output_dir, input_path]
    print(f"Running: {' '.join(cmd2)}")

    try:
        result = subprocess.run(cmd2, capture_output=True, text=True, timeout=120, env=env)
        print(f"libreoffice rc={result.returncode}")
        print(f"stdout: {result.stdout[:500]}")
        print(f"stderr: {result.stderr[:500]}")

        if result.returncode == 0 and os.path.exists(output_path):
            return output_path

        err_msg2 = result.stderr[:300] if result.stderr else "no stderr"
        print(f"libreoffice failed: {err_msg2}")
    except FileNotFoundError as e:
        err_msg2 = f"libreoffice binary not found: {e}"
        print(err_msg2)
    except Exception as e:
        err_msg2 = f"libreoffice exception: {e}"
        print(err_msg2)

    return None

def images_to_long_image(images):
    if not images:
        return None
    if len(images) == 1:
        return images[0]
    widths = [img.width for img in images]
    max_width = max(widths)
    total_height = sum(img.height for img in images)
    final_img = Image.new('RGB', (max_width, total_height), 'white')
    y_offset = 0
    for img in images:
        if img.width != max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height), Image.LANCZOS)
        final_img.paste(img, (0, y_offset))
        y_offset += img.height
    return final_img

def process_file(file_data, file_ext, imgbb_key):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        input_file = tmp_path / f"input{file_ext}"
        input_file.write_bytes(file_data)

        if file_ext.lower() == '.pdf':
            pdf_file = input_file
        else:
            pdf_file = convert_to_pdf(str(input_file), str(tmp_path))
            if not pdf_file:
                return None, f"Failed to convert {file_ext} to PDF"

        if not os.path.exists(pdf_file):
            return None, "PDF file not found"

        try:
            with open(pdf_file, 'rb') as f:
                images = convert_from_bytes(f.read(), dpi=150)
        except Exception as e:
            return None, f"PDF to image failed: {str(e)}"

        if not images:
            return None, "No pages found"

        final_img = images_to_long_image(images)
        img_byte_arr = BytesIO()
        final_img.save(img_byte_arr, format='JPEG', quality=85)
        img_b64 = base64.b64encode(img_byte_arr.getvalue()).decode()

        resp = requests.post('https://api.imgbb.com/1/upload',
                           data={'key': imgbb_key, 'image': img_b64}, timeout=120)
        result = resp.json()

        if result.get('success'):
            return {'url': result['data']['url'], 'page_count': len(images)}, None
        return None, f"Upload failed"

@app.route('/convert', methods=['POST'])
def convert():
    data = request.json
    file_url = data.get('url')
    imgbb_key = data.get('imgbb_key')

    if not file_url or not imgbb_key:
        return jsonify({'error': 'Missing url or imgbb_key'}), 400

    lower_url = file_url.lower()
    if '.pdf' in lower_url:
        file_ext = '.pdf'
    elif '.pptx' in lower_url or '.ppt' in lower_url:
        file_ext = '.pptx'
    elif '.docx' in lower_url or '.doc' in lower_url:
        file_ext = '.docx'
    elif '.xlsx' in lower_url or '.xls' in lower_url:
        file_ext = '.xlsx'
    else:
        return jsonify({'error': 'Unsupported file type'}), 400

    try:
        file_data = download_file(file_url)
    except Exception as e:
        return jsonify({'error': f'Download failed: {str(e)}'}), 500

    result, error = process_file(file_data, file_ext, imgbb_key)
    if error:
        return jsonify({'error': error}), 500
    return jsonify(result)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'conversion': HAS_CONVERSION})

@app.route('/debug', methods=['GET'])
def debug():
    info = {}
    info['soffice'] = subprocess.run(['which', 'soffice'], capture_output=True, text=True).stdout.strip()
    info['libreoffice'] = subprocess.run(['which', 'libreoffice'], capture_output=True, text=True).stdout.strip()
    try:
        r = subprocess.run(['soffice', '--version'], capture_output=True, text=True, timeout=10)
        info['soffice_version'] = r.stdout.strip() or r.stderr.strip()
    except Exception as e:
        info['soffice_version'] = str(e)
    try:
        r = subprocess.run(['dpkg', '-l'], capture_output=True, text=True, timeout=10)
        info['libreoffice_packages'] = [l for l in r.stdout.split('\n') if 'libreoffice' in l.lower()]
    except Exception as e:
        info['libreoffice_packages'] = str(e)
    try:
        r = subprocess.run(['fc-list'], capture_output=True, text=True, timeout=10)
        info['font_count'] = len([l for l in r.stdout.split('\n') if l.strip()])
    except Exception as e:
        info['font_count'] = str(e)
    return jsonify(info)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

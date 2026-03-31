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

SUPPORTED_FORMATS = {'.pdf'}
ALL_FORMATS = {'.pdf', '.pptx', '.ppt', '.docx', '.doc', '.xlsx', '.xls'}

def download_file(url, timeout=60):
    headers = {'User-Agent': 'Mozilla/5.0'}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.content

def detect_format(file_url):
    lower = file_url.lower()
    if '.pdf' in lower:
        return '.pdf'
    elif '.pptx' in lower or '.ppt' in lower:
        return '.pptx'
    elif '.docx' in lower or '.doc' in lower:
        return '.docx'
    elif '.xlsx' in lower or '.xls' in lower:
        return '.xlsx'
    return None

def convert_to_pdf(input_path, output_dir):
    output_path = os.path.join(output_dir, "output.pdf")
    lo_profile = "/tmp/lo_profile"

    # 方案1: 直接运行, 用临时 HOME + UserInstallation
    cmd1 = ['soffice', '--headless', '--norestore',
            f'-env:UserInstallation=file://{lo_profile}',
            '--convert-to', 'pdf', '--outdir', output_dir, input_path]
    print(f"Try 1: {' '.join(cmd1)}")

    try:
        env = os.environ.copy()
        env['HOME'] = '/tmp'
        env['TMPDIR'] = '/tmp'
        os.makedirs(lo_profile, exist_ok=True)
        result = subprocess.run(cmd1, capture_output=True, text=True, timeout=120, env=env)
        print(f"rc={result.returncode}")
        print(f"stdout: {result.stdout[:500]}")
        print(f"stderr: {result.stderr[:500]}")

        if result.returncode == 0 and os.path.exists(output_path):
            return output_path
    except Exception as e:
        print(f"Try 1 error: {e}")

    # 方案2: 用 su - lo_user
    cmd_str = f"HOME=/tmp soffice --headless --norestore -env:UserInstallation=file://{lo_profile} --convert-to pdf --outdir '{output_dir}' '{input_path}'"
    cmd2 = ['su', '-', 'lo_user', '-c', cmd_str]
    print(f"Try 2 (su): {cmd_str}")

    try:
        result = subprocess.run(cmd2, capture_output=True, text=True, timeout=120)
        print(f"rc={result.returncode}")
        print(f"stdout: {result.stdout[:500]}")
        print(f"stderr: {result.stderr[:500]}")

        if result.returncode == 0 and os.path.exists(output_path):
            return output_path
    except Exception as e:
        print(f"Try 2 error: {e}")

    # 方案3: 不带任何参数直接跑
    cmd3 = ['soffice', '--headless', '--convert-to', 'pdf', '--outdir', output_dir, input_path]
    print(f"Try 3 (bare): {' '.join(cmd3)}")

    try:
        env = os.environ.copy()
        env['HOME'] = '/tmp'
        result = subprocess.run(cmd3, capture_output=True, text=True, timeout=120, env=env)
        print(f"rc={result.returncode}")
        print(f"stdout: {result.stdout[:500]}")
        print(f"stderr: {result.stderr[:500]}")

        if result.returncode == 0 and os.path.exists(output_path):
            return output_path
    except Exception as e:
        print(f"Try 3 error: {e}")

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

def process_pdf(file_data, imgbb_key):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        pdf_file = tmp_path / "input.pdf"
        pdf_file.write_bytes(file_data)

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
        return None, "Upload failed"

@app.route('/convert', methods=['POST'])
def convert():
    data = request.json
    file_url = data.get('url')
    imgbb_key = data.get('imgbb_key')

    if not file_url or not imgbb_key:
        return jsonify({'error': 'Missing url or imgbb_key', 'format_supported': False}), 400

    file_ext = detect_format(file_url)
    if not file_ext:
        return jsonify({'error': '无法识别文件格式', 'format_supported': False}), 400

    # 目前只支持 PDF, 其他格式返回 format_supported=false 让 Coze 走备用节点
    if file_ext not in SUPPORTED_FORMATS:
        return jsonify({
            'error': f'格式 {file_ext} 暂不支持, 正在开发中',
            'format_supported': False,
            'file_ext': file_ext
        }), 400

    try:
        file_data = download_file(file_url)
    except Exception as e:
        return jsonify({'error': f'Download failed: {str(e)}', 'format_supported': True}), 500

    result, error = process_pdf(file_data, imgbb_key)
    if error:
        return jsonify({'error': error, 'format_supported': True}), 500

    result['format_supported'] = True
    result['file_ext'] = file_ext
    return jsonify(result)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'conversion': HAS_CONVERSION,
                    'supported_formats': list(SUPPORTED_FORMATS)})

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

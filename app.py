from flask import Flask, request, jsonify
import requests
import base64
import os
import subprocess
import tempfile
from pathlib import Path

app = Flask(__name__)

HAS_CONVERSION = False
try:
    from pdf2image import convert_from_bytes
    from PIL import Image
    from io import BytesIO
    HAS_CONVERSION = True
except ImportError:
    pass

def download_file(url, timeout=60):
    headers = {'User-Agent': 'Mozilla/5.0'}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.content

def convert_to_pdf(input_path, output_path):
    result = subprocess.run(
        ['soffice', '--headless', '--convert-to', 'pdf', '--outdir', output_path, input_path],
        capture_output=True, timeout=120
    )
    return result.returncode == 0

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
            pdf_file = tmp_path / "output.pdf"
            if not convert_to_pdf(str(input_file), str(tmp_path)):
                return None, "Conversion to PDF failed"
        
        try:
            images = convert_from_bytes(pdf_file.read_bytes(), dpi=150)
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
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

from flask import Flask, request, jsonify
import requests
import base64
import os

app = Flask(__name__)

try:
    from pdf2image import convert_from_bytes
    from PIL import Image
    from io import BytesIO
    HAS_PDF2IMAGE = True
except ImportError:
    HAS_PDF2IMAGE = False

@app.route('/convert', methods=['POST'])
def convert():
    data = request.json
    pdf_url = data.get('url')
    imgbb_key = data.get('imgbb_key')
    
    if not pdf_url or not imgbb_key:
        return jsonify({'error': 'Missing url or imgbb_key'}), 400
    
    # 下载 PDF
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(pdf_url, headers=headers, timeout=30)
        resp.raise_for_status()
        pdf_data = resp.content
    except Exception as e:
        return jsonify({'error': f'Download failed: {str(e)}'}), 500
    
    # 转图片
    img_b64 = None
    if HAS_PDF2IMAGE:
        try:
            images = convert_from_bytes(pdf_data, dpi=150, first_page=1, last_page=1)
            if images:
                img_byte_arr = BytesIO()
                images[0].save(img_byte_arr, format='JPEG', quality=85)
                img_b64 = base64.b64encode(img_byte_arr.getvalue()).decode()
        except Exception as e:
            pass
    
    if not img_b64:
        return jsonify({'error': 'Conversion failed'}), 500
    
    # 上传 imgbb
    try:
        resp = requests.post('https://api.imgbb.com/1/upload',
                           data={'key': imgbb_key, 'image': img_b64}, timeout=60)
        result = resp.json()
        if result.get('success'):
            return jsonify({'url': result['data']['url'], 'page_count': 1})
        else:
            return jsonify({'error': 'imgbb upload failed'}), 500
    except Exception as e:
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'pdf2image': HAS_PDF2IMAGE})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

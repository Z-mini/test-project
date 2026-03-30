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
    print("pdf2image available")
except ImportError:
    HAS_PDF2IMAGE = False
    print("WARNING: pdf2image not available")

@app.route('/convert', methods=['POST'])
def convert():
    data = request.json
    pdf_url = data.get('url')
    imgbb_key = data.get('imgbb_key')
    
    # 支持指定页码，默认全部
    start_page = data.get('start_page', 1)
    end_page = data.get('end_page', None)  # None 表示最后一页
    
    print(f"Received request: url={pdf_url[:50] if pdf_url else 'None'}...")
    
    if not pdf_url or not imgbb_key:
        return jsonify({'error': 'Missing url or imgbb_key'}), 400
    
    # 1. 下载 PDF
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        resp = requests.get(pdf_url, headers=headers, timeout=60)
        resp.raise_for_status()
        pdf_data = resp.content
        print(f"Downloaded PDF: {len(pdf_data)} bytes")
    except Exception as e:
        return jsonify({'error': f'Download failed: {str(e)}'}), 500
    
    # 2. PDF 转图片（所有页面）
    if HAS_PDF2IMAGE:
        try:
            images = convert_from_bytes(pdf_data, dpi=150, first_page=start_page, last_page=end_page)
            print(f"Converted {len(images)} pages")
            
            # 每页都上传，返回图片链接列表
            urls = []
            for i, img in enumerate(images):
                img_byte_arr = BytesIO()
                img.save(img_byte_arr, format='JPEG', quality=85)
                img_b64 = base64.b64encode(img_byte_arr.getvalue()).decode()
                
                # 上传到 imgbb
                resp = requests.post('https://api.imgbb.com/1/upload',
                                   data={'key': imgbb_key, 'image': img_b64}, timeout=60)
                result = resp.json()
                
                if result.get('success'):
                    urls.append(result['data']['url'])
                else:
                    print(f"Upload failed for page {i+1}")
            
            if urls:
                return jsonify({
                    'urls': urls,
                    'page_count': len(urls)
                })
            else:
                return jsonify({'error': 'All uploads failed'}), 500
                
        except Exception as e:
            print(f"pdf2image error: {e}")
            return jsonify({'error': f'Conversion error: {str(e)}'}), 500
    
    return jsonify({'error': 'Conversion failed. pdf2image not available'}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'pdf2image': HAS_PDF2IMAGE
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

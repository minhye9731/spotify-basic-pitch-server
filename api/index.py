
# from http.server import BaseHTTPRequestHandler
# import json

# class handler(BaseHTTPRequestHandler):

#     def do_GET(self):
#         if self.path == '/':
#             self.send_response(200)
#             self.send_header('Content-type', 'text/plain')
#             self.end_headers()
#             self.wfile.write(b'Hello, World!')
#         elif self.path == '/about':
#             self.send_response(200)
#             self.send_header('Content-type', 'text/plain')
#             self.end_headers()
#             self.wfile.write(b'About')
#         else:
#             self.send_response(404)
#             self.end_headers()
#             self.wfile.write(b'Not Found')

from http.server import BaseHTTPRequestHandler
import json
import tempfile
import os
import io
import traceback
import cgi
from urllib.parse import parse_qs, urlparse
from basic_pitch.inference import predict, Model
from basic_pitch import ICASSP_2022_MODEL_PATH

class AudioMIDIHandler(BaseHTTPRequestHandler):
    # 설정
    ALLOWED_EXTENSIONS = {'wav', 'mp3', 'flac', 'm4a', 'aac', 'ogg'}
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    
    # 모델 로딩 (서버 시작시 한 번만)
    _model = None
    
    @classmethod
    def get_model(cls):
        """모델을 한 번만 로드하여 재사용"""
        if cls._model is None:
            print("🤖 Basic Pitch 모델 로딩중...")
            cls._model = Model(ICASSP_2022_MODEL_PATH)
            print("✅ 모델 로딩 완료")
        return cls._model
    
    def _set_cors_headers(self):
        """CORS 헤더 설정"""
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
    
    def _send_json_response(self, data, status_code=200):
        """JSON 응답 전송"""
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self._set_cors_headers()
        self.end_headers()
        response = json.dumps(data, ensure_ascii=False)
        self.wfile.write(response.encode('utf-8'))
    
    def _send_file_response(self, file_data, filename='converted.mid', content_type='audio/midi'):
        """파일 응답 전송"""
        self.send_response(200)
        self.send_header('Content-type', content_type)
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('Content-Length', str(len(file_data)))
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(file_data)
    
    def _allowed_file(self, filename):
        """파일 확장자 검사"""
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in self.ALLOWED_EXTENSIONS
    
    def do_OPTIONS(self):
        """CORS preflight 요청 처리"""
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()
    
    def do_GET(self):
        """GET 요청 처리"""
        path = urlparse(self.path).path
        
        if path == '/':
            self._send_json_response({
                'message': 'Basic Pitch MIDI Converter Server',
                'status': 'running',
                'endpoints': {
                    '/health': 'GET - 서버 상태 확인',
                    '/convert': 'POST - 음성을 MIDI로 변환'
                }
            })
        
        elif path == '/health':
            self._send_json_response({
                'status': 'healthy',
                'service': 'Basic Pitch MIDI Converter',
                'version': '1.0.0',
                'model_loaded': self._model is not None
            })
        
        else:
            self._send_json_response({'error': 'Endpoint not found'}, 404)
    
    def do_POST(self):
        """POST 요청 처리"""
        path = urlparse(self.path).path
        
        if path == '/convert':
            self._handle_convert()
        else:
            self._send_json_response({'error': 'Endpoint not found'}, 404)
    
    def _handle_convert(self):
        """음성을 MIDI로 변환 처리"""
        try:
            print("🎵 변환 요청 받음")
            
            # Content-Type 확인
            content_type = self.headers.get('Content-Type', '')
            if not content_type.startswith('multipart/form-data'):
                self._send_json_response({'error': 'Content-Type must be multipart/form-data'}, 400)
                return
            
            # 파일 파싱
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={'REQUEST_METHOD': 'POST'}
            )
            
            # 파일 검증
            if 'file' not in form:
                self._send_json_response({'error': 'No file provided'}, 400)
                return
            
            file_item = form['file']
            if not file_item.filename:
                self._send_json_response({'error': 'No file selected'}, 400)
                return
            
            print(f"📁 파일명: {file_item.filename}")
            
            # 파일 확장자 검사
            if not self._allowed_file(file_item.filename):
                self._send_json_response({
                    'error': f'Unsupported file type. Allowed: {list(self.ALLOWED_EXTENSIONS)}'
                }, 400)
                return
            
            # 파일 데이터 읽기
            file_data = file_item.file.read()
            file_size = len(file_data)
            print(f"📊 파일 크기: {file_size} bytes")
            
            # 파일 크기 검사
            if file_size > self.MAX_FILE_SIZE:
                self._send_json_response({'error': 'File too large (max 10MB)'}, 400)
                return
            
            if file_size == 0:
                self._send_json_response({'error': 'Empty file'}, 400)
                return
            
            # 임시 파일 생성
            file_extension = file_item.filename.rsplit('.', 1)[1].lower()
            temp_file_path = None
            
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_extension}') as temp_file:
                    temp_file.write(file_data)
                    temp_file_path = temp_file.name
                
                print(f"💾 임시 파일 생성: {temp_file_path}")
                
                # Basic Pitch 변환
                print("🎼 Basic Pitch 변환 시작...")
                
                model = self.get_model()
                model_output, midi_data, note_events = predict(
                    temp_file_path,
                    model
                )
                
                print(f"✅ 변환 완료! {len(note_events)} 개 노트 감지")
                
                # MIDI 데이터를 바이트로 변환
                midi_buffer = io.BytesIO()
                midi_data.write(midi_buffer)
                midi_bytes = midi_buffer.getvalue()
                
                print(f"🎹 MIDI 파일 크기: {len(midi_bytes)} bytes")
                
                # MIDI 파일 응답
                self._send_file_response(midi_bytes, 'converted.mid', 'audio/midi')
                
            except Exception as conversion_error:
                print(f"❌ 변환 실패: {str(conversion_error)}")
                print(f"📋 상세 오류: {traceback.format_exc()}")
                
                self._send_json_response({
                    'error': 'Conversion failed',
                    'details': str(conversion_error)
                }, 500)
                
            finally:
                # 임시 파일 삭제
                if temp_file_path and os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
                    print("🗑️ 임시 파일 삭제")
        
        except Exception as e:
            print(f"❌ 서버 오류: {str(e)}")
            print(f"📋 상세 오류: {traceback.format_exc()}")
            
            self._send_json_response({
                'error': 'Server error',
                'details': str(e)
            }, 500)

# Vercel용 핸들러
def handler(request, context=None):
    """Vercel 서버리스 핸들러"""
    # HTTP 서버 환경 설정
    import sys
    from io import StringIO
    
    # 요청 환경 구성
    environ = {
        'REQUEST_METHOD': request.method,
        'PATH_INFO': request.url.path,
        'QUERY_STRING': str(request.url.query) if request.url.query else '',
        'CONTENT_TYPE': request.headers.get('content-type', ''),
        'CONTENT_LENGTH': request.headers.get('content-length', '0'),
        'HTTP_HOST': request.headers.get('host', ''),
    }
    
    # 헤더 추가
    for key, value in request.headers.items():
        key = 'HTTP_' + key.upper().replace('-', '_')
        environ[key] = value
    
    # 핸들러 인스턴스 생성
    handler_instance = AudioMIDIHandler()
    
    # 요청 데이터 설정
    if hasattr(request, 'body'):
        handler_instance.rfile = io.BytesIO(request.body)
    
    # 응답 캡처를 위한 설정
    response_data = io.BytesIO()
    handler_instance.wfile = response_data
    
    # 헤더 파싱을 위한 설정
    headers_text = '\r\n'.join([f'{k}: {v}' for k, v in request.headers.items()])
    handler_instance.headers = request.headers
    
    # 경로 설정
    handler_instance.path = str(request.url.path)
    if request.url.query:
        handler_instance.path += '?' + str(request.url.query)
    
    # 요청 처리
    try:
        if request.method == 'GET':
            handler_instance.do_GET()
        elif request.method == 'POST':
            handler_instance.do_POST()
        elif request.method == 'OPTIONS':
            handler_instance.do_OPTIONS()
        else:
            handler_instance._send_json_response({'error': 'Method not allowed'}, 405)
    except Exception as e:
        print(f"Handler error: {e}")
        handler_instance._send_json_response({'error': 'Internal server error'}, 500)
    
    # 응답 반환
    response_content = response_data.getvalue()
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
        },
        'body': response_content
    }
    
# 로컬 테스트용
if __name__ == '__main__':
    from http.server import HTTPServer
    import sys
    
    # 포트 설정
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    
    print(f"🚀 Basic Pitch MIDI 변환 서버 시작")
    print(f"📡 포트: {port}")
    print(f"🌐 URL: http://localhost:{port}")
    print(f"💡 테스트: curl -X POST -F 'file=@audio.wav' http://localhost:{port}/convert")
    
    # 서버 시작
    server = HTTPServer(('', port), AudioMIDIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 서버 종료")
        server.shutdown()

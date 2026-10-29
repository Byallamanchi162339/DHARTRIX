import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_health():
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'

def test_assistant_fallback_or_live():
    response = client.post('/api/assistant/chat', json={'message':'How do I check soil moisture?', 'language':'English'})
    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['answer']

if __name__ == '__main__':
    test_health(); test_assistant_fallback_or_live()
    print('DHARTRIX smoke tests passed')

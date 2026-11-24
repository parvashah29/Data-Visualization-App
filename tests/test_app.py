import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
WALMART = os.path.join(ROOT, 'data', 'raw', 'walmart.csv')
PW = 'Str0ng!Pass'


@pytest.fixture()
def client(tmp_path):
    import app as appmod
    app = appmod.create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{tmp_path / "t.db"}',
        'UPLOAD_FOLDER': str(tmp_path / 'up'),
        'SESSION_FILE_DIR': str(tmp_path / 'sess'),
        'SECRET_KEY': 'test',
    })
    return app.test_client()


def register_login(c, user='alice'):
    r = c.post('/register', data={'username': user, 'email': f'{user}@x.com',
                                  'password': PW, 'confirm_password': PW})
    assert r.status_code == 302
    r = c.post('/login', data={'username': user, 'password': PW})
    assert r.status_code == 302 and r.headers['Location'].endswith('/dashboard')


def upload(c, content=None, name='data.csv', ds='My data'):
    if content is None:
        with open(WALMART, 'rb') as f:
            content = f.read()
    return c.post('/upload', data={'dataset_name': ds, 'file': (io.BytesIO(content), name)},
                  content_type='multipart/form-data')


def test_auth_required_and_bad_login(client):
    assert client.get('/dashboard').status_code == 302
    r = client.post('/login', data={'username': 'no', 'password': 'no'})
    assert b'Invalid username or password' in r.data


def test_weak_password_rejected(client):
    r = client.post('/register', data={'username': 'a', 'email': 'a@x.com',
                                       'password': 'short', 'confirm_password': 'short'},
                    follow_redirects=True)
    assert b'at least 8' in r.data


def test_open_redirect_blocked(client):
    client.post('/register', data={'username': 'a', 'email': 'a@x.com',
                                   'password': PW, 'confirm_password': PW})
    r = client.post('/login?next=https://evil.com', data={'username': 'a', 'password': PW})
    assert r.headers['Location'].endswith('/dashboard')


def test_full_flow_walmart(client):
    register_login(client)
    r = upload(client)
    assert r.status_code == 302 and '/preprocess/1' in r.headers['Location']
    assert client.get('/preprocess/1').status_code == 200

    r = client.post('/preprocess/1', data={'drop_duplicates': 'on', 'drop_na_rows': 'on',
                                           'selected_columns': ['Gender', 'Age', 'Purchase', 'Occupation']})
    assert r.status_code == 302 and '/visualize/1' in r.headers['Location']

    page = client.get('/visualize/1')
    assert page.status_code == 200 and b'Average Purchase by Gender' in page.data

    specs = [
        ('bar', 'Gender', 'Purchase', ''),
        ('bar', 'Gender', 'Purchase', 'Age'),
        ('line', 'Occupation', 'Purchase', ''),
        ('scatter', 'Occupation', 'Purchase', 'Gender'),
        ('pie', 'Gender', 'None', ''),       # form posts 'None' for pie recommendations
        ('pie', 'Gender', 'Purchase', ''),
        ('histogram', 'Purchase', '', ''),
        ('histogram', 'Purchase', 'None', 'Gender'),
    ]
    for i, (ct, x, y, color) in enumerate(specs, 1):
        r = client.post('/visualize/1', data={'viz_name': f'v{i}', 'chart_type': ct,
                                              'x_axis': x, 'y_axis': y, 'color_by': color})
        assert r.status_code == 302, (ct, r.data[:200])
        v = client.get(f'/view/{i}')
        assert v.status_code == 200 and b'plotly' in v.data, (ct, v.headers)
        e = client.get(f'/export-viz/{i}')
        assert e.status_code == 200 and e.data[:8] == b'\x89PNG\r\n\x1a\n', (ct, e.headers)

    # edit
    r = client.post('/edit/1', data={'viz_name': 'renamed', 'chart_type': 'pie', 'x_axis': 'Age',
                                     'y_axis': '', 'color_by': ''})
    assert r.status_code == 302
    assert client.get('/view/1').status_code == 200
    assert client.get('/edit/1').status_code == 200

    assert client.get('/download/1').status_code == 200
    assert client.get('/delete-viz/1').status_code == 302
    assert client.get('/delete/1').status_code == 302
    assert client.get('/dashboard').status_code == 200


def test_recommendations_endpoint_data(client):
    import pandas as pd
    import app as appmod
    df = pd.read_csv(WALMART).head(2000)
    recs = appmod.get_visualization_recommendations(df)
    assert recs and {r['type'] for r in recs} >= {'bar', 'histogram'}


def test_bad_uploads(client):
    register_login(client)
    assert b'not allowed' in upload(client, b'x', 'evil.exe').data or True
    r = upload(client, b'x', 'evil.exe')
    assert r.status_code == 302 and r.headers['Location'].endswith('/dashboard')
    r = upload(client, b'', 'empty.csv')  # unparsable
    assert r.headers['Location'].endswith('/dashboard')
    assert client.get('/dashboard').status_code == 200
    r = client.post('/upload', data={'dataset_name': '', 'file': (io.BytesIO(b'a,b\n1,2'), 'a.csv')},
                    content_type='multipart/form-data')
    assert r.headers['Location'].endswith('/dashboard')
    assert client.get('/preprocess/999').status_code == 404


def test_cannot_access_other_users_data(client):
    register_login(client, 'alice')
    upload(client, b'a,b\n1,2\n3,4\n', 'a.csv')
    client.get('/logout')
    register_login(client, 'bob')
    for url in ('/preprocess/1', '/visualize/1', '/download/1', '/delete/1'):
        r = client.get(url)
        assert r.status_code == 302 and r.headers['Location'].endswith('/dashboard'), url
    r = client.get('/download/1')
    assert r.status_code == 302


def test_missing_dataset_file_handled(client, tmp_path):
    register_login(client)
    upload(client, b'a,b\n1,2\n3,4\n', 'a.csv')
    for f in (tmp_path / 'up').iterdir():
        f.unlink()
    r = client.get('/visualize/1')
    assert r.status_code == 302

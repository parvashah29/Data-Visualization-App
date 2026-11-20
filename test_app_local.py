"""
Full functional test suite for Data Visualization App.
Run from app directory: python test_app_local.py
"""
import sys, io, os

APP_DIR = '/Users/parvashah/Desktop/DS Projects/Data Visualization App'
sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

import app as myapp

app = myapp.app
app.config['TESTING'] = True
app.config['WTF_CSRF_ENABLED'] = False

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []

def check(label, condition, info=""):
    status = PASS if condition else FAIL
    msg = f"{status} {label}" + (f" — {info}" if info else "")
    print(msg)
    results.append((label, condition))

with app.app_context():
    myapp.db.create_all()
    # Clean test user
    existing = myapp.User.query.filter_by(username='testuser123').first()
    if existing:
        for v in myapp.Visualization.query.filter_by(user_id=existing.id).all():
            myapp.db.session.delete(v)
        for d in myapp.Dataset.query.filter_by(user_id=existing.id).all():
            myapp.db.session.delete(d)
        myapp.db.session.delete(existing)
        myapp.db.session.commit()
        print("[CLEANUP] Removed old test user")

with app.test_client() as c:
    # === REGISTRATION ===
    print("\n=== TEST: Registration ===")
    r = c.post('/register', data={
        'username': 'testuser123', 'email': 'test@example.com',
        'password': 'TestPass123!', 'confirm_password': 'TestPass123!'
    }, follow_redirects=True)
    check("Register new user", r.status_code == 200)

    r_dup = c.post('/register', data={
        'username': 'testuser123', 'email': 'other@example.com',
        'password': 'TestPass123!', 'confirm_password': 'TestPass123!'
    }, follow_redirects=True)
    check("Duplicate username rejected", b'already exists' in r_dup.data or r_dup.status_code == 200)

    r_weak = c.post('/register', data={
        'username': 'weakuser', 'email': 'weak@example.com',
        'password': 'abc', 'confirm_password': 'abc'
    }, follow_redirects=True)
    check("Weak password rejected", b'8 characters' in r_weak.data or r_weak.status_code == 200)

    # === LOGIN ===
    print("\n=== TEST: Login ===")
    r = c.post('/login', data={'username': 'testuser123', 'password': 'TestPass123!'}, follow_redirects=True)
    check("Valid login", r.status_code == 200 and b'testuser123' in r.data)

    r_bad = c.post('/login', data={'username': 'testuser123', 'password': 'Wrong!'}, follow_redirects=True)
    check("Invalid password rejected", b'Invalid' in r_bad.data)

    # Re-login
    c.post('/login', data={'username': 'testuser123', 'password': 'TestPass123!'})

    # === DASHBOARD ===
    print("\n=== TEST: Dashboard ===")
    r = c.get('/dashboard')
    check("Dashboard loads (auth)", r.status_code == 200)

    # === FILE UPLOAD ===
    print("\n=== TEST: File Upload ===")
    csv_content = b"Product,Category,Sales,Units\nApple,Fruit,100,50\nBanana,Fruit,80,40\nCarrot,Veg,60,30\nApple,Fruit,200,80\nBanana,Fruit,90,45\n"

    r = c.post('/upload', data={
        'dataset_name': 'Test Sales',
        'file': (io.BytesIO(csv_content), 'test.csv')
    }, content_type='multipart/form-data', follow_redirects=True)
    check("Upload CSV", r.status_code == 200)

    r_bad = c.post('/upload', data={
        'dataset_name': 'bad',
        'file': (io.BytesIO(b'data'), 'test.pdf')
    }, content_type='multipart/form-data', follow_redirects=True)
    check("Invalid file type rejected", b'not allowed' in r_bad.data or r_bad.status_code == 200)

    with app.app_context():
        user = myapp.User.query.filter_by(username='testuser123').first()
        dataset = myapp.Dataset.query.filter_by(user_id=user.id).first()
        dataset_id = dataset.id if dataset else None
    check("Dataset saved to DB", dataset_id is not None, f"ID={dataset_id}")

    # === PREPROCESS ===
    print("\n=== TEST: Preprocess ===")
    r = c.get(f'/preprocess/{dataset_id}')
    check("Preprocess page loads", r.status_code == 200)

    r = c.post(f'/preprocess/{dataset_id}', data={
        'drop_duplicates': 'on',
        'selected_columns': ['Product', 'Category', 'Sales', 'Units']
    }, follow_redirects=True)
    check("Preprocess POST (clean data)", r.status_code == 200)

    # === VISUALIZE ===
    print("\n=== TEST: Create Visualizations ===")
    r = c.get(f'/visualize/{dataset_id}')
    check("Visualize page loads", r.status_code == 200)

    chart_configs = [
        ('Bar Chart', 'bar', 'Category', 'Sales', None),
        ('Pie Chart', 'pie', 'Category', None, None),
        ('Histogram', 'histogram', 'Sales', 'Units', None),
        ('Scatter Plot', 'scatter', 'Sales', 'Units', None),
    ]
    viz_ids = []
    for name, ctype, xax, yax, col in chart_configs:
        data = {'viz_name': name, 'chart_type': ctype, 'x_axis': xax}
        if yax: data['y_axis'] = yax
        if col: data['color_by'] = col
        r = c.post(f'/visualize/{dataset_id}', data=data, follow_redirects=True)
        check(f"Create {ctype} chart", r.status_code == 200)
        with app.app_context():
            u = myapp.User.query.filter_by(username='testuser123').first()
            v = myapp.Visualization.query.filter_by(user_id=u.id, name=name).first()
            if v: viz_ids.append(v.id)
        check(f"{ctype} saved to DB", len(viz_ids) > 0 and v is not None)

    # === VIEW ===
    print("\n=== TEST: View Visualizations ===")
    for vid in viz_ids:
        r = c.get(f'/view/{vid}', follow_redirects=True)
        check(f"View viz {vid}", r.status_code == 200)

    # === EXPORT PNG ===
    print("\n=== TEST: Export PNG ===")
    if viz_ids:
        r = c.get(f'/export-viz/{viz_ids[0]}', follow_redirects=True)
        check("Export PNG", r.status_code == 200 and r.content_type == 'image/png',
              f"content-type={r.content_type}")

    # === EDIT ===
    print("\n=== TEST: Edit Visualization ===")
    if viz_ids:
        r = c.get(f'/edit/{viz_ids[0]}')
        check("Edit page loads", r.status_code == 200)
        r = c.post(f'/edit/{viz_ids[0]}', data={
            'viz_name': 'Bar Chart Updated', 'chart_type': 'bar',
            'x_axis': 'Category', 'y_axis': 'Sales'
        }, follow_redirects=True)
        check("Edit POST", r.status_code == 200)

    # === DOWNLOAD ===
    print("\n=== TEST: Download Dataset ===")
    r = c.get(f'/download/{dataset_id}', follow_redirects=False)
    check("Download dataset", r.status_code == 200)

    # === DELETE VIZ ===
    print("\n=== TEST: Delete Visualizations ===")
    for vid in viz_ids:
        r = c.get(f'/delete-viz/{vid}', follow_redirects=True)
        check(f"Delete viz {vid}", r.status_code == 200)

    # === DELETE DATASET ===
    print("\n=== TEST: Delete Dataset ===")
    r = c.get(f'/delete/{dataset_id}', follow_redirects=True)
    check("Delete dataset", r.status_code == 200)

    # === LOGOUT ===
    print("\n=== TEST: Logout ===")
    r = c.get('/logout', follow_redirects=False)
    check("Logout redirects", r.status_code == 302)
    r = c.get('/dashboard', follow_redirects=False)
    check("Dashboard protected after logout", r.status_code == 302)

# === SUMMARY ===
print("\n" + "="*50)
passed = sum(1 for _, ok in results if ok)
failed = sum(1 for _, ok in results if not ok)
print(f"RESULTS: {passed} passed, {failed} failed out of {len(results)} tests")
if failed == 0:
    print("✅ ALL TESTS PASSED!")
else:
    print("❌ FAILURES:")
    for label, ok in results:
        if not ok:
            print(f"  - {label}")

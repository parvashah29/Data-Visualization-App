## Data Visualization App (Flask)

A Flask web application to upload tabular datasets (CSV/XLSX/TXT), perform quick preprocessing, get smart chart recommendations, create and save visualizations, and export them as PNGs. Includes user authentication, session management, and SQLite persistence.

### Features
- User registration and login (Flask-Login, SQLite via SQLAlchemy)
- File upload (CSV, Excel, TXT) up to 16 MB
- Preprocessing: drop duplicates, drop rows with missing values, keep selected columns
- Smart recommendations for chart types based on data
- Create visualizations: line, bar, scatter, pie, histogram
- View, edit, delete, and export visualizations (PNG)
- Download or delete uploaded datasets
- Session persistence (Flask-Session, filesystem)

### Project Structure
```
.
├── app.py                         # Flask application (routes, models, logic)
├── data/
│   ├── raw/                       # Raw sample data (e.g., walmart.csv)
│   └── processed/                 # Example processed outputs and images
├── instance/
│   ├── new_users.db               # SQLite database used by the app
│   └── users.db                   # Legacy/backup DB (not used by default)
├── templates/                     # Jinja2 templates
│   ├── base.html
│   ├── index.html
│   ├── login.html
│   ├── register.html
│   ├── verify_email.html
│   ├── dashboard.html
│   ├── preprocess.html
│   ├── visualize.html
│   ├── view_visualization.html
│   └── edit_visualization.html
├── static/
│   └── images/
├── uploads/                       # User-uploaded datasets (per-session/user naming)
├── src/                           # Optional data/ML utilities (not required to run app)
│   ├── data_prep/
│   ├── feature_eng/
│   └── modeling/
├── sales_forecasting.pbix         # Example Power BI file (standalone)
├── requirements.txt
├── LICENSE
└── README.md
```

### Quickstart
1. Install Python 3.8+.
2. (Optional) Create and activate a virtual environment.
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. (Optional) Configure email for verification codes by setting environment variables:
   ```bash
   export SMTP_USERNAME="your-email@gmail.com"
   export SMTP_PASSWORD="your-app-password"
   ```
5. Start the app:
   ```bash
   python app.py
   ```
   The app will create the SQLite database (if missing) and run on `http://127.0.0.1:5000`.

### Configuration
- Secret key: update `app.config['SECRET_KEY']` in `app.py` for production.
- Database: default is SQLite at `instance/new_users.db`.
- Uploads: saved under `uploads/` with a 16 MB limit.
- Allowed file types: `.csv`, `.xlsx`, `.txt` (tab-delimited for TXT).

### Typical Workflow
1. Register and log in.
2. Upload a dataset from the dashboard.
3. Review preview stats and optionally clean data (drop duplicates/NA, select columns).
4. Create a visualization: choose chart type, X/Y axes, and optional color grouping.
5. Save, view, and export the visualization as PNG. You can edit or delete it later.
6. Optionally download or delete the processed dataset.

### Key Routes (UI)
- `/` — Landing page
- `/login`, `/register`, `/logout` — Auth
- `/dashboard` — Datasets and visualizations
- `/upload` — Upload dataset (POST)
- `/preprocess/<int:dataset_id>` — Clean dataset
- `/visualize/<int:dataset_id>` — Create visualization
- `/view/<int:viz_id>` — View visualization
- `/edit/<int:viz_id>` — Edit visualization
- `/export-viz/<int:viz_id>` — Export PNG
- `/download/<int:dataset_id>` — Download dataset
- `/delete/<int:dataset_id>`, `/delete-viz/<int:viz_id>` — Delete

### Notes
- The `sales_forecasting.pbix` file is provided as a standalone Power BI artifact and is not required to run the Flask app.
- The `src/` directory contains optional data preparation and modeling scripts used for experimentation; the web app does not depend on them.

### License
This project is licensed under the terms specified in `LICENSE`.
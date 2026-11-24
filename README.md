# Data Visualization App (Flask)

A Flask web app to upload tabular datasets (CSV, XLSX, tab-separated TXT), do quick preprocessing, get chart recommendations, and create, edit, view and export visualizations. Includes user accounts (Flask-Login) with SQLite storage.

## Features
- Register / login (password rules enforced, hashed passwords)
- Upload CSV / XLSX / TXT (default limit 64 MB, set with `MAX_UPLOAD_MB`)
- Preprocessing: drop duplicate rows, drop rows with missing values, keep selected columns
- Chart recommendations (correlations, distributions, category comparisons, time series for datetime columns)
- Chart types: line, bar (mean of Y per category), scatter, pie, histogram, with optional color grouping. Large datasets are aggregated or sampled (20k points) for the chart.
- Interactive view (Plotly), edit, delete, and PNG export (matplotlib) of saved visualizations
- Download or delete datasets; every dataset/visualization is private to its owner

Not included: forecasting in the web app (see "Experiments" below), email verification.

## Quickstart
```bash
git clone https://github.com/parvashah29/Data-Visualization-App.git
cd Data-Visualization-App
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then set SECRET_KEY to a long random string
python app.py               # http://127.0.0.1:5000
```
The SQLite database (`instance/app.db`), `uploads/` and `flask_session/` are created automatically and are git-ignored. If `SECRET_KEY` is unset, a random key is generated on each start (sessions will not survive restarts).

Run the tests: `python -m pytest tests`

Production: `gunicorn app:app`.

## Configuration (environment variables / `.env`)
| Variable | Default |
|---|---|
| `SECRET_KEY` | random per start |
| `DATABASE_URL` | `sqlite:///instance/app.db` |
| `UPLOAD_FOLDER` | `./uploads` |
| `MAX_UPLOAD_MB` | `64` |
| `HOST`, `PORT`, `FLASK_DEBUG` | `127.0.0.1`, `5000`, off |

## Sample dataset
`data/raw/walmart.csv` (about 22 MB, Walmart Black Friday purchases: User_ID, Product_ID, Gender, Age, Occupation, City_Category, Purchase, ...). Upload it from the dashboard to try the full flow. The tests exercise it end to end. `data/processed/` holds example outputs from the experiment scripts.

## Project layout
```
app.py              Flask app (models, routes, chart logic)
templates/          Jinja2 templates
tests/              pytest suite (register, upload, preprocess, all chart types, export, access control)
data/raw, data/processed   sample data
src/                offline sales-forecasting experiments (not used by the app)
sales_forecasting.pbix     standalone Power BI file
```

## Experiments (`src/`)
Standalone scripts for data prep, feature engineering and forecasting (XGBoost / Holt-Winters). Only `src/data_prep` was verified to run (needs just pandas). The feature-engineering and modeling scripts additionally need `scikit-learn`, `xgboost`, `statsmodels` and `joblib`, which are not in `requirements.txt`, and were not re-verified.

## License
See `LICENSE`.

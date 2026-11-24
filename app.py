import io
import json
import os
from datetime import datetime, timedelta
from urllib.parse import urlparse

import matplotlib
matplotlib.use('Agg')  # non-GUI backend
import matplotlib.pyplot as plt
import pandas as pd
import pytz
import string
from dotenv import load_dotenv
from flask import (Flask, render_template, request, redirect, url_for, flash,
                   send_file)
from flask_login import (LoginManager, UserMixin, login_user, login_required,
                         logout_user, current_user)
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))

IST = pytz.timezone('Asia/Kolkata')
ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'txt'}
CHART_TYPES = {'line', 'bar', 'scatter', 'pie', 'histogram'}
MAX_PLOT_POINTS = 20000  # cap rows sent to the chart so big files stay fast


def create_app(test_config=None):
    app = Flask(__name__)
    instance_dir = os.path.join(BASE_DIR, 'instance')
    os.makedirs(instance_dir, exist_ok=True)

    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY') or os.urandom(32).hex(),
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            'DATABASE_URL', 'sqlite:///' + os.path.join(instance_dir, 'app.db')),
        UPLOAD_FOLDER=os.environ.get('UPLOAD_FOLDER', os.path.join(BASE_DIR, 'uploads')),
        MAX_CONTENT_LENGTH=int(os.environ.get('MAX_UPLOAD_MB', '64')) * 1024 * 1024,
        SESSION_TYPE='filesystem',
        SESSION_FILE_DIR=os.environ.get('SESSION_FILE_DIR', os.path.join(BASE_DIR, 'flask_session')),
        SESSION_PERMANENT=True,
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    )
    if test_config:
        app.config.update(test_config)

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
    Session(app)
    db.init_app(app)
    login_manager.init_app(app)

    register_routes(app)
    with app.app_context():
        db.create_all()
    return app


db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.session_protection = 'strong'


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    datasets = db.relationship('Dataset', backref='user', lazy=True)
    visualizations = db.relationship('Visualization', backref='user', lazy=True)
    last_login = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(IST))


class Dataset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    upload_date = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(IST))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    file_type = db.Column(db.String(10), nullable=False)
    columns = db.Column(db.Text)  # JSON list of column names


class Visualization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    dataset_id = db.Column(db.Integer, db.ForeignKey('dataset.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    chart_type = db.Column(db.String(50), nullable=False)
    x_axis = db.Column(db.String(100))
    y_axis = db.Column(db.String(100))
    color_by = db.Column(db.String(100))
    created_date = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(IST))
    config = db.Column(db.Text)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ---------------------------------------------------------------- helpers

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def read_table(path, file_type):
    if file_type == 'csv':
        return pd.read_csv(path)
    if file_type == 'xlsx':
        return pd.read_excel(path)
    if file_type == 'txt':
        return pd.read_csv(path, sep='\t')
    raise ValueError(f'Unsupported file type: {file_type}')


def dataset_path(app, dataset):
    return os.path.join(app.config['UPLOAD_FOLDER'], dataset.filename)


def load_dataset_df(app, dataset):
    path = dataset_path(app, dataset)
    if not os.path.exists(path):
        raise FileNotFoundError('The dataset file is missing on the server.')
    return read_table(path, dataset.file_type)


def column_groups(df):
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])
               and not pd.api.types.is_bool_dtype(df[c])]
    datetime_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    categorical = [c for c in df.columns if c not in numeric and c not in datetime_cols]
    return numeric, categorical, datetime_cols


def clean_axis(value, df):
    """Form values may be '', 'None' or a column that no longer exists."""
    if value in (None, '', 'None'):
        return None
    return value if value in df.columns else None


def safe_next(target):
    """Only allow same-site relative redirects after login."""
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith('/') or target.startswith('//'):
        return None
    return target


def get_visualization_recommendations(df):
    """Analyze dataset and recommend appropriate visualizations."""
    recommendations = []
    if len(df) == 0:
        return recommendations
    numeric_cols, categorical_cols, datetime_cols = column_groups(df)

    for date_col in datetime_cols:
        for num_col in numeric_cols:
            df_sorted = df.sort_values(date_col)
            corr = df_sorted[num_col].corr(pd.Series(range(len(df_sorted)), index=df_sorted.index))
            if pd.isna(corr):
                corr = 0.0
            trend = "increasing" if corr > 0.5 else "decreasing" if corr < -0.5 else "varying"
            recommendations.append({
                'category': 'Trends & Patterns', 'type': 'line',
                'title': f'Time Series Analysis: {num_col} Over Time',
                'x_axis': date_col, 'y_axis': num_col,
                'description': f'Track {trend} trend of {num_col} over time.',
                'confidence': min(abs(corr) * 100, 100)})

    if len(numeric_cols) >= 2:
        corr_matrix = df[numeric_cols].corr()
        for i in range(len(numeric_cols)):
            for j in range(i + 1, len(numeric_cols)):
                c = corr_matrix.iloc[i, j]
                if pd.notna(c) and abs(c) > 0.3:
                    c = abs(c)
                    rel = "strong" if c > 0.7 else "moderate"
                    recommendations.append({
                        'category': 'Correlations', 'type': 'scatter',
                        'title': f'Correlation: {numeric_cols[i]} vs {numeric_cols[j]}',
                        'x_axis': numeric_cols[i], 'y_axis': numeric_cols[j],
                        'description': f'A {rel} correlation ({c:.2f}) was detected between these variables.',
                        'confidence': c * 100})

    for num_col in numeric_cols:
        skew = df[num_col].skew()
        if pd.isna(skew):
            continue
        dist = "normal" if abs(skew) < 0.5 else "right-skewed" if skew > 0 else "left-skewed"
        recommendations.append({
            'category': 'Distributions', 'type': 'histogram',
            'title': f'Distribution of {num_col}',
            'x_axis': num_col, 'y_axis': None,
            'description': f'The data shows a {dist} distribution (skewness {skew:.2f}).',
            'confidence': max(min((1 - abs(skew) / 3) * 100, 100), 0)})

    for cat_col in categorical_cols:
        counts = df[cat_col].value_counts()
        n = len(counts)
        if n < 2 or n > 30:
            continue
        if n <= 12:
            recommendations.append({
                'category': 'Comparisons', 'type': 'pie',
                'title': f'Distribution of {cat_col}',
                'x_axis': cat_col, 'y_axis': None,
                'description': f'Shows the proportion of {n} categories in {cat_col}. The most common represents {counts.iloc[0] / len(df) * 100:.1f}% of the data.',
                'confidence': (1 - n / len(df)) * 100})
        for num_col in numeric_cols:
            agg = df.groupby(cat_col)[num_col].agg(['mean', 'std']).round(2)
            if agg['mean'].isna().all():
                continue
            hi, lo = agg['mean'].idxmax(), agg['mean'].idxmin()
            recommendations.append({
                'category': 'Comparisons', 'type': 'bar',
                'title': f'Average {num_col} by {cat_col}',
                'x_axis': cat_col, 'y_axis': num_col,
                'description': f'Compare {num_col} across categories. {hi} has the highest average ({agg.loc[hi, "mean"]:.2f}), {lo} the lowest ({agg.loc[lo, "mean"]:.2f}).',
                'confidence': 90 if agg['std'].mean() < agg['mean'].std() else 70})

    recommendations.sort(key=lambda r: r['confidence'], reverse=True)
    return recommendations[:30]


def prepare_plot_data(viz, df):
    """Validate columns and reduce the frame to what the chart needs.

    Returns (plot_df, y_label). Bar and pie charts are aggregated (mean for
    bar, sum for pie with a Y column); other charts are sampled to
    MAX_PLOT_POINTS rows.
    """
    needed = [c for c in (viz.x_axis, viz.y_axis, viz.color_by) if c]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")
    if viz.chart_type not in CHART_TYPES:
        raise ValueError(f"Unknown chart type: {viz.chart_type}")
    if viz.chart_type in ('line', 'bar', 'scatter') and not viz.y_axis:
        raise ValueError('This chart type needs a Y axis column.')

    plot_df = df[list(dict.fromkeys(needed))].copy()
    if viz.y_axis:
        plot_df[viz.y_axis] = pd.to_numeric(plot_df[viz.y_axis], errors='coerce')
    plot_df = plot_df.dropna()
    if len(plot_df) == 0:
        raise ValueError("No valid data points after cleaning. Check for missing or invalid values.")

    ct = viz.chart_type
    if ct == 'bar':
        keys = [c for c in (viz.x_axis, viz.color_by) if c]
        plot_df = plot_df.groupby(keys, as_index=False)[viz.y_axis].mean()
    elif ct == 'pie':
        names = viz.color_by or viz.x_axis
        if viz.y_axis:
            plot_df = plot_df.groupby(names, as_index=False)[viz.y_axis].sum()
        else:
            plot_df = plot_df[[names]].value_counts().reset_index(name='count')
    else:
        if len(plot_df) > MAX_PLOT_POINTS:
            plot_df = plot_df.sample(MAX_PLOT_POINTS, random_state=0)
        if ct == 'line':
            plot_df = plot_df.sort_values(by=viz.x_axis)
    return plot_df


def build_plotly_html(viz, plot_df):
    import plotly.express as px
    import plotly.io as pio
    kw = dict(title=viz.name, template='plotly_white')
    ct = viz.chart_type
    if ct == 'line':
        fig = px.line(plot_df, x=viz.x_axis, y=viz.y_axis, color=viz.color_by, markers=len(plot_df) < 200, **kw)
    elif ct == 'bar':
        fig = px.bar(plot_df, x=viz.x_axis, y=viz.y_axis, color=viz.color_by, barmode='group', **kw)
    elif ct == 'scatter':
        fig = px.scatter(plot_df, x=viz.x_axis, y=viz.y_axis, color=viz.color_by, **kw)
    elif ct == 'pie':
        names = viz.color_by or viz.x_axis
        values = viz.y_axis if viz.y_axis else 'count'
        fig = px.pie(plot_df, names=names, values=values, **kw)
    else:
        fig = px.histogram(plot_df, x=viz.x_axis, color=viz.color_by, **kw)
    fig.update_layout(margin=dict(l=40, r=40, t=60, b=40))
    return pio.to_html(fig, full_html=False, include_plotlyjs='cdn', config={
        'displayModeBar': True, 'displaylogo': False,
        'modeBarButtonsToRemove': ['lasso2d', 'select2d'],
        'toImageButtonOptions': {'format': 'png', 'filename': viz.name, 'scale': 2}})


def render_png(viz, plot_df):
    fig, ax = plt.subplots(figsize=(10, 6))
    try:
        ct = viz.chart_type
        if ct == 'pie':
            names = viz.color_by or viz.x_axis
            values = viz.y_axis if viz.y_axis else 'count'
            ax.pie(plot_df[values], labels=plot_df[names].astype(str), autopct='%1.1f%%')
            ax.set_ylabel('')
        else:
            if ct == 'histogram':
                if viz.color_by:
                    for g, sub in plot_df.groupby(viz.color_by):
                        ax.hist(pd.to_numeric(sub[viz.x_axis], errors='coerce').dropna(), bins=30, alpha=0.6, label=str(g))
                    ax.legend()
                else:
                    ax.hist(pd.to_numeric(plot_df[viz.x_axis], errors='coerce').dropna(), bins=30)
            elif ct == 'bar':
                if viz.color_by:
                    piv = plot_df.pivot(index=viz.x_axis, columns=viz.color_by, values=viz.y_axis)
                    piv.plot(kind='bar', ax=ax)
                else:
                    ax.bar(plot_df[viz.x_axis].astype(str), plot_df[viz.y_axis])
                plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
            else:
                groups = plot_df.groupby(viz.color_by) if viz.color_by else [(None, plot_df)]
                for g, sub in groups:
                    if ct == 'line':
                        ax.plot(sub[viz.x_axis], sub[viz.y_axis], label=None if g is None else str(g))
                    else:
                        ax.scatter(sub[viz.x_axis], sub[viz.y_axis], s=8, label=None if g is None else str(g))
                if viz.color_by:
                    ax.legend()
            ax.set_xlabel(viz.x_axis)
            ax.set_ylabel(viz.y_axis if viz.y_axis else 'Count')
        ax.set_title(viz.name)
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        return buf
    finally:
        plt.close(fig)


# ---------------------------------------------------------------- routes

def register_routes(app):
    def owned_or_redirect(model, obj_id, what):
        obj = db.get_or_404(model, obj_id)
        if obj.user_id != current_user.id:
            flash(f'You do not have permission to access this {what}', 'error')
            return None
        return obj

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = request.form.get('username', '')
            password = request.form.get('password', '')
            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password_hash, password):
                login_user(user, remember=True)
                user.last_login = datetime.now(IST)
                db.session.commit()
                return redirect(safe_next(request.args.get('next')) or url_for('dashboard'))
            flash('Invalid username or password', 'error')
        return render_template('login.html')

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'POST':
            username = (request.form.get('username') or '').strip()
            email = (request.form.get('email') or '').strip()
            password = request.form.get('password') or ''
            confirm = request.form.get('confirm_password') or ''

            error = None
            if not username or not email or not password:
                error = 'Username, email and password are required.'
            elif User.query.filter_by(username=username).first():
                error = 'Username already exists. Please choose another one.'
            elif User.query.filter_by(email=email).first():
                error = 'Email already registered. Please use another email or login.'
            elif len(password) < 8:
                error = 'Password must be at least 8 characters long.'
            elif not any(c.isupper() for c in password):
                error = 'Password must contain at least one uppercase letter.'
            elif not any(c.islower() for c in password):
                error = 'Password must contain at least one lowercase letter.'
            elif not any(c.isdigit() for c in password):
                error = 'Password must contain at least one number.'
            elif not any(c in string.punctuation for c in password):
                error = 'Password must contain at least one special character.'
            elif password != confirm:
                error = 'Passwords do not match.'
            if error:
                flash(error, 'danger')
                return redirect(url_for('register'))

            db.session.add(User(username=username, email=email,
                                password_hash=generate_password_hash(password)))
            db.session.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        return render_template('register.html')

    @app.route('/dashboard')
    @login_required
    def dashboard():
        datasets = Dataset.query.filter_by(user_id=current_user.id).all()
        visualizations = Visualization.query.filter_by(user_id=current_user.id).all()
        last_login = 'Never'
        ll = current_user.last_login
        if ll:
            ll = IST.localize(ll) if ll.tzinfo is None else ll.astimezone(IST)
            last_login = ll.strftime('%d/%m/%Y %I:%M %p')
        return render_template('dashboard.html', username=current_user.username,
                               datasets=datasets, visualizations=visualizations,
                               last_login=last_login)

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('index'))

    @app.route('/upload', methods=['GET', 'POST'])
    @login_required
    def upload_file():
        if request.method != 'POST':
            return redirect(url_for('dashboard'))
        file = request.files.get('file')
        dataset_name = request.form.get('dataset_name', '').strip()
        if not dataset_name:
            flash('Please provide a name for your dataset.', 'error')
            return redirect(url_for('dashboard'))
        if file is None or file.filename == '':
            flash('No file selected. Please choose a file to upload.', 'error')
            return redirect(url_for('dashboard'))
        if not allowed_file(file.filename):
            flash('File type not allowed. Please upload a CSV, Excel, or TXT file.', 'error')
            return redirect(url_for('dashboard'))

        filename = secure_filename(file.filename)
        if not filename or '.' not in filename:
            flash('Invalid file name.', 'error')
            return redirect(url_for('dashboard'))
        ext = filename.rsplit('.', 1)[1].lower()
        unique = f"{current_user.id}_{int(datetime.now().timestamp())}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique)
        try:
            file.save(file_path)
            df = read_table(file_path, ext)
            if df.shape[1] == 0:
                raise ValueError('The file has no columns.')
            ds = Dataset(name=dataset_name[:100], filename=unique, user_id=current_user.id,
                         file_type=ext, columns=json.dumps([str(c) for c in df.columns]))
            db.session.add(ds)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            if os.path.exists(file_path):
                os.remove(file_path)
            flash(f'Error processing file: {e}', 'error')
            return redirect(url_for('dashboard'))
        flash(f'Dataset "{dataset_name}" uploaded successfully!', 'success')
        return redirect(url_for('preprocess', dataset_id=ds.id))

    @app.route('/preprocess/<int:dataset_id>', methods=['GET', 'POST'])
    @login_required
    def preprocess(dataset_id):
        dataset = owned_or_redirect(Dataset, dataset_id, 'dataset')
        if dataset is None:
            return redirect(url_for('dashboard'))
        try:
            df = load_dataset_df(app, dataset)

            if request.method == 'POST':
                cleaned = df.copy()
                if request.form.get('drop_duplicates') == 'on':
                    cleaned = cleaned.drop_duplicates()
                if request.form.get('drop_na_rows') == 'on':
                    cleaned = cleaned.dropna()
                selected = [c for c in request.form.getlist('selected_columns') if c in cleaned.columns]
                if selected:
                    cleaned = cleaned[selected]
                if len(cleaned) == 0:
                    flash('Cleaning would remove every row; nothing was changed.', 'error')
                    return redirect(url_for('preprocess', dataset_id=dataset.id))

                base = dataset.filename[len('cleaned_'):] if dataset.filename.startswith('cleaned_') else dataset.filename
                cleaned_filename = f"cleaned_{base}"
                cleaned_path = os.path.join(app.config['UPLOAD_FOLDER'], cleaned_filename)
                if dataset.file_type == 'csv':
                    cleaned.to_csv(cleaned_path, index=False)
                elif dataset.file_type == 'xlsx':
                    cleaned.to_excel(cleaned_path, index=False)
                else:
                    cleaned.to_csv(cleaned_path, sep='\t', index=False)
                dataset.filename = cleaned_filename
                dataset.columns = json.dumps([str(c) for c in cleaned.columns])
                db.session.commit()
                flash('Data cleaning completed successfully!', 'success')
                return redirect(url_for('visualize', dataset_id=dataset.id))

            info = {
                'total_rows': len(df),
                'total_columns': len(df.columns),
                'missing_cells': int(df.isnull().sum().sum()),
                'duplicate_rows': int(df.duplicated().sum()),
            }
            columns_info = [{
                'name': c, 'dtype': str(df[c].dtype),
                'missing_values': int(df[c].isnull().sum()),
                'unique_values': int(df[c].nunique()),
                'sample_values': df[c].dropna().head(3).tolist(),
            } for c in df.columns]
            return render_template('preprocess.html', dataset=dataset, info=info,
                                   columns_info=columns_info,
                                   preview_data=df.head(5).to_dict('records'),
                                   columns=df.columns.tolist())
        except Exception as e:
            flash(f'Error processing dataset: {e}', 'error')
            return redirect(url_for('dashboard'))

    @app.route('/visualize/<int:dataset_id>', methods=['GET', 'POST'])
    @login_required
    def visualize(dataset_id):
        dataset = owned_or_redirect(Dataset, dataset_id, 'dataset')
        if dataset is None:
            return redirect(url_for('dashboard'))
        try:
            df = load_dataset_df(app, dataset)
            numeric, categorical, datetimes = column_groups(df)
            columns = {'numeric': numeric, 'categorical': categorical,
                       'datetime': datetimes, 'all': df.columns.tolist()}
            recommendations = get_visualization_recommendations(df)

            def page():
                return render_template('visualize.html', dataset=dataset, columns=columns,
                                       recommendations=recommendations,
                                       sample_data=df.head(5).to_dict('records'))

            if request.method == 'POST':
                viz_name = request.form.get('viz_name', '').strip()
                chart_type = request.form.get('chart_type')
                x_axis = clean_axis(request.form.get('x_axis'), df)
                y_axis = clean_axis(request.form.get('y_axis'), df)
                color_by = clean_axis(request.form.get('color_by'), df)

                if not viz_name:
                    flash('Please provide a name for your visualization', 'error')
                    return page()
                if chart_type not in CHART_TYPES:
                    flash('Please choose a valid chart type', 'error')
                    return page()
                if not x_axis or (chart_type in ('line', 'bar', 'scatter') and not y_axis):
                    flash('Please select the required X and Y axis columns', 'error')
                    return page()
                if chart_type in ('histogram',):
                    y_axis = None

                viz = Visualization(name=viz_name[:100], dataset_id=dataset.id,
                                    user_id=current_user.id, chart_type=chart_type,
                                    x_axis=x_axis, y_axis=y_axis, color_by=color_by,
                                    created_date=datetime.now(IST))
                db.session.add(viz)
                db.session.commit()
                flash(f'Visualization "{viz_name}" created successfully!', 'success')
                return redirect(url_for('view_visualization', viz_id=viz.id))
            return page()
        except Exception as e:
            flash(f'Error processing dataset: {e}', 'error')
            return redirect(url_for('dashboard'))

    @app.route('/view/<int:viz_id>')
    @login_required
    def view_visualization(viz_id):
        viz = owned_or_redirect(Visualization, viz_id, 'visualization')
        if viz is None:
            return redirect(url_for('dashboard'))
        dataset = db.session.get(Dataset, viz.dataset_id)
        if not dataset:
            flash('Dataset not found', 'error')
            return redirect(url_for('dashboard'))
        try:
            df = load_dataset_df(app, dataset)
            plot_df = prepare_plot_data(viz, df)
            plot_html = build_plotly_html(viz, plot_df)
            return render_template('view_visualization.html', viz=viz, dataset=dataset,
                                   plot_html=plot_html)
        except Exception as e:
            flash(f'Error creating visualization: {e}', 'error')
            return redirect(url_for('dashboard'))

    @app.route('/edit/<int:viz_id>', methods=['GET', 'POST'])
    @login_required
    def edit_visualization(viz_id):
        viz = owned_or_redirect(Visualization, viz_id, 'visualization')
        if viz is None:
            return redirect(url_for('dashboard'))
        dataset = db.session.get(Dataset, viz.dataset_id)
        if not dataset:
            flash('Dataset not found', 'error')
            return redirect(url_for('dashboard'))
        try:
            df = load_dataset_df(app, dataset)
            if request.method == 'POST':
                chart_type = request.form.get('chart_type', viz.chart_type)
                x_axis = clean_axis(request.form.get('x_axis'), df)
                y_axis = clean_axis(request.form.get('y_axis'), df)
                if chart_type not in CHART_TYPES or not x_axis or (
                        chart_type in ('line', 'bar', 'scatter') and not y_axis):
                    flash('Please choose a valid chart type and the required X/Y columns.', 'error')
                    return redirect(url_for('edit_visualization', viz_id=viz.id))
                viz.name = (request.form.get('viz_name') or viz.name).strip()[:100]
                viz.chart_type = chart_type
                viz.x_axis = x_axis
                viz.y_axis = None if chart_type == 'histogram' else y_axis
                viz.color_by = clean_axis(request.form.get('color_by'), df)
                db.session.commit()
                flash(f'Visualization "{viz.name}" updated successfully!', 'success')
                return redirect(url_for('view_visualization', viz_id=viz.id))
            return render_template('edit_visualization.html', viz=viz, dataset=dataset,
                                   columns=df.columns.tolist())
        except Exception as e:
            flash(f'Error editing visualization: {e}', 'error')
            return redirect(url_for('dashboard'))

    @app.route('/delete/<int:dataset_id>')
    @login_required
    def delete_dataset(dataset_id):
        dataset = owned_or_redirect(Dataset, dataset_id, 'dataset')
        if dataset is None:
            return redirect(url_for('dashboard'))
        path = dataset_path(app, dataset)
        if os.path.exists(path):
            os.remove(path)
        Visualization.query.filter_by(dataset_id=dataset_id).delete()
        name = dataset.name
        db.session.delete(dataset)
        db.session.commit()
        flash(f'Dataset "{name}" deleted successfully!', 'success')
        return redirect(url_for('dashboard'))

    @app.route('/delete-viz/<int:viz_id>')
    @login_required
    def delete_visualization(viz_id):
        viz = owned_or_redirect(Visualization, viz_id, 'visualization')
        if viz is None:
            return redirect(url_for('dashboard'))
        name = viz.name
        db.session.delete(viz)
        db.session.commit()
        flash(f'Visualization "{name}" deleted successfully!', 'success')
        return redirect(url_for('dashboard'))

    @app.route('/download/<int:dataset_id>')
    @login_required
    def download_dataset(dataset_id):
        dataset = owned_or_redirect(Dataset, dataset_id, 'dataset')
        if dataset is None:
            return redirect(url_for('dashboard'))
        path = dataset_path(app, dataset)
        if not os.path.exists(path):
            flash('File not found', 'error')
            return redirect(url_for('dashboard'))
        return send_file(path, as_attachment=True)

    @app.route('/export-viz/<int:viz_id>')
    @login_required
    def export_visualization(viz_id):
        viz = owned_or_redirect(Visualization, viz_id, 'visualization')
        if viz is None:
            return redirect(url_for('dashboard'))
        dataset = db.session.get(Dataset, viz.dataset_id)
        if not dataset:
            flash('Dataset not found', 'error')
            return redirect(url_for('dashboard'))
        try:
            df = load_dataset_df(app, dataset)
            img = render_png(viz, prepare_plot_data(viz, df))
            return send_file(img, mimetype='image/png', as_attachment=True,
                             download_name=f"{secure_filename(viz.name) or 'chart'}.png")
        except Exception as e:
            flash(f'Error exporting visualization: {e}', 'error')
            return redirect(url_for('dashboard'))


app = create_app()

if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1',
            host=os.environ.get('HOST', '127.0.0.1'),
            port=int(os.environ.get('PORT', '5000')))

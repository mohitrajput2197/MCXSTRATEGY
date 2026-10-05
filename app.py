import os
import io
import json
import re
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, request, send_file, session, redirect, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_admin import Admin, AdminIndexView
from flask_admin.contrib.sqla import ModelView
from wtforms.fields import PasswordField
from flask_babel import Babel
from dotenv import load_dotenv

# --- Configuration ---
load_dotenv()
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "mcx-secret-key-for-development")
INVITATION_CODE = os.environ.get("INVITATION_CODE", "MCX2026")

# --- Database Configuration ---
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///' + os.path.join(basedir, 'mcx_users.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['BABEL_DEFAULT_LOCALE'] = 'en'
babel = Babel(app)
db = SQLAlchemy(app)

# --- Database Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    last_analysis_result = db.Column(db.Text)

class SavedMCXStrategy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    strategy_name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref=db.backref('mcx_strategies', lazy=True, cascade="all, delete-orphan"))
    commodity = db.Column(db.String(50), nullable=False)
    option_expiry = db.Column(db.String(50))
    futures_expiry = db.Column(db.String(50))
    firstStrikeCE = db.Column(db.Integer)
    firstStrikePE = db.Column(db.Integer)
    strikeStep = db.Column(db.Integer)
    totStrikes = db.Column(db.Integer)
    buySellPattern = db.Column(db.String(50))
    mode = db.Column(db.String(10))
    ratios_gaps_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class MCXTradeJournal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref=db.backref('mcx_journal_entries', lazy=True, cascade="all, delete-orphan"))
    strategy_details_json = db.Column(db.Text, nullable=False)
    entry_date = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)
    final_pnl = db.Column(db.Float)

# --- Admin Panel Panel ---
class MyAdminIndexView(AdminIndexView):
    def is_accessible(self):
        return session.get('logged_in') and session.get('is_admin')
    def inaccessible_callback(self, name, **kwargs):
        flash('You do not have permission to access the Admin Panel.', 'error')
        return redirect('/login')

class SecureModelView(ModelView):
    column_list = ['username', 'is_admin']
    form_columns = ['username', 'password', 'is_admin']
    form_overrides = {'password': PasswordField}
    def on_model_change(self, form, model, is_created):
        if form.password.data:
            model.password = generate_password_hash(form.password.data)
    def is_accessible(self):
        return session.get('logged_in') and session.get('is_admin')
    def inaccessible_callback(self, name, **kwargs):
        return redirect('/login')

admin = Admin(app, name='MCX Control Panel', template_mode='bootstrap3', index_view=MyAdminIndexView())
admin.add_view(SecureModelView(User, db.session))
admin.add_view(ModelView(SavedMCXStrategy, db.session))
admin.add_view(ModelView(MCXTradeJournal, db.session))

with app.app_context():
    db.create_all()

@app.template_filter('fromjson')
def fromjson_filter(value):
    return json.loads(value)

# --- Dynamic MCX Expiry Calculation Engine ---
def get_dynamic_mcx_commodities():
    now = datetime.now()
    current_year = now.year
    current_month = now.month
    current_day = now.day

    months_map = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']

    def calculate_expiry(target_day, month_offset=0):
        y = current_year
        m = current_month + month_offset
        while m > 12:
            m -= 12
            y += 1
        return f"{target_day:02d}-{months_map[m-1]}-{y}"

    co_offset = 1 if current_day > 17 else 0
    co_fut_offset = 1 if current_day > 19 else 0

    comini_opt_offset = 1 if current_day > 17 else 0
    comini_fut_offset = 1 if current_day > 19 else 0

    ng_offset = 1 if current_day > 24 else 0
    ng_fut_offset = 1 if current_day > 26 else 0

    ngmini_opt_offset = 1 if current_day > 24 else 0
    ngmini_fut_offset = 1 if current_day > 26 else 0

    gold_opt_offset = 1 if current_day > 24 else 0
    gold_fut_offset = gold_opt_offset + 1

    goldmini_opt_offset = 1 if current_day > 24 else 0
    goldmini_fut_offset = goldmini_opt_offset + 1

    silver_opt_offset = 1 if current_day > 26 else 0
    silver_fut_offset = silver_opt_offset + 1

    silvermini_opt_offset = 1 if current_day > 26 else 0
    silvermini_fut_offset = silvermini_opt_offset + 1

    copper_offset = 1 if current_day > 23 else 0
    copper_fut_offset = 1 if current_day > 30 else 0

    return {
        'CRUDEOIL': {
            'name': 'Crude Oil', 'lot_size': 100, 'tick_size': 10,
            'option_expiry': calculate_expiry(17, co_offset),
            'futures_expiry': calculate_expiry(19, co_fut_offset),
            'default_first_ce': 9500, 'default_first_pe': 8000, 'strike_step': 500
        },
        'CRUDEOILM': {
            'name': 'Crude Oil Mini', 'lot_size': 10, 'tick_size': 1,
            'option_expiry': calculate_expiry(17, comini_opt_offset),
            'futures_expiry': calculate_expiry(19, comini_fut_offset),
            'default_first_ce': 9500, 'default_first_pe': 8000, 'strike_step': 100
        },
        'NATURALGAS': {
            'name': 'Natural Gas', 'lot_size': 1250, 'tick_size': 10,
            'option_expiry': calculate_expiry(24, ng_offset),
            'futures_expiry': calculate_expiry(26, ng_fut_offset),
            'default_first_ce': 290, 'default_first_pe': 290, 'strike_step': 20
        },
        'NATGASMINI': {
            'name': 'Natural Gas Mini', 'lot_size': 250, 'tick_size': 1,
            'option_expiry': calculate_expiry(24, ngmini_opt_offset),
            'futures_expiry': calculate_expiry(26, ngmini_fut_offset),
            'default_first_ce': 290, 'default_first_pe': 290, 'strike_step': 10
        },
        'GOLD': {
            'name': 'Gold', 'lot_size': 1, 'tick_size': 100,
            'option_expiry': calculate_expiry(24, gold_opt_offset),
            'futures_expiry': calculate_expiry(2, gold_fut_offset),
            'default_first_ce': 158000, 'default_first_pe': 158000, 'strike_step': 1000
        },
        'GOLDMINI': {
            'name': 'Gold Mini', 'lot_size': 100, 'tick_size': 10,
            'option_expiry': calculate_expiry(24, goldmini_opt_offset),
            'futures_expiry': calculate_expiry(5, goldmini_fut_offset),
            'default_first_ce': 70000, 'default_first_pe': 70000, 'strike_step': 100
        },
        'SILVER': {
            'name': 'Silver', 'lot_size': 30, 'tick_size': 100,
            'option_expiry': calculate_expiry(26, silver_opt_offset),
            'futures_expiry': calculate_expiry(5, silver_fut_offset),
            'default_first_ce': 270000, 'default_first_pe': 270000, 'strike_step': 1000
        },
        'SILVERMINI': {
            'name': 'Silver Mini', 'lot_size': 5, 'tick_size': 1,
            'option_expiry': calculate_expiry(26, silvermini_opt_offset),
            'futures_expiry': calculate_expiry(5, silvermini_fut_offset),
            'default_first_ce': 90000, 'default_first_pe': 90000, 'strike_step': 500
        },
        'COPPER': {
            'name': 'Copper', 'lot_size': 2500, 'tick_size': 10,
            'option_expiry': calculate_expiry(23, copper_offset),
            'futures_expiry': calculate_expiry(30, copper_fut_offset),
            'default_first_ce': 1200, 'default_first_pe': 1200, 'strike_step': 50
        }
    }

# --- Main Endpoints ---
@app.route('/')
def index():
    if not session.get("logged_in"):
        return redirect('/login')
    return render_template('dashboard.html', username=session.get("username"), is_admin=session.get('is_admin', False), page='mcx')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get("username")).first()
        if user and check_password_hash(user.password, request.form.get("password")):
            session["logged_in"] = True
            session["username"] = user.username
            session["is_admin"] = user.is_admin
            return redirect('/')
        else:
            flash('Invalid username or password.', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if request.form.get('invitation_code') != INVITATION_CODE:
            flash('Invalid Invitation Code.', 'error')
            return redirect('/register')
        if User.query.filter_by(username=request.form.get('username')).first():
            flash('That username is already taken.', 'error')
            return redirect('/register')
        new_user = User(username=request.form.get('username'),
                        password=generate_password_hash(request.form.get('password')),
                        is_admin=False)
        db.session.add(new_user)
        db.session.commit()
        flash('Registration successful! You can now log in.', 'success')
        return redirect('/login')
    return render_template('register.html')

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash('You have been successfully logged out.', 'success')
    return redirect("/login")

# --- Strategy Management Routes ---
@app.route('/mcx_history')
def mcx_history():
    if not session.get("logged_in"):
        return redirect('/login')
    user = User.query.filter_by(username=session['username']).first()
    user_strategies = SavedMCXStrategy.query.filter_by(user_id=user.id).order_by(SavedMCXStrategy.created_at.desc()).all()
    return render_template('mcx_history.html', strategies=user_strategies, username=session.get("username"))

@app.route('/save_mcx_strategy', methods=['POST'])
def save_mcx_strategy():
    if not session.get("logged_in"):
        return jsonify({"status": "error"}), 401
    data = request.json
    user = User.query.filter_by(username=session['username']).first()
    new_strategy = SavedMCXStrategy(
        strategy_name=data.get('strategy_name', 'Unnamed'),
        user_id=user.id,
        commodity=data.get('commodity'),
        option_expiry=data.get('option_expiry'),
        futures_expiry=data.get('futures_expiry'),
        firstStrikeCE=data.get('firstStrikeCE'),
        firstStrikePE=data.get('firstStrikePE'),
        strikeStep=data.get('strikeStep'),
        totStrikes=data.get('totStrikesMaster', 10),
        buySellPattern=data.get('buySellPattern'),
        mode=data.get('mode'),
        ratios_gaps_json=json.dumps(data.get('ratios_gaps'))
    )
    db.session.add(new_strategy)
    db.session.commit()
    return jsonify({"status": "success", "message": f"Strategy '{new_strategy.strategy_name}' saved!"})

@app.route('/load_mcx_strategy/<int:strategy_id>')
def load_mcx_strategy(strategy_id):
    if not session.get("logged_in"):
        return jsonify({}), 401
    strategy = SavedMCXStrategy.query.get_or_404(strategy_id)
    user = User.query.filter_by(username=session['username']).first()
    if strategy.user_id != user.id:
        return jsonify({"status": "error"}), 403
    return jsonify({
        'commodity': strategy.commodity,
        'option_expiry': strategy.option_expiry,
        'futures_expiry': strategy.futures_expiry,
        'firstStrikeCE': strategy.firstStrikeCE,
        'firstStrikePE': strategy.firstStrikePE,
        'strikeStep': strategy.strikeStep,
        'totStrikesMaster': strategy.totStrikes,
        'totStrikesCE': strategy.totStrikes,
        'totStrikesPE': strategy.totStrikes,
        'buySellPattern': strategy.buySellPattern,
        'mode': strategy.mode,
        'ratios_gaps': json.loads(strategy.ratios_gaps_json)
    })

# --- MCX CSV Generation Logic ---
@app.route('/mcx_generate', methods=['POST'])
def mcx_generate():
    if not session.get("logged_in"):
        return redirect("/login")

    def get_int_from_form(field_name, default_value):
        value = request.form.get(field_name, str(default_value))
        return int(value) if value and value.isdigit() else default_value

    def get_str_from_form(field_name, default_value):
        value = request.form.get(field_name)
        return value if value and value.strip() else str(default_value)

    strategy_type = request.form.get('strategy_type', 'options_only')
    strike_direction = request.form.get('strike_direction', 'normal')
    commodity = request.form.get('commodity', 'CRUDEOIL').upper()

    dynamic_commodities = get_dynamic_mcx_commodities()
    if commodity not in dynamic_commodities:
        flash('Invalid commodity selected.', 'error')
        return redirect('/')

    # --- SYMBOL MAPPING FOR MINI CONTRACTS ---
    if commodity == 'GOLDMINI':
        mcx_symbol = 'GOLDM'
    elif commodity == 'SILVERMINI':
        mcx_symbol = 'SILVERM'
    elif commodity == 'CRUDEOILM':
        mcx_symbol = 'CRUDEOILM'
    elif commodity == 'NATGASMINI':
        mcx_symbol = 'NATGASMINI'
    else:
        mcx_symbol = commodity

    commodity_info = dynamic_commodities[commodity]

    ratios_list = request.form.getlist('ratios')
    gaps_list_str = request.form.getlist('gaps')
    use_individual_gaps_list = request.form.getlist('use_individual_gaps')

    parsed_pairs = []
    for i, (ratio_str, gap_str) in enumerate(zip(ratios_list, gaps_list_str)):
        use_individual = True
        if i < len(use_individual_gaps_list):
            use_individual = (use_individual_gaps_list[i] == 'on')
        parsed_pairs.append({'ratio': ratio_str, 'gaps': gap_str, 'individual': use_individual})

    option_expiry = request.form.get('option_expiry').strip().upper() if request.form.get('option_expiry') else commodity_info['option_expiry']
    futures_expiry = request.form.get('futures_expiry').strip().upper() if request.form.get('futures_expiry') else commodity_info['futures_expiry']

    base_first_ce = get_int_from_form('firstStrikeCE', commodity_info['default_first_ce'])
    base_first_pe = get_int_from_form('firstStrikePE', commodity_info['default_first_pe'])
    strikeStep = get_int_from_form('strikeStep', commodity_info['strike_step'])

    # --- REVERSE ITM MODE: 1 STRIKE STEP UPAR SE SHURU KARNA ---
    if strike_direction == 'reverse':
        firstStrikeCE = base_first_ce + strikeStep
        firstStrikePE = base_first_pe + strikeStep
    else:
        firstStrikeCE = base_first_ce
        firstStrikePE = base_first_pe

    # NEW BI-DIRECTIONAL OPTIONAL SWITCH LAYER
    sync_strikes = request.form.get('sync_strikes') == 'on'
    if sync_strikes:
        master_count = get_int_from_form('totStrikesMaster', 10)
        totStrikesCE = master_count
        totStrikesPE = master_count
    else:
        totStrikesCE = get_int_from_form('totStrikesCE', 10)
        totStrikesPE = get_int_from_form('totStrikesPE', 10)

    raw_bsp = request.form.get('buySellPattern', 'S.B.S').upper()

    fileName = request.form.get('fileName') or f"{mcx_symbol}-strategy.csv"
    if not fileName.endswith('.csv'):
        fileName += '.csv'

    mode = request.form.get('mode', '8184')
    use_advanced_csv = request.form.get('use_advanced_csv') == 'on'
    adv_bsoq = get_str_from_form('bsoq', '0') if use_advanced_csv else '0'
    adv_bqty = get_str_from_form('bqty', '0') if use_advanced_csv else '0'
    adv_bprice = get_str_from_form('bprice', '0') if use_advanced_csv else '0'
    adv_sprice = get_str_from_form('sprice', '0') if use_advanced_csv else '0'
    adv_sqty = get_str_from_form('sqty', '0') if use_advanced_csv else '0'
    adv_ssoq = get_str_from_form('ssoq', '0') if use_advanced_csv else '0'

    lot_per_script = commodity_info['lot_size']
    tick_size = commodity_info['tick_size']

    def getStgCode(ratioStr, mode, commodity):
        count = len(ratioStr.split('.'))
        if mode == "IOC":
            if count == 2: return 210
            if count == 3: return 310
            if count == 4: return 410
            return 210
        if count == 2: return 10201
        if count == 3: return 10301
        if count == 4: return 10401
        return 10301

    headerLine = "#PID,cost,bcmp,scmp,flp,stgcode,script,lotsize,itype,expiry,otype,stkprice,ratio,buysell,pnAdd,pnMulti,bsoq,bqty,bprice,sprice,sqty,ssoq,btrQty,strQty,gap,ticksize,orderDepth,priceDepth,thshqty,allowedBiddepth,allowedSlippage,tradeGear,shortflag,isBidding,marketOrderRetries,marketOrLimitOrder,isBestbid,unhedgedActionType,TERActionType,BidWaitingType,param2,param3,param4,param5,param6,param7,param01,param02,param03,param04,param05,param06,param07,param08,param09,param10,param11,param12,param13,param14,param15,param16,param17,param18,param19,param20,param21,param22,param23,param24,param25,param26,param27,param28,param29,param30,param31,param32,param33,param34,param35,param36,param37,param38,param39,param40,param301,param302,param303,param304,param305,param306,param307,param308,param309,param310,param311,param312,param313,param314,param315,param316,param317,param318,param319,param320,param321,param322,param323,param324,param325,param326,param327,param328,param329,param330,param331,param332,param333,param334,param335,param336,param337,param338,param339,param340"
    headers = headerLine.split(",")

    baseParts = [char for char in raw_bsp if char.isalpha()]
    if not baseParts:
        baseParts = ['S', 'B']
    baseCount = len(baseParts)

    rows = [headerLine]
    pid = 1

    for pair in parsed_pairs:
        raw_ratio_str = pair['ratio']
        raw_gap_str = pair['gaps']
        use_individual = pair['individual']

        if not raw_ratio_str.strip() or not raw_gap_str.strip():
            continue

        ratio_digits = re.findall(r'\d+', raw_ratio_str)
        if not ratio_digits:
            continue

        legCount = len(ratio_digits)
        norm_ratio = ".".join(ratio_digits)
        formatted_ratio = "|".join(ratio_digits)

        all_gaps_to_iterate = [int(g) for g in re.findall(r'\d+', raw_gap_str)]
        if not all_gaps_to_iterate:
            continue

        stgCode = getStgCode(norm_ratio, mode, commodity)
        current_lotSize = "|".join([str(lot_per_script)] * legCount)
        buySellStr = '.'.join([baseParts[i % baseCount] for i in range(legCount)])

        for gap in all_gaps_to_iterate:
            # --- CE Row Generation ---
            for i in range(totStrikesCE):
                if strike_direction == 'reverse':
                    current_ce_strike = firstStrikeCE + (i * strikeStep)
                    if use_individual:
                        leg_gaps = all_gaps_to_iterate
                        ce_prices = [current_ce_strike]
                        for j in range(legCount - 1):
                            gap_to_subtract = leg_gaps[j] if j < len(leg_gaps) else leg_gaps[-1]
                            current_ce_strike -= gap_to_subtract
                            ce_prices.append(current_ce_strike)
                    else:
                        ce_prices = [firstStrikeCE + i * strikeStep - j * gap for j in range(legCount)]
                else:
                    current_ce_strike = firstStrikeCE + (i * strikeStep)
                    if use_individual:
                        leg_gaps = all_gaps_to_iterate
                        ce_prices = [current_ce_strike]
                        for j in range(legCount - 1):
                            gap_to_add = leg_gaps[j] if j < len(leg_gaps) else leg_gaps[-1]
                            current_ce_strike += gap_to_add
                            ce_prices.append(current_ce_strike)
                    else:
                        ce_prices = [firstStrikeCE + i * strikeStep + j * gap for j in range(legCount)]

                if strategy_type == 'mixed':
                    itype_list = ['FUTSTK'] + ['OPTSTK'] * (legCount - 1) if legCount > 1 else ['FUTSTK']
                    expiry_list = [futures_expiry] + [option_expiry] * (legCount - 1) if legCount > 1 else [futures_expiry]
                    ce_otype_list = ['-'] + ['CE'] * (legCount - 1) if legCount > 1 else ['-']
                    ce_strike_list = ['0'] + [str(x) for x in ce_prices[1:]] if legCount > 1 else ['0']

                    current_ticksize = str(tick_size * 2)
                    p01, p02, p05, p08, p09 = '200', '9', '20', '0', '5'
                    p10, p11, p12, p13, p14 = '5', '10', '50', '5', '5'
                    p16, p23, p24 = '1', '9', '300'
                else:
                    itype_list = ['OPTSTK'] * legCount
                    expiry_list = [option_expiry] * legCount
                    ce_otype_list = ['CE'] * legCount
                    ce_strike_list = [str(x) for x in ce_prices]

                    current_ticksize = str(tick_size)
                    p01, p02, p05, p08, p09 = '60', ('50' if mode == "IOC" else '800'), '100', '60', '100'
                    p10, p11, p12, p13, p14 = '200', '100', '100', '10', '0'
                    p16, p23, p24 = '0', '10', '0'

                row_ce = ['0'] * len(headers)
                row_ce[0] = str(pid)
                pid += 1
                row_ce[5] = str(stgCode)

                # Mapped symbol
                row_ce[6] = mcx_symbol

                row_ce[7] = current_lotSize
                row_ce[8] = '-'.join(itype_list)
                row_ce[9] = '|'.join(expiry_list)
                row_ce[10] = '|'.join(ce_otype_list)
                row_ce[11] = '|'.join(ce_strike_list)
                row_ce[12] = formatted_ratio
                row_ce[13] = buySellStr
                row_ce[24] = str(gap)
                row_ce[25] = current_ticksize
                row_ce[16] = adv_bsoq
                row_ce[17] = adv_bqty
                row_ce[18] = str(int(float(adv_bprice)) * 100) if adv_bprice != '0' else '0'
                row_ce[19] = str(int(float(adv_sprice)) * 100) if adv_sprice != '0' else '0'
                row_ce[20] = adv_sqty
                row_ce[21] = adv_ssoq
                row_ce[15] = '1'
                row_ce[26] = '2'
                row_ce[27] = '2'
                row_ce[29] = '5'
                row_ce[30] = '50' if mode == "IOC" else '200'
                row_ce[31] = '2'
                row_ce[32] = '1'
                row_ce[33] = 'FALSE' if mode == "IOC" else 'TRUE'
                row_ce[34] = '5'
                row_ce[37] = '2'
                row_ce[38] = '1'
                row_ce[39] = '500'

                row_ce[46] = p01
                row_ce[47] = p02
                row_ce[50] = p05
                row_ce[51] = '200'
                row_ce[52] = '2575'
                row_ce[53] = p08
                row_ce[54] = p09
                row_ce[55] = p10
                row_ce[56] = p11
                row_ce[57] = p12
                row_ce[58] = p13
                row_ce[59] = p14
                row_ce[60] = '1'
                row_ce[61] = p16
                row_ce[64] = '1999'
                row_ce[66] = '30'
                row_ce[68] = p23
                row_ce[69] = p24
                row_ce[86] = '101'
                row_ce[28] = '80' if mode == "IOC" else '0'

                rows.append(','.join(row_ce))

            # --- PE Row Generation ---
            for i in range(totStrikesPE):
                if strike_direction == 'reverse':
                    current_pe_strike = firstStrikePE - (i * strikeStep)
                    if use_individual:
                        leg_gaps = all_gaps_to_iterate
                        pe_prices = [current_pe_strike]
                        for j in range(legCount - 1):
                            gap_to_add = leg_gaps[j] if j < len(leg_gaps) else leg_gaps[-1]
                            current_pe_strike += gap_to_add
                            pe_prices.append(current_pe_strike)
                    else:
                        pe_prices = [firstStrikePE - i * strikeStep + j * gap for j in range(legCount)]
                else:
                    current_pe_strike = firstStrikePE - (i * strikeStep)
                    if use_individual:
                        leg_gaps = all_gaps_to_iterate
                        pe_prices = [current_pe_strike]
                        for j in range(legCount - 1):
                            gap_to_subtract = leg_gaps[j] if j < len(leg_gaps) else leg_gaps[-1]
                            current_pe_strike -= gap_to_subtract
                            pe_prices.append(current_pe_strike)
                    else:
                        pe_prices = [firstStrikePE - i * strikeStep - j * gap for j in range(legCount)]

                if strategy_type == 'mixed':
                    itype_list = ['FUTSTK'] + ['OPTSTK'] * (legCount - 1) if legCount > 1 else ['FUTSTK']
                    expiry_list = [futures_expiry] + [option_expiry] * (legCount - 1) if legCount > 1 else [futures_expiry]
                    pe_otype_list = ['-'] + ['PE'] * (legCount - 1) if legCount > 1 else ['-']
                    pe_strike_list = ['0'] + [str(x) for x in pe_prices[1:]] if legCount > 1 else ['0']

                    current_ticksize = str(tick_size * 2)
                    p01, p02, p05, p08, p09 = '200', '9', '20', '0', '5'
                    p10, p11, p12, p13, p14 = '5', '10', '50', '5', '5'
                    p16, p23, p24 = '1', '9', '300'
                else:
                    itype_list = ['OPTSTK'] * legCount
                    expiry_list = [option_expiry] * legCount
                    pe_otype_list = ['PE'] * legCount
                    pe_strike_list = [str(x) for x in pe_prices]

                row_pe = ['0'] * len(headers)
                row_pe[0] = str(pid)
                pid += 1
                row_pe[5] = str(stgCode)

                # Mapped symbol
                row_pe[6] = mcx_symbol

                row_pe[7] = current_lotSize
                row_pe[8] = '-'.join(itype_list)
                row_pe[9] = '|'.join(expiry_list)
                row_pe[10] = '|'.join(pe_otype_list)
                row_pe[11] = '|'.join(pe_strike_list)
                row_pe[12] = formatted_ratio
                row_pe[13] = buySellStr
                row_pe[24] = str(gap)
                row_pe[25] = current_ticksize
                row_pe[16] = adv_bsoq
                row_pe[17] = adv_bqty
                row_pe[18] = str(int(float(adv_bprice)) * 100) if adv_bprice != '0' else '0'
                row_pe[19] = str(int(float(adv_sprice)) * 100) if adv_sprice != '0' else '0'
                row_pe[20] = adv_sqty
                row_pe[21] = adv_ssoq
                row_pe[15] = '1'
                row_pe[26] = '2'
                row_pe[27] = '2'
                row_pe[29] = '5'
                row_pe[30] = '50' if mode == "IOC" else '200'
                row_pe[31] = '2'
                row_pe[32] = '1'
                row_pe[33] = 'FALSE' if mode == "IOC" else 'TRUE'
                row_pe[34] = '5'
                row_pe[37] = '2'
                row_pe[38] = '1'
                row_pe[39] = '500'

                row_pe[46] = p01
                row_pe[47] = p02
                row_pe[50] = p05
                row_pe[51] = '200'
                row_pe[52] = '2575'
                row_pe[53] = p08
                row_pe[54] = p09
                row_pe[55] = p10
                row_pe[56] = p11
                row_pe[57] = p12
                row_pe[58] = p13
                row_pe[59] = p14
                row_pe[60] = '1'
                row_pe[61] = p16
                row_pe[64] = '1999'
                row_pe[66] = '30'
                row_pe[68] = p23
                row_pe[69] = p24
                row_pe[86] = '101'
                row_pe[28] = '80' if mode == "IOC" else '0'

                rows.append(','.join(row_pe))

            if use_individual:
                break

    csv_content = '\n'.join(rows)
    output = io.StringIO(csv_content)
    output.seek(0)

    return send_file(
        io.BytesIO(output.read().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=fileName
    )

if __name__ == '__main__':
    app.run(debug=True)
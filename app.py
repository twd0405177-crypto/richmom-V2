import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
import pandas as pd
import plotly.express as px
import json
import datetime
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from PIL import Image
import urllib.parse

# 1. 設定網頁標題
st.set_page_config(page_title="RichMom 懶人記帳", page_icon="logo.png", layout="centered")

# --- 強制注入 Logo 給 iPhone ---
logo_url = "https://raw.githubusercontent.com/twd0405177-crypto/richmom-accounting/main/logo.png"
st.markdown(
    f"""
    <head>
        <link rel="apple-touch-icon" href="{logo_url}">
    </head>
    """,
    unsafe_allow_html=True
)

st.title("💰 RichMom 懶人記帳 (姊妹貼心版)")

# --- 2. 讀取網址參數 (實現「記住所有設定」功能) ---
# 讀取網址中的參數
query_params = st.query_params
default_api = query_params.get("api", "")
default_sheet = query_params.get("sheet", "")
# 讀取網址裡的卡片設定 (如果有)
default_cards_param = query_params.get("cards", "")
default_banks_param = query_params.get("banks", "")

# --- 3. 側邊欄：使用者設定 ---
with st.sidebar:
    st.header("⚙️ 設定區")
    
    user_api_key = st.text_input("1️⃣ Gemini API Key", value=default_api, type="password")
    user_sheet_name = st.text_input("2️⃣ Google 試算表名稱", value=default_sheet, placeholder="例如：2026年記帳本")
    
    st.caption("💡 提示：不想每次重打？請看網頁最下方的「懶人連結教學」！")

    st.divider()
    st.header("💳 帳戶與信用卡")
    
    # --- 這裡改為不寫死，優先讀取網址參數，沒有的話就留白 ---
    # 如果網址有參數，就用網址的；如果沒有，就給個範例文字
    initial_cards = default_cards_param if default_cards_param else ""
    initial_banks = default_banks_param if default_banks_param else ""

    # 卡片輸入框
    user_cards_str = st.text_area(
        "常用信用卡 (用逗號隔開)", 
        value=initial_cards, 
        placeholder="例如：台新Gogo, 富邦J卡 (請自行輸入)"
    )
    # 自動把中文逗號變英文
    user_cards_str = user_cards_str.replace("，", ",") 
    user_cards = [x.strip() for x in user_cards_str.split(",") if x.strip()]

    # 銀行輸入框
    user_banks_str = st.text_area(
        "常用網銀/銀行 (用逗號隔開)", 
        value=initial_banks, 
        placeholder="例如：中國信託, 郵局 (請自行輸入)"
    )
    # 自動把中文逗號變英文
    user_banks_str = user_banks_str.replace("，", ",") 
    user_banks = [x.strip() for x in user_banks_str.split(",") if x.strip()]
    
    all_payment_methods = ["現金"] + user_cards + user_banks

    st.divider()
    if "gcp_service_account" in st.secrets:
        bot_email = st.secrets["gcp_service_account"]["client_email"]
        with st.expander("🤖 查看機器人 Email"):
            st.code(bot_email, language="text")

# --- 4. 連接 Google Sheet ---
if not user_api_key or not user_sheet_name:
    st.warning("👉 請在左側輸入 API Key 和 試算表名稱 才能開始記帳喔！")
    st.stop()

# 初始化 AI
try:
    genai.configure(api_key=user_api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    st.sidebar.success("✅ AI 連線成功")
except Exception as e:
    st.sidebar.error(f"AI 連線失敗: {e}")

# 初始化試算表
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
try:
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    client = gspread.authorize(creds)
    sheet = client.open(user_sheet_name).sheet1
    st.toast(f"✅ 成功連線到：{user_sheet_name}")
except Exception as e:
    st.error(f"❌ 試算表連線失敗：{e}")
    st.stop()

# 定義大分類 (用於圓餅圖)
main_categories = ["食 (餐飲)", "衣 (服飾)", "住 (房租/水電)", "行 (交通/車費)", "育 (進修/書)", "樂 (娛樂/旅行)", "醫療", "保險", "投資", "其他"]

# --- 5. 讀取資料 ---
def load_data():
    try:
        data = sheet.get_all_records()
        expected_cols = ["日期", "類別", "項目", "金額", "付款方式"]
        
        if not data: return pd.DataFrame(columns=expected_cols)
        df = pd.DataFrame(data)
        
        if "類別" not in df.columns: df["類別"] = "未分類"
        if "付款方式" not in df.columns: df["付款方式"] = "現金"
        
        if not df.empty:
            df['日期'] = pd.to_datetime(df['日期'], errors='coerce')
            df['金額'] = pd.to_numeric(df['金額'], errors='coerce').fillna(0)
            df['年份月份'] = df['日期'].dt.strftime('%Y-%m')
        return df
    except:
        return pd.DataFrame(columns=["日期", "類別", "項目", "金額", "付款方式"])

df = load_data()
if not df.empty and '年份月份' in df.columns:
    all_months = sorted(df['年份月份'].dropna().unique(), reverse=True)
else:
    all_months = []

# --- 主功能區 ---
tab1, tab2, tab_inst, tab3, tab4 = st.tabs(["📸 AI 記帳", "✍️ 手動輸入", "💳 分期計算", "📊 財務分析", "📂 資料管理"])

if "ocr_result" not in st.session_state:
    st.session_state.ocr_result = None

# === Tab 1: AI 記帳 ===
with tab1:
    st.subheader("🤖 AI 智慧記帳")
    text_input = st.text_input("輸入內容 (文字或照片)", key="ai_input")
    uploaded_file = st.file_uploader("上傳照片", type=["jpg", "png"])
    
    if st.button("✨ AI 分析", type="primary"):
        if text_input or uploaded_file:
            today_str = str(datetime.date.today())
            methods_str = ", ".join(all_payment_methods)
            cats_str = ", ".join(main_categories)
            
            prompt = f"""
            今天是 {today_str}。
            付款方式選項：{methods_str}。
            類別選項：{cats_str}。
            任務：提取記帳資訊。日期若為過去請推算。
            回傳 JSON 格式: {{ "date": "YYYY-MM-DD", "category": "類別", "item": "項目", "amount": 100, "method": "付款方式" }}
            輸入：{text_input}
            """
            with st.spinner("AI 分析中..."):
                try:
                    inputs = [prompt]
                    if uploaded_file: inputs.append(Image.open(uploaded_file))
                    response = model.generate_content(inputs)
                    result = json.loads(response.text.replace("```json", "").replace("```", "").strip())
                    st.session_state.ocr_result = result
                    st.success("分析成功！")
                except: st.error("AI 讀取失敗")

    if st.session_state.ocr_result:
        with st.container(border=True):
            current_amount = st.session_state.ocr_result.get("amount", 0)
            
            c1, c2 = st.columns(2)
            new_date = c1.text_input("日期", st.session_state.ocr_result.get("date"))
            
            ai_cat = st.session_state.ocr_result.get("category", "其他")
            try: cat_idx = main_categories.index(ai_cat)
            except: cat_idx = len(main_categories)-1
            new_category = c2.selectbox("類別", main_categories, index=cat_idx, key="ai_cat")
            
            c3, c4 = st.columns(2)
            new_item = c3.text_input("項目", st.session_state.ocr_result.get("item"))
            new_amount = c4.number_input("金額", value=current_amount)
            
            ai_method = st.session_state.ocr_result.get("method", "現金")
            if ai_method not in all_payment_methods: ai_method = "現金"
            try: idx = all_payment_methods.index(ai_method)
            except: idx = 0
            new_method = st.selectbox("付款方式", all_payment_methods, index=idx, key="ai_method")
            
            if st.button("✅ 確認寫入"):
                try:
                    sheet.append_row([new_date, new_category, new_item, new_amount, new_method])
                    st.toast("已儲存！")
                    st.session_state.ocr_result = None
                    st.rerun()
                except Exception as e: st.error(f"寫入失敗: {e}")

# === Tab 2: 手動輸入 ===
with tab2:
    st.subheader("✍️ 手動輸入")
    
    with st.form("manual"):
        c1, c2 = st.columns(2)
        m_date = c1.date_input("日期", datetime.date.today())
        m_category = c2.selectbox("類別 (用於圓餅圖)", main_categories)
        
        c3, c4 = st.columns(2)
        m_item = c3.text_input("項目名稱", placeholder="例如：午餐")
        m_amount = c4.number_input("金額", min_value=0)
        
        m_method = st.selectbox("付款方式", all_payment_methods)

        if st.form_submit_button("✅ 新增"):
            if m_item and m_amount > 0:
                sheet.append_row([str(m_date), m_category, m_item, m_amount, m_method])
                st.success(f"已儲存：{m_category} - {m_item} ${m_amount}")
                st.rerun()
            else:
                st.warning("請輸入項目和金額")

# === Tab 3: 分期與定期扣款 ===
with tab_inst:
    st.subheader("💳 分期與定期扣款計算機")
    
    with st.container(border=True):
        i_col1, i_col2 = st.columns(2)
        i_item = i_col1.text_input("商品名稱", placeholder="例如：iPhone 16")
        
        installment_sources = user_cards + user_banks
        i_card = i_col2.selectbox("扣款方式 (信用卡/銀行)", installment_sources if installment_sources else ["請先設定信用卡"])
        
        i_col3, i_col4 = st.columns(2)
        i_price = i_col3.number_input("總金額", min_value=0, step=100, value=30000)
        
        months_options = [1, 3, 6, 12, 18, 24, 30, 36]
        i_months = i_col4.selectbox("期數 (選 1 為一次付清)", months_options, index=3) 
        
        st.markdown("---")
        interest_mode = st.radio("利息計算", ["零利率", "固定手續費", "利率 (%)"], horizontal=True)

        total_pay = i_price
        if interest_mode == "固定手續費":
            interest_amt = st.number_input("總手續費", min_value=0)
            total_pay += interest_amt
        elif interest_mode == "利率 (%)":
            rate = st.number_input("總利率 %", min_value=0.0, step=0.1)
            total_pay += int(i_price * (rate / 100))
        
        monthly_pay = int(total_pay / i_months)
        start_date = st.date_input("首期扣款日", datetime.date.today())

        if i_months == 1:
            st.info(f"💵 一次付清： **${total_pay:,}**")
        else:
            st.info(f"🗓️ 每期約 **${monthly_pay:,}** (總額 ${total_pay:,})")

        if st.button("📝 生成並寫入", type="primary"):
            if i_item and total_pay > 0:
                try:
                    rows_to_add = []
                    curr = start_date
                    i_category = "分期/定期" if i_months > 1 else "其他"
                    
                    for m in range(1, i_months + 1):
                        name_suffix = "" if i_months == 1 else f" ({m}/{i_months})"
                        final_name = f"{i_item}{name_suffix}"
                        if i_months == 1:
                            pay = total_pay
                        else:
                            pay = monthly_pay + (total_pay - monthly_pay * i_months) if m==1 else monthly_pay
                        rows_to_add.append([str(curr), i_category, final_name, pay, i_card])
                        curr += relativedelta(months=1)
                    
                    sheet.append_rows(rows_to_add)
                    st.balloons()
                    st.success(f"成功寫入 {i_months} 筆資料！")
                    st.rerun()
                except Exception as e:
                    st.error(f"寫入失敗：{e}")

# === Tab 4: 財務分析 ===
with tab3:
    if not df.empty and all_months:
        month = st.selectbox("📅 選擇月份", all_months)
        m_df = df[df['年份月份'] == month]
        
        total_spend = int(m_df['金額'].sum())
        st.metric(f"{month} 總花費", f"${total_spend:,}")
        
        st.divider()
        c1, c2 = st.columns(2)
        
        with c1: 
            st.subheader("類別比例")
            if "類別" in m_df.columns:
                st.plotly_chart(px.pie(m_df, values='金額', names='類別', hole=0.4), use_container_width=True)
            else:
                st.warning("舊資料無類別，顯示項目")
                st.plotly_chart(px.pie(m_df, values='金額', names='項目', hole=0.4), use_container_width=True)
                
        with c2:
            st.subheader("付款方式")
            st.plotly_chart(px.pie(m_df, values='金額', names='付款方式', hole=0.4), use_container_width=True)
            
    else: st.info("無資料")

# === Tab 5: 資料管理 ===
with tab4:
    st.subheader("📂 資料管理")
    if not df.empty:
        search_term = st.text_input("🔍 搜尋資料", placeholder="關鍵字...")
        df_edit = df.copy()
        df_edit["🗑️ 刪除"] = False
        
        if search_term:
            mask = df_edit.astype(str).apply(lambda x: x.str.contains(search_term, case=False)).any(axis=1)
            df_edit = df_edit[mask]
        
        cols = ["🗑️ 刪除", "日期", "類別", "項目", "金額", "付款方式"]
        for c in cols:
            if c not in df_edit.columns: df_edit[c] = ""
            
        edited_df = st.data_editor(
            df_edit[cols], 
            num_rows="dynamic", use_container_width=True,
            column_config={"🗑️ 刪除": st.column_config.CheckboxColumn("刪除?", default=False)}
        )
        
        if st.button("💾 儲存變更"):
            if search_term: st.warning("搜尋模式下無法儲存")
            else:
                try:
                    rows = edited_df[edited_df["🗑️ 刪除"] == False].drop(columns=["🗑️ 刪除"])
                    header = ["日期", "類別", "項目", "金額", "付款方式"]
                    rows = rows.reindex(columns=header)
                    rows['日期'] = pd.to_datetime(rows['日期']).dt.strftime('%Y-%m-%d')
                    rows['付款方式'] = rows['付款方式'].fillna("現金")
                    
                    sheet.clear()
                    sheet.update([header] + rows.values.tolist())
                    st.success("更新成功")
                    st.rerun()
                except Exception as e: st.error(f"失敗: {e}")

# --- 8. 懶人連結教學區 ---
st.divider()
with st.expander("🤫 懶人秘密：如何讓 APP 記住我的設定？"):
    st.markdown(f"""
    1. 在上方左側欄位，填好妳的 **API Key**、**試算表名稱**。
    2. 填好妳常用的 **信用卡** 和 **銀行** (用逗號隔開)。
    3. **👇 點擊下面這個按鈕**，它會生成妳的專屬網址。
    4. 把那個網址存成書籤，下次打開所有欄位都自動填好了！
    """)
    
    # 用程式自動抓取目前使用者輸入的內容
    if st.button("🔗 生成我的專屬連結"):
        base_url = "https://richmom-accounting-sisters.streamlit.app/" 
        
        # 進行網址編碼，確保中文和特殊符號不會出錯
        params = []
        if user_api_key: params.append(f"api={user_api_key}")
        if user_sheet_name: params.append(f"sheet={urllib.parse.quote(user_sheet_name)}")
        if user_cards_str: params.append(f"cards={urllib.parse.quote(user_cards_str)}")
        if user_banks_str: params.append(f"banks={urllib.parse.quote(user_banks_str)}")
        
        final_url = base_url + "?" + "&".join(params)
        
        st.code(final_url, language="text")
        st.success("👆 複製上面這個網址，加到「加入主畫面」或「我的最愛」，下次連卡片都不用重打囉！")
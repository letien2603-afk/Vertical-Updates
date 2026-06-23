import streamlit as st
import pandas as pd
import re
import io

def clean_original_invoice(inv): 
    """Xoá bỏ các phần COR, REV và các số theo sau để lấy Original Invoice""" 
    if pd.isnull(inv): 
        return "" 
    inv = str(inv).strip()
    # Dùng [\s\-]* để quét MỌI dấu gạch ngang (bao gồm --COR)
    pattern = re.compile(r'[\s\-]*(COR|REV)\d*$', re.IGNORECASE) 
    cleaned = re.sub(pattern, '', inv).strip()
    return cleaned.rstrip('- ')

def parse_suffix_for_ranking(inv): 
    """Phân loại để tìm ra Invoice mới nhất theo 3 cấp độ""" 
    inv = str(inv).upper().strip()
    match = re.search(r'([\s\-]*)(COR|REV)(\d*)$', inv) 
    if not match: 
        return (0, 0, 0)
    
    separator = match.group(1)
    type_str = match.group(2)
    num_str = match.group(3)
    
    type_val = 2 if type_str == 'COR' else 1
    num_val = int(num_str) if num_str else 1
    dash_count = separator.count('-') # Đếm số lượng gạch ngang để ưu tiên --COR hơn -COR
    
    return (num_val, type_val, dash_count)

def increment_or_append_suffix(val, suffix_type): 
    """Tính toán cấp độ (level) của hoá đơn và gắn hậu tố mới""" 
    if pd.isnull(val): return val 
    val = str(val).strip()
    match = re.search(r'(?i)(.*?)(?:[\s\-]*)(COR|REV)(\d*)$', val) 
    if match: 
        prefix = match.group(1).rstrip('- ') 
        num_str = match.group(3)
        current_num = int(num_str) if num_str else 1
        next_num = current_num + 1
        return f"{prefix}-{suffix_type}{next_num}"
    else:
        return f"{val.rstrip('- ')}-{suffix_type}"

def replace_cor_with_rev(val): 
    """Thay thế chữ COR thành REV để đồng bộ cấp độ""" 
    if pd.isnull(val): return val 
    val = str(val)
    return re.sub(r'COR(\d*)$', r'REV\1', val)

def main():
    st.set_page_config(page_title="Invoice Correction Tool", layout="wide")
    st.title("Vertical Bulk Corrections")
    
    # Khởi tạo session state để giữ các nút download không bị biến mất
    if 'processed' not in st.session_state:
        st.session_state.processed = False
        st.session_state.excel_data = None
        st.session_state.csv_data = None

    # --- UI GIAO DIỆN STREAMLIT ---
    col1, col2 = st.columns(2)
    with col1:
        req_file = st.file_uploader("1. Upload Requested Correction file", type=['xlsx', 'xls', 'xlsb'])
    with col2:
        atf_file = st.file_uploader("2. Upload ATF file", type=['xlsx', 'xls', 'xlsb'])
        
    user_comment = st.text_input("3. Comment")

    if st.button("Start Data Processing"):
        if not req_file or not atf_file:
            st.error("Error: Need to upload 2 requested files!")
            return
            
        progress_bar = st.progress(0)
        status_text = st.empty()

        try:
            # Hàm phụ trợ để xử lý cho cả định dạng xlsx, xls và xlsb
            def load_excel(file_upload):
                if file_upload.name.endswith('.xlsb'):
                    return pd.read_excel(file_upload, sheet_name=0, engine='pyxlsb')
                else:
                    return pd.read_excel(file_upload, sheet_name=0)

            status_text.text("Scanning the uploaded files...")
            df_req = load_excel(req_file)
            df_atf = load_excel(atf_file)
            progress_bar.progress(20)

            # --- XỬ LÝ REQUESTED CORRECTION ---
            status_text.text("Scanning Requested Correction file...")
            df_req['Text'] = df_req['Invoice Number'].apply(lambda x: isinstance(x, str))

            def format_invoice(row):
                val = row['Invoice Number']
                if not row['Text'] and pd.notnull(val):
                    return '00' + str(int(val))
                return str(val)

            df_req['Invoice Number'] = df_req.apply(format_invoice, axis=1)
            df_req['Original Invoice'] = df_req['Invoice Number'].apply(clean_original_invoice)
            original_invoices_memory = df_req['Original Invoice'].drop_duplicates().tolist()

            if 'CONFIRMED VERTICAL' in df_req.columns:
                vertical_mapping = dict(zip(df_req['Original Invoice'], df_req['CONFIRMED VERTICAL']))
            else:
                vertical_mapping = {}

            progress_bar.progress(40)

            # --- XỬ LÝ ATF FILE & MATCHING ---
            status_text.text("Processing ATF file and matching invoices...")
            df_atf['Original Invoice'] = df_atf['Invoice Number'].apply(clean_original_invoice)
            matched_atf = df_atf[df_atf['Original Invoice'].isin(original_invoices_memory)].copy()
			matched_atf['SortKey'] = matched_atf['Invoice Number'].apply(parse_suffix_for_ranking)
		# [CẬP NHẬT MỚI]: Dùng Temp_Amount để làm sạch trị tuyệt đối và gom nhóm 
            matched_atf['Temp_Amount'] = pd.to_numeric(matched_atf['Transaction Amount'], errors='coerce').abs()
            max_sort_keys = matched_atf.groupby(['Original Invoice', 'Temp_Amount'], dropna=False)['SortKey'].transform('max')
            matched_atf.drop(columns=['Temp_Amount'], inplace=True)
            latest_atf = matched_atf[matched_atf['SortKey'] == max_sort_keys].copy()


            # Skip Vertical
            col_vertical_atf = 'Vertical'
            if col_vertical_atf in latest_atf.columns:
                latest_atf['Req_Vertical'] = latest_atf['Original Invoice'].map(vertical_mapping)
                val_atf = latest_atf[col_vertical_atf].astype(str).str.strip().str.lower()
                val_req = latest_atf['Req_Vertical'].astype(str).str.strip().str.lower()
                latest_atf = latest_atf[val_atf != val_req].copy()
                latest_atf.drop(columns=['Req_Vertical'], inplace=True)
                
            if latest_atf.empty:
                st.warning("Verticals in all requested invoices have been updated to match with the requested file or no matching invoices to process.")
                progress_bar.progress(100)
                st.session_state.processed = False
                return

            progress_bar.progress(60)

            # --- TẠO DỮ LIỆU COR VÀ REV ---
            status_text.text("Updating invoices suffix and Comments...")
            df_cor = latest_atf.copy()
            df_rev = latest_atf.copy()

            # Xử lý COR
            df_cor['Transaction Number'] = df_cor['Transaction Number'].apply(lambda x: increment_or_append_suffix(x, 'COR'))
            df_cor['Invoice Number'] = df_cor['Invoice Number'].apply(lambda x: increment_or_append_suffix(x, 'COR'))
            df_cor['Transaction Type'] = 'MANUAL_ADJ'
            df_cor['Vertical'] = df_cor['Original Invoice'].map(vertical_mapping)

            # Xử lý REV
            df_rev['Transaction Number'] = df_cor['Transaction Number'].apply(replace_cor_with_rev)
            df_rev['Invoice Number'] = df_cor['Invoice Number'].apply(replace_cor_with_rev)
            df_rev['Transaction Type'] = 'MANUAL_ADJ'

            cols_to_invert = ['Transaction Amount', 'EUR Value', 'CAD Value', 'GBP Value','Native Currency','AUD Value']
            for col in cols_to_invert:
                if col in df_rev.columns:
                    df_rev[col] = pd.to_numeric(df_rev[col], errors='coerce') * -1

            # --- APPLY COMMENTS VÀ REMOVE PERIOD ---
            for df in [df_cor, df_rev]:
                if 'Period' in df.columns:
                    df.drop(columns=['Period'], inplace=True)
                
                if user_comment:
                    if 'Comments' in df.columns:
                        df['Comments'] = user_comment
                    elif 'Comment' in df.columns:
                        df['Comment'] = user_comment
                    else:
                        df['Comments'] = user_comment
                
                df.drop(columns=['SortKey', 'Original Invoice'], errors='ignore', inplace=True)

            # =======================================================
            # CONSOLIDATE (GỘP) COR VÀ REV THÀNH 1 SHEET UPLOAD
            # =======================================================
            df_upload = pd.concat([df_cor, df_rev], ignore_index=True)
            
            # =======================================================
            # FORMAT CỘT THÀNH NUMBER (Không thập phân, không dấu phẩy)
            # =======================================================
            format_cols = ['Source Business Unit ID', 'Business Unit ID']
            for col in format_cols:
                if col in df_upload.columns:
                    # Chuyển kiểu dữ liệu thành Int64 (kiểu số nguyên của Pandas có hỗ trợ giá trị rỗng).
                    # Quá trình này sẽ cắt bỏ phần đuôi .0 hoặc định dạng khoa học ở các dãy số cực dài.
                    df_upload[col] = pd.to_numeric(df_upload[col], errors='coerce').astype('Int64')

            progress_bar.progress(80)
            status_text.text("Creating the output files...")

            # --- CHUẨN BỊ XUẤT FILE ĐẦU RA ---
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                df_upload.to_excel(writer, sheet_name='Upload', index=False)
            
            csv_buffer = df_upload.to_csv(index=False).encode('utf-8-sig')

            # Lưu vào bộ nhớ Session State để giữ nút Download
            st.session_state.excel_data = excel_buffer.getvalue()
            st.session_state.csv_data = csv_buffer
            st.session_state.processed = True

            progress_bar.progress(100)
            status_text.success("Completed data processing. Files are ready to download")

        except Exception as e:
            st.error(f"Error: data processing error: {e}")
            progress_bar.empty()
            st.session_state.processed = False

    # --- HIỂN THỊ NÚT DOWNLOAD ---
    if st.session_state.processed:
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            st.download_button(
                label="📥 Download Excel (.xlsx)",
                data=st.session_state.excel_data,
                file_name="Vertical Bulk Corrections.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        with col_btn2:
            st.download_button(
                label="📥 Download CSV (.csv)",
                data=st.session_state.csv_data,
                file_name="Vertical Bulk Corrections.csv",
                mime="text/csv"
            )

if __name__ == "__main__":
    main()

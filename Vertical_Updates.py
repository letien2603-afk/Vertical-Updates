import streamlit as st
import pandas as pd
import re
import io

def clean_original_invoice(inv):
    """Xoá bỏ các phần COR, REV và các số theo sau để lấy Original Invoice"""
    if pd.isnull(inv):
        return ""
    inv = str(inv)
    pattern = re.compile(r'\s*-?\s*(COR|REV)\d*$', re.IGNORECASE)
    return re.sub(pattern, '', inv).strip()

def parse_suffix_for_ranking(inv):
    """Phân loại để tìm ra Invoice mới nhất"""
    inv = str(inv).upper()
    match = re.search(r'\s*-?\s*(COR|REV)(\d*)$', inv)
    if not match:
        return (0, 0)
    
    type_str = match.group(1)
    num_str = match.group(2)
    type_val = 2 if type_str == 'COR' else 1
    num_val = int(num_str) if num_str else 1
    return (num_val, type_val)

def increment_or_append_suffix(val, suffix_type):
    """Tính toán cấp độ (level) của hoá đơn và gắn hậu tố mới"""
    if pd.isnull(val): return val
    val = str(val)
    match = re.search(r'(?i)(.*?)(?:-?\s*)(COR|REV)(\d*)$', val)
    if match:
        prefix = match.group(1).strip()
        num_str = match.group(3)
        current_num = int(num_str) if num_str else 1
        next_num = current_num + 1
        return f"{prefix}-{suffix_type}{next_num}"
    else:
        return f"{val.strip()}-{suffix_type}"

def replace_cor_with_rev(val):
    """Thay thế chữ COR thành REV để sheet REV đồng bộ cấp độ với sheet COR"""
    if pd.isnull(val): return val
    val = str(val)
    return re.sub(r'COR(\d*)$', r'REV\1', val)

def main():
    st.set_page_config(page_title="Invoice Correction Tool", layout="wide")
    st.title("Chương Trình Xử Lý Invoice & ATF")
    
    # --- UI GIAO DIỆN STREAMLIT ---
    # 1. & 2. Upload file
    col1, col2 = st.columns(2)
    with col1:
        req_file = st.file_uploader("1. Upload Requested Correction file (.xlsx)", type=['xlsx', 'xls'])
    with col2:
        atf_file = st.file_uploader("2. Upload ATF file (.xlsx)", type=['xlsx', 'xls'])
        
    # 3. Input Comment
    user_comment = st.text_input("3. Nhập Comment (Sẽ áp dụng cho toàn bộ sheet COR và REV):")

    # Nút thực thi
    if st.button("Bắt đầu xử lý dữ liệu"):
        if not req_file or not atf_file:
            st.error("Lỗi: Vui lòng upload đầy đủ 2 file!")
            return
            
        # 5. Thanh tiến trình (Progress bar)
        progress_bar = st.progress(0)
        status_text = st.empty()

        try:
            status_text.text("Đang đọc dữ liệu từ file Excel...")
            df_req = pd.read_excel(req_file, sheet_name=0)
            df_atf = pd.read_excel(atf_file, sheet_name=0)
            progress_bar.progress(20)

            # --- XỬ LÝ REQUESTED CORRECTION ---
            status_text.text("Đang xử lý Requested Correction file...")
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
            status_text.text("Đang xử lý ATF file và matching invoices...")
            df_atf['Original Invoice'] = df_atf['Invoice Number'].apply(clean_original_invoice)
            matched_atf = df_atf[df_atf['Original Invoice'].isin(original_invoices_memory)].copy()

            matched_atf['SortKey'] = matched_atf['Invoice Number'].apply(parse_suffix_for_ranking)
            max_sort_keys = matched_atf.groupby('Original Invoice')['SortKey'].transform('max')
            latest_atf = matched_atf[matched_atf['SortKey'] == max_sort_keys].copy()

            col_vertical_atf = 'Vertical'
            if col_vertical_atf in latest_atf.columns:
                latest_atf['Req_Vertical'] = latest_atf['Original Invoice'].map(vertical_mapping)
                val_atf = latest_atf[col_vertical_atf].astype(str).str.strip().str.lower()
                val_req = latest_atf['Req_Vertical'].astype(str).str.strip().str.lower()
                latest_atf = latest_atf[val_atf != val_req].copy()
                latest_atf.drop(columns=['Req_Vertical'], inplace=True)
                
            if latest_atf.empty:
                st.warning("Tất cả Invoice đều đã khớp Vertical hoặc không có dữ liệu để update.")
                progress_bar.progress(100)
                return

            progress_bar.progress(60)

            # --- TẠO SHEETS COR VÀ REV ---
            status_text.text("Đang tạo sheet COR/REV và cập nhật Comment/Period...")
            df_cor = latest_atf.copy()
            df_rev = latest_atf.copy()

            # Sheet COR
            df_cor['Transaction Number'] = df_cor['Transaction Number'].apply(lambda x: increment_or_append_suffix(x, 'COR'))
            df_cor['Invoice Number'] = df_cor['Invoice Number'].apply(lambda x: increment_or_append_suffix(x, 'COR'))
            df_cor['Transaction Type'] = 'MANUAL_ADJ'
            df_cor['Vertical'] = df_cor['Original Invoice'].map(vertical_mapping)

            # Sheet REV
            df_rev['Transaction Number'] = df_cor['Transaction Number'].apply(replace_cor_with_rev)
            df_rev['Invoice Number'] = df_cor['Invoice Number'].apply(replace_cor_with_rev)
            df_rev['Transaction Type'] = 'MANUAL_ADJ'

            cols_to_invert = ['Transaction Amount', 'EUR Value', 'CAD Value', 'GBP Value']
            for col in cols_to_invert:
                if col in df_rev.columns:
                    df_rev[col] = pd.to_numeric(df_rev[col], errors='coerce') * -1

            # --- APPLY COMMENTS VÀ REMOVE PERIOD ---
            for df in [df_cor, df_rev]:
                # Xóa cột Period
                if 'Period' in df.columns:
                    df.drop(columns=['Period'], inplace=True)
                
                # Cập nhật cột Comments nếu user có nhập
                if user_comment:
                    # Hỗ trợ cả 'Comment' và 'Comments' tùy thuộc file nguồn
                    if 'Comments' in df.columns:
                        df['Comments'] = user_comment
                    elif 'Comment' in df.columns:
                        df['Comment'] = user_comment
                    else:
                        # Nếu file gốc không có cột này, tự động tạo mới
                        df['Comments'] = user_comment
                
                # Xóa các cột tạm xử lý thuật toán
                df.drop(columns=['SortKey', 'Original Invoice'], errors='ignore', inplace=True)

            progress_bar.progress(80)
            status_text.text("Đang nén dữ liệu để tải xuống...")

            # --- CHUẨN BỊ XUẤT FILE ĐẦU RA ---
            # EXCEL OUTPUT
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                df_cor.to_excel(writer, sheet_name='COR', index=False)
                df_rev.to_excel(writer, sheet_name='REV', index=False)
            
            # 4. CSV OUTPUT
            # Gộp dữ liệu 2 bản COR và REV lại chung 1 file CSV. Cột "Sheet_Type" sẽ được gắn tự động để phân biệt.
            df_csv = pd.concat([df_cor.assign(Sheet_Type='COR'), df_rev.assign(Sheet_Type='REV')], ignore_index=True)
            csv_buffer = df_csv.to_csv(index=False).encode('utf-8-sig') # Dùng utf-8-sig để giữ nguyên font trên Excel

            progress_bar.progress(100)
            status_text.success("Hoàn tất xử lý! Vui lòng tải các file kết quả bên dưới.")

            # Hiển thị nút Tải Xuống
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                st.download_button(
                    label="📥 Tải xuống File Excel (.xlsx)",
                    data=excel_buffer.getvalue(),
                    file_name="Matched_Latest_Invoices.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            with col_btn2:
                st.download_button(
                    label="📥 Tải xuống File CSV (.csv)",
                    data=csv_buffer,
                    file_name="Matched_Latest_Invoices.csv",
                    mime="text/csv"
                )

        except Exception as e:
            st.error(f"Đã xảy ra lỗi trong quá trình xử lý: {e}")
            progress_bar.empty()

if __name__ == "__main__":
    main()

import streamlit as st 
import pandas as pd 
import re 
import io

def clean_original_invoice(inv): 
    """Xoá bỏ các phần COR, REV và các số theo sau để lấy Original Invoice""" 
    if pd.isnull(inv): 
        return "" 
    inv = str(inv).strip()
    # [CẬP NHẬT]: Dùng [\s\-]* để quét MỌI dấu gạch ngang (nhận diện được cả --COR) [1]
    pattern = re.compile(r'[\s\-]*(COR|REV)\d*$', re.IGNORECASE) 
    cleaned = re.sub(pattern, '', inv).strip()
    return cleaned.rstrip('- ')

def parse_suffix_for_ranking(inv): 
    """Phân loại để tìm ra Invoice mới nhất""" 
    inv = str(inv).upper().strip()
    # [CẬP NHẬT]: Tách riêng phần dấu gạch ngang ra để đếm số lượng [1]
    match = re.search(r'([\s\-]*)(COR|REV)(\d*)$', inv) 
    if not match: 
        return (0, 0, 0)
    
    separator = match.group(1)
    type_str = match.group(2)
    num_str = match.group(3)
    
    type_val = 2 if type_str == 'COR' else 1
    num_val = int(num_str) if num_str else 1
    dash_count = separator.count('-') # Đếm gạch ngang, giúp ưu tiên --COR > -COR
    
    return (num_val, type_val, dash_count)

def increment_or_append_suffix(val, suffix_type): 
    """Tính toán cấp độ (level) của hoá đơn và gắn hậu tố mới""" 
    if pd.isnull(val): 
        return val 
    val = str(val).strip()
    # [CẬP NHẬT]: Cắt bỏ sạch các dấu gạch ngang cũ dư thừa trước khi gắn đuôi mới [1]
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
    if pd.isnull(val): 
        return val 
    val = str(val) 
    return re.sub(r'COR(\d*)$', r'REV\1', val) [2]

# ==========================================================
# PHẦN SAU ĐÂY LÀ HÀM MAIN() - BẠN GIỮ NGUYÊN CODE CỦA BẠN 
# ==========================================================
def main(): 
    st.set_page_config(page_title="Invoice Correction Tool", layout="wide") 
    st.title("Vertical Bulk Corrections") [2]
    
    # ... [GIỮ NGUYÊN CÁC ĐOẠN UPLOAD FILE VÀ LOGIC KHÁC CỦA BẠN] ...
    
    # [LƯU Ý QUAN TRỌNG NHẤT]: Tại phần code tìm "Latest Invoice" trong hàm main() của bạn,
    # để lấy được chính xác 13 dòng màu vàng cho invoice 0043905960 (không bị nhân lên 20 dòng hay tụt xuống 10 dòng) [3, 4], 
    # hãy đảm bảo bạn sử dụng logic Temp_Amount (Trị tuyệt đối) như sau:
    
    """
    matched_atf['SortKey'] = matched_atf['Invoice Number'].apply(parse_suffix_for_ranking)
    
    # Chuyển đổi thành số dương để gom nhóm các khoản tiền bị lệch format/dấu
    matched_atf['Temp_Amount'] = pd.to_numeric(matched_atf['Transaction Amount'], errors='coerce').abs()
    
    # Nhóm theo Original Invoice VÀ Temp_Amount
    max_sort_keys = matched_atf.groupby(['Original Invoice', 'Temp_Amount'], dropna=False)['SortKey'].transform('max')
    matched_atf.drop(columns=['Temp_Amount'], inplace=True)
    
    # Lấy ra Latest Invoice
    latest_atf = matched_atf[matched_atf['SortKey'] == max_sort_keys].copy()
    """
    
    # ... [GIỮ NGUYÊN PHẦN XUẤT FILE VÀ CÁC LOGIC KHÁC] ...

if __name__ == "__main__": 
    main() [2]

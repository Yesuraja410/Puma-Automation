import io
import re
import zipfile
import urllib.parse
import pandas as pd
import numpy as np

# Synonyms for auto-mapping columns
COLUMN_SYNONYMS = {
    "sku": [
        "seller sku", "sku", "seller_sku", "sellersku", "ean", "barcode", "upc", 
        "item code", "item_code", "product sku", "product_sku", "seller sku sku"
    ],
    "article_number": [
        "article number", "article no", "article", "article_number", "art no", 
        "art_no", "style code", "style_code", "style number", "style_no"
    ],
    "ecommerce_status": [
        "e-commerce status", "ecommerce status", "status", "ecom status", 
        "listing status", "ecom_status", "channel status", "status_ecom",
        "active status", "listing_status"
    ],
    "launch_date": [
        "launch date", "launch_date", "date launch", "release date", 
        "launch date (dd/mm/yyyy)", "launch date (yyyy-mm-dd)", "launch_dates",
        "launching date", "start date"
    ],
    "gender": [
        "gender", "sex", "target group", "division", "genders", "target_group"
    ],
    "product_name": [
        "product name", "product_name", "name", "title", "item name", 
        "item_name", "description", "product title", "product_title"
    ],
    "color_name": [
        "color name", "color_name", "color", "colour", "color_no", 
        "color number", "color_description", "color description",
        "variation 1", "variation1", "variation_1", "primary variation value (option)"
    ],
    "size": [
        "size", "size_code", "size code", "sizing", "product size", 
        "size_name", "size name", "variation 2", "variation2", "variation_2",
        "variation", "secondary variation value (option)"
    ],
    "quantity": [
        "quantity", "qty", "stock", "inventory", "quantity available", 
        "available qty", "quantity_available", "current stock", "stock_qty"
    ],
    "price": [
        "price", "retail price", "selling price", "amount", "msrp", 
        "price list", "unit price", "selling_price", "retail_price", "rrp",
        "retail price (local currency)"
    ],
    "images": [
        "images", "image", "image url", "image_url", "image urls", 
        "image 1", "image link", "image_link", "product images", 
        "image_urls", "image_links"
    ],
    "size_chart": [
        "size chart", "size_chart", "size chart url", "size_chart_url", 
        "size_chart_link", "chart", "size_chart_link"
    ]
}

CANONICAL_LABELS = {
    "sku": "Seller SKU",
    "article_number": "Article Number",
    "ecommerce_status": "E-commerce Status",
    "launch_date": "Launch Date",
    "gender": "Gender",
    "product_name": "Product Name",
    "color_name": "Color Name",
    "size": "Size",
    "quantity": "Quantity",
    "price": "Price",
    "images": "Images",
    "size_chart": "Size Chart"
}

# ── General Helper Utilities ──────────────────────────────────────────────────

def _safe_str(val):
    if val is None:
        return ""
    if isinstance(val, (pd.Series, np.ndarray)):
        if len(val) == 0:
            return ""
        val = val.iloc[0] if hasattr(val, "iloc") else val[0]
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    return str(val).strip()

def _clean_sku(val):
    s = _safe_str(val)
    if re.fullmatch(r'\d+\.0', s):
        s = s[:-2]
    return s

def _normalise_cols(df):
    df.columns = [_safe_str(c) for c in df.columns]
    return df

def compute_excel_row_numbers(num_rows, header_row=0, skiprows=None):
    skipped = set()
    if isinstance(skiprows, list):
        skipped = set(skiprows)
    elif isinstance(skiprows, int):
        skipped = set(range(skiprows))
        
    kept_indices = []
    file_idx = 0
    needed = (header_row + 1 + num_rows) * 2
    while len(kept_indices) < needed:
        if file_idx not in skipped:
            kept_indices.append(file_idx)
        file_idx += 1
        
    header_file_idx = kept_indices[header_row]
    data_file_indices = kept_indices[header_row + 1 : header_row + 1 + num_rows]
    
    return [idx + 1 for idx in data_file_indices]

def _normalise_article_no(val):
    s = _safe_str(val)
    if not s:
        return ""
    s = s.strip().upper()
    s = re.sub(r'[\s\-]+', '_', s)
    s = s.strip('_')
    return s

def _ecom_status_from_val(val, future_launch):
    s = _safe_str(val).upper()
    if s in ("YES", "Y"):
        return "Yes"
    return "No"

def parse_google_sheets_url(url: str) -> str:
    if "docs.google.com/spreadsheets" not in url:
        return url
    try:
        id_match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
        if not id_match:
            return url
        spreadsheet_id = id_match.group(1)
        
        gid = "0"
        parsed_url = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        if "gid" in query_params:
            gid = query_params["gid"][0]
        elif parsed_url.fragment:
            fragment_params = urllib.parse.parse_qs(parsed_url.fragment)
            if "gid" in fragment_params:
                gid = fragment_params["gid"][0]
            else:
                gid_match = re.search(r"gid=(\d+)", parsed_url.fragment)
                if gid_match:
                    gid = gid_match.group(1)
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"
    except Exception as e:
        print(f"Error parsing Google Sheets URL: {e}")
        return url

# ── General File Reader ───────────────────────────────────────────────────────

def _read_file(file, header_row=0, skiprows=None):
    if file is None:
        return pd.DataFrame()
    
    if isinstance(file, str):
        filename = file
        with open(file, 'rb') as f:
            raw = f.read()
    else:
        filename = getattr(file, "name", "unknown.csv")
        raw = file.read()
        file.seek(0)

    name = filename.lower()
    try:
        if name.endswith(".csv"):
            return pd.read_csv(io.BytesIO(raw), header=header_row, skiprows=skiprows, dtype=str)
        try:
            import python_calamine
            return pd.read_excel(io.BytesIO(raw), header=header_row, skiprows=skiprows, dtype=str, engine="calamine")
        except ImportError:
            return pd.read_excel(io.BytesIO(raw), header=header_row, skiprows=skiprows, dtype=str)
    except Exception:
        return pd.DataFrame()

def get_parse_params(channel: str = None):
    if channel:
        channel_lower = channel.lower()
        if "zalora" in channel_lower:
            # Header in 3rd row (index 2). First two rows ignored.
            return 2, None
        elif "tiktok" in channel_lower:
            # Header in 3rd row (index 2). Ignore 4, 5, 6 rows (indices 3, 4, 5).
            # Also ignore first two rows (indices 0, 1).
            # skiprows=[0, 1, 3, 4, 5]. Since index 2 is not skipped, it becomes the first row (header index 0).
            return 0, [0, 1, 3, 4, 5]
    return 0, [0, 2]

def load_file_to_df(file_or_path, filename: str = None, channel: str = None) -> pd.DataFrame:
    h, s = get_parse_params(channel)
    df = _read_file(file_or_path, header_row=h, skiprows=s)
    
    check_cols = ["Seller SKU", "SKU", "SellerSKU", "Product Name", "Variation 1"]
    if channel:
        channel_lower = channel.lower()
        if "zalora" in channel_lower:
            check_cols.extend(["sellersku", "name", "variation"])
        elif "tiktok" in channel_lower:
            check_cols.extend(["seller sku", "product name", "primary variation value (option)", "secondary variation value (option)"])
            
    if df.empty or not any(c.lower() in [col.lower() for col in df.columns] for c in check_cols):
        df_normal = _read_file(file_or_path, header_row=0, skiprows=None)
        if not df_normal.empty:
            df_normal["_excel_row"] = compute_excel_row_numbers(len(df_normal), 0, None)
            return df_normal
    else:
        if not df.empty:
            df["_excel_row"] = compute_excel_row_numbers(len(df), h, s)
    return df

def load_excel_all_sheets(file_or_path, channel: str = None) -> dict:
    if file_or_path is None:
        return {}
    
    if isinstance(file_or_path, str):
        with open(file_or_path, 'rb') as f:
            raw = f.read()
    else:
        raw = file_or_path.read()
        file_or_path.seek(0)
        
    try:
        try:
            import python_calamine
            xl = pd.ExcelFile(io.BytesIO(raw), engine="calamine")
        except ImportError:
            xl = pd.ExcelFile(io.BytesIO(raw))
            
        sheet_dfs = {}
        h, s = get_parse_params(channel)
        
        sheet_names_to_parse = []
        if channel:
            channel_lower = channel.lower()
            if "zalora" in channel_lower:
                sheet_names_to_parse = [name for name in xl.sheet_names if name.strip().lower() == "upload template"]
                if not sheet_names_to_parse:
                    sheet_names_to_parse = [name for name in xl.sheet_names if name.strip().lower() == "template"]
            elif "tiktok" in channel_lower:
                sheet_names_to_parse = [name for name in xl.sheet_names if name.strip().lower() == "template"]
                if not sheet_names_to_parse:
                    sheet_names_to_parse = [name for name in xl.sheet_names if name.strip().lower() == "upload template"]
                
        # Robust fallback: if sheet_names_to_parse is empty or none of those sheets exist in the file
        if not sheet_names_to_parse or not any(name in xl.sheet_names for name in sheet_names_to_parse):
            # Check for common listing template sheet names
            common_names = ["upload template", "template", "sheet1", "listings", "listing"]
            sheet_names_to_parse = [name for name in xl.sheet_names if name.strip().lower() in common_names]
            
            # If still empty, exclude known helper/instruction sheets
            if not sheet_names_to_parse:
                helpers = {
                    "instruction", "instructions", "example", "examples", "hiddenstyle", "hiddenattr", 
                    "category", "brand", "shippinginsurance", "condition", "specialproductlistingtype", 
                    "templateconfig", "unavailable categories", "readme", "read me", "read_me", "config"
                }
                sheet_names_to_parse = [name for name in xl.sheet_names if name.strip().lower() not in helpers]
            
            # If still empty, use all sheets in the file
            if not sheet_names_to_parse:
                sheet_names_to_parse = xl.sheet_names
                
        for s_name in sheet_names_to_parse:
            df = pd.DataFrame()
            is_fallback = False
            try:
                df = xl.parse(s_name, header=h, skiprows=s, dtype=str)
                check_cols = ["Seller SKU", "SKU", "SellerSKU", "Product Name", "Variation 1"]
                if channel:
                    channel_lower = channel.lower()
                    if "zalora" in channel_lower:
                        check_cols.extend(["sellersku", "name", "variation"])
                    elif "tiktok" in channel_lower:
                        check_cols.extend(["seller sku", "product name", "primary variation value (option)", "secondary variation value (option)"])
                if df.empty or not any(c.lower() in [col.lower() for col in df.columns] for c in check_cols):
                    df = xl.parse(s_name, dtype=str)
                    is_fallback = True
            except Exception:
                try:
                    df = xl.parse(s_name, dtype=str)
                    is_fallback = True
                except Exception:
                    pass
            if not df.empty:
                if is_fallback:
                    df["_excel_row"] = compute_excel_row_numbers(len(df), 0, None)
                else:
                    df["_excel_row"] = compute_excel_row_numbers(len(df), h, s)
                sheet_dfs[s_name] = df
        return sheet_dfs
    except Exception:
        return {}

def load_google_sheet(url: str, channel: str = None) -> pd.DataFrame:
    csv_url = parse_google_sheets_url(url)
    h, s = get_parse_params(channel)
    df = pd.read_csv(csv_url, header=h, skiprows=s, dtype=str)
    
    check_cols = ["Seller SKU", "SKU", "SellerSKU", "Product Name", "Variation 1"]
    if channel:
        channel_lower = channel.lower()
        if "zalora" in channel_lower:
            check_cols.extend(["sellersku", "name", "variation"])
        elif "tiktok" in channel_lower:
            check_cols.extend(["seller sku", "product name", "primary variation value (option)", "secondary variation value (option)"])
            
    if df.empty or not any(c.lower() in [col.lower() for col in df.columns] for c in check_cols):
        df_normal = pd.read_csv(csv_url, dtype=str)
        if not df_normal.empty:
            df_normal["_excel_row"] = compute_excel_row_numbers(len(df_normal), 0, None)
            return df_normal
    else:
        if not df.empty:
            df["_excel_row"] = compute_excel_row_numbers(len(df), h, s)
    return df

def _read_zip(file, header_row=0, skiprows=None):
    raw = file.read()
    file.seek(0)
    frames = []
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for name in zf.namelist():
            if name.lower().endswith((".xlsx", ".xls", ".csv")):
                with zf.open(name) as f:
                    data = f.read()
                    try:
                        if name.lower().endswith(".csv"):
                            df = pd.read_csv(io.BytesIO(data), header=header_row, skiprows=skiprows, dtype=str)
                        else:
                            try:
                                import python_calamine
                                df = pd.read_excel(io.BytesIO(data), header=header_row, skiprows=skiprows, dtype=str, engine="calamine")
                            except ImportError:
                                df = pd.read_excel(io.BytesIO(data), header=header_row, skiprows=skiprows, dtype=str)
                        frames.append(df)
                    except Exception:
                        continue
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

# ── 10 Channel Specific Reading Methods ───────────────────────────────────────

def load_lazada(file, country):
    if file is None:
        return pd.DataFrame()
    df = _read_file(file, header_row=0)
    if df.empty:
        return pd.DataFrame()
    df = _normalise_cols(df)
    df = df.iloc[3:].reset_index(drop=True)
    
    col_map = {"SellerSKU": "SKU", "Quantity": "MP Stock", "status": "MP Status", "price": "MP Price", "name": "MP Product Name"}
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    if "SKU" not in df.columns:
        return pd.DataFrame()
        
    df["Marketplace"] = "Lazada " + country
    df["SKU"] = df["SKU"].apply(_clean_sku)
    df = df[df["SKU"] != ""].copy()
    if "MP Stock" in df.columns:
        df["MP Stock"] = pd.to_numeric(df["MP Stock"].apply(_safe_str), errors="coerce").fillna(0)
    else:
        df["MP Stock"] = 0
    if "MP Price" in df.columns:
        df["MP Price"] = pd.to_numeric(df["MP Price"].apply(_safe_str), errors="coerce").fillna(0.0)
    return df

def _find_sku_col(df):
    for c in ["SKU", "Variation SKU", "Parent SKU", "Seller SKU", "SellerSKU", "ParentSKU", "VariationSKU"]:
        if c in df.columns:
            return c
    for c in df.columns:
        if "sku" in c.lower():
            return c
    return None

def _find_pid_col(df):
    for c in ["Product ID", "ProductID", "product_id", "product id"]:
        if c in df.columns:
            return c
    for c in df.columns:
        if "product" in c.lower() and "id" in c.lower():
            return c
    return None

def _parse_shopee_single(raw_bytes, filename_lower):
    import warnings
    if filename_lower.endswith(".csv"):
        try:
            df = pd.read_csv(io.BytesIO(raw_bytes), header=2, dtype=str)
            df = _normalise_cols(df)
            df = df.iloc[3:].reset_index(drop=True)
            df = df.dropna(how="all").reset_index(drop=True)
            return df
        except Exception:
            return pd.DataFrame()

    engines = []
    try:
        import python_calamine
        engines.append("calamine")
    except ImportError:
        pass
    engines.append("openpyxl")

    for engine in engines:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                df = pd.read_excel(io.BytesIO(raw_bytes), header=2, dtype=str, engine=engine)
            if df is None or df.empty:
                continue
            df = _normalise_cols(df)
            if len(df) > 3:
                df = df.iloc[3:].reset_index(drop=True)
            df = df.dropna(how="all").reset_index(drop=True)
            cols_lower = [c.lower() for c in df.columns]
            if any("sku" in c for c in cols_lower) or any("product" in c for c in cols_lower):
                if len(df) > 0:
                    return df
        except Exception:
            continue

    try:
        import openpyxl
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True, read_only=True)
            ws = wb.active
            rows_data = []
            for row in ws.iter_rows(values_only=True):
                rows_data.append(list(row))
            wb.close()
        if len(rows_data) < 7:
            return pd.DataFrame()
        header = [str(v).strip() if v is not None else "" for v in rows_data[2]]
        data_rows = rows_data[6:]
        df = pd.DataFrame(data_rows, columns=header)
        df = df.astype(str).replace("None", "")
        df = _normalise_cols(df)
        df = df.dropna(how="all").reset_index(drop=True)
        cols_lower = [c.lower() for c in df.columns]
        if any("sku" in c for c in cols_lower) or any("product" in c for c in cols_lower):
            return df
    except Exception:
        pass

    return pd.DataFrame()

def _load_shopee_raw(file):
    if file is None:
        return pd.DataFrame()
    name = file.name.lower()
    raw = file.read()
    file.seek(0)
    
    if name.endswith(".zip"):
        frames = []
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                for entry in sorted(zf.namelist()):
                    if entry.lower().endswith((".xlsx", ".xls", ".csv")):
                        with zf.open(entry) as f:
                            entry_bytes = f.read()
                        df = _parse_shopee_single(entry_bytes, entry.lower())
                        if not df.empty:
                            frames.append(df)
        except Exception:
            return pd.DataFrame()
        if not frames:
            return pd.DataFrame()
        combined = pd.concat(frames, ignore_index=True)
        return _normalise_cols(combined)
    else:
        return _parse_shopee_single(raw, name)

def load_shopee_stock(file, country):
    df = _load_shopee_raw(file)
    if df.empty:
        return pd.DataFrame()

    pid_col = _find_pid_col(df)
    if pid_col and pid_col != "Product ID":
        df = df.rename(columns={pid_col: "Product ID"})

    sku_col = None
    for c in ["SKU", "Variation SKU", "VariationSKU", "Seller SKU", "SellerSKU"]:
        if c in df.columns:
            sku_col = c
            break
    if sku_col is None:
        for c in df.columns:
            cl = c.lower()
            if "sku" in cl and "parent" not in cl:
                sku_col = c
                break

    parent_col = None
    for c in ["Parent SKU", "ParentSKU", "parent_sku", "parent sku"]:
        if c in df.columns:
            parent_col = c
            break

    stock_col = None
    for c in ["Stock", "MP Stock", "Available Stock", "Current Stock", "Quantity"]:
        if c in df.columns:
            stock_col = c
            break

    price_col = None
    for c in ["Price", "MP Price", "Price List", "Unit Price"]:
        if c in df.columns:
            price_col = c
            break

    if sku_col:
        df["SKU"] = df[sku_col].apply(_clean_sku)
    else:
        df["SKU"] = ""

    if parent_col:
        mask_blank = df["SKU"] == ""
        df.loc[mask_blank, "SKU"] = df.loc[mask_blank, parent_col].apply(_clean_sku)

    df = df[df["SKU"].str.fullmatch(r"\d{13}", na=False)].copy().reset_index(drop=True)
    if df.empty:
        return pd.DataFrame()

    if stock_col and stock_col != "MP Stock":
        df = df.rename(columns={stock_col: "MP Stock"})
    if price_col and price_col != "MP Price":
        df = df.rename(columns={price_col: "MP Price"})

    df["Marketplace"] = "Shopee " + country
    if "MP Stock" in df.columns:
        df["MP Stock"] = pd.to_numeric(df["MP Stock"].apply(_safe_str), errors="coerce").fillna(0)
    else:
        df["MP Stock"] = 0
    if "MP Price" in df.columns:
        df["MP Price"] = pd.to_numeric(df["MP Price"].apply(_safe_str), errors="coerce").fillna(0.0)

    return df

def load_shopee_status(file, country):
    df = _load_shopee_raw(file)
    if df.empty:
        return pd.DataFrame()

    pid_col = _find_pid_col(df)
    if pid_col:
        if pid_col != "Product ID":
            df = df.rename(columns={pid_col: "Product ID"})
        df["Product ID"] = df["Product ID"].apply(_safe_str)
    else:
        df["Product ID"] = ""

    df["MP Status"] = df["Product ID"].apply(
        lambda x: "Active" if _safe_str(x) not in ("", "nan", "none") else "Inactive"
    )

    sku_col = None
    for c in ["SKU", "Variation SKU", "Seller SKU"]:
        if c in df.columns:
            sku_col = c
            break
    if sku_col is None:
        for c in df.columns:
            if "sku" in c.lower() and "parent" not in c.lower():
                sku_col = c
                break

    if sku_col and sku_col != "SKU":
        df = df.rename(columns={sku_col: "SKU"})

    parent_col = None
    for c in ["Parent SKU", "ParentSKU", "parent_sku", "parent sku"]:
        if c in df.columns:
            parent_col = c
            break

    if "SKU" in df.columns:
        df["SKU"] = df["SKU"].apply(_clean_sku)
        if parent_col:
            mask_blank = df["SKU"] == ""
            df.loc[mask_blank, "SKU"] = df.loc[mask_blank, parent_col].apply(_clean_sku)
        
        has_13 = df["SKU"].str.fullmatch(r'\d{13}', na=False).any()
        if has_13:
            df = df[df["SKU"].str.fullmatch(r'\d{13}', na=False)].copy()
    else:
        df["SKU"] = ""

    df["Marketplace"] = "Shopee " + country
    return df.reset_index(drop=True)

def load_zalora_stock(file, country):
    if file is None:
        return pd.DataFrame()
    df = _read_file(file)
    if df.empty:
        return pd.DataFrame()
    df = _normalise_cols(df)
    
    sku_col = None
    for c in ["SellerSku", "SellerSKU", "Seller Sku", "Seller SKU", "SKU"]:
        if c in df.columns:
            sku_col = c
            break
    if sku_col is None:
        for c in df.columns:
            if "sku" in c.lower() or "seller" in c.lower():
                sku_col = c
                break
    if sku_col is None:
        return pd.DataFrame()
    if sku_col != "SKU":
        df = df.rename(columns={sku_col: "SKU"})
        
    qty_col = None
    for c in ["Quantity", "Stock", "MP Stock", "quantity", "stock"]:
        if c in df.columns:
            qty_col = c
            break
    if qty_col and qty_col != "MP Stock":
        df = df.rename(columns={qty_col: "MP Stock"})
        
    price_col = None
    for c in ["Price", "MP Price", "price", "unit price"]:
        if c in df.columns:
            price_col = c
            break
    if price_col and price_col != "MP Price":
        df = df.rename(columns={price_col: "MP Price"})

    df["SKU"] = df["SKU"].apply(_clean_sku)
    df["Marketplace"] = "Zalora " + country
    df = df[df["SKU"] != ""].copy()
    if "MP Stock" in df.columns:
        df["MP Stock"] = pd.to_numeric(df["MP Stock"].apply(_safe_str), errors="coerce").fillna(0)
    else:
        df["MP Stock"] = 0
    if "MP Price" in df.columns:
        df["MP Price"] = pd.to_numeric(df["MP Price"].apply(_safe_str), errors="coerce").fillna(0.0)
    return df

def load_zalora_status(file, country):
    if file is None:
        return pd.DataFrame()
    df = _read_file(file)
    if df.empty:
        return pd.DataFrame()
    df = _normalise_cols(df)
    
    sku_col = None
    for c in ["SellerSku", "SellerSKU", "Seller Sku", "Seller SKU", "SKU"]:
        if c in df.columns:
            sku_col = c
            break
    if sku_col is None:
        for c in df.columns:
            if "sku" in c.lower() or "seller" in c.lower():
                sku_col = c
                break
    if sku_col is None:
        return pd.DataFrame()
    if sku_col != "SKU":
        df = df.rename(columns={sku_col: "SKU"})
        
    status_col = None
    for c in ["Status", "MP Status", "status", "mp_status"]:
        if c in df.columns:
            status_col = c
            break
    if status_col is None:
        for c in df.columns:
            if "status" in c.lower():
                status_col = c
                break
    if status_col and status_col != "MP Status":
        df = df.rename(columns={status_col: "MP Status"})
        
    if "MP Status" in df.columns:
        df["MP Status"] = df["MP Status"].apply(_safe_str).str.strip().str.capitalize()
    else:
        df["MP Status"] = "Unknown"
        
    df["SKU"] = df["SKU"].apply(_clean_sku)
    df["Marketplace"] = "Zalora " + country
    return df[df["SKU"] != ""].copy()

def _load_tiktok_raw(file):
    if file is None:
        return pd.DataFrame()
    df = _read_file(file, header_row=2)
    if df.empty:
        return pd.DataFrame()
    df = _normalise_cols(df)
    if len(df) > 2:
        df = df.iloc[2:].reset_index(drop=True)
    return df

def _load_tiktok_file(file, status_label):
    if file is None:
        return pd.DataFrame()
    df = _load_tiktok_raw(file)
    if df.empty:
        return pd.DataFrame()
        
    sku_col = None
    for c in ["Seller SKU", "SellerSKU", "SKU", "seller sku"]:
        if c in df.columns:
            sku_col = c
            break
    if sku_col is None:
        for c in df.columns:
            if "sku" in c.lower():
                sku_col = c
                break
    if sku_col is None:
        return pd.DataFrame()
        
    pid_col = None
    for c in ["Product ID", "ProductID", "product_id", "product id"]:
        if c in df.columns:
            pid_col = c
            break
            
    qty_col = None
    for c in ["Quantity", "Stock", "quantity", "stock", "Available Stock"]:
        if c in df.columns:
            qty_col = c
            break
            
    price_col = None
    for c in ["Price", "price", "Retail Price"]:
        if c in df.columns:
            price_col = c
            break

    out = pd.DataFrame()
    out["SKU"] = df[sku_col].apply(_clean_sku)
    if pid_col:
        out["Product ID"] = df[pid_col].apply(_safe_str)
    else:
        out["Product ID"] = ""
        
    out["MP Stock"] = pd.to_numeric(
        df[qty_col].apply(_safe_str) if qty_col else pd.Series([0] * len(df)),
        errors="coerce"
    ).fillna(0)
    out["MP Price"] = pd.to_numeric(
        df[price_col].apply(_safe_str) if price_col else pd.Series([0.0] * len(df)),
        errors="coerce"
    ).fillna(0.0)
    
    out["MP Status"]   = status_label
    out["Marketplace"] = "TikTok MY"
    return out[out["SKU"] != ""].copy()

def load_tiktok(active_file, inactive_file):
    active   = _load_tiktok_file(active_file,   "Active")
    inactive = _load_tiktok_file(inactive_file, "Inactive")
    if active.empty and inactive.empty:
        return pd.DataFrame()
    combined = pd.concat([active, inactive], ignore_index=True)
    combined = combined.sort_values(
        "MP Status",
        key=lambda x: x.map({"Active": 0, "Inactive": 1}),
    )
    combined = combined.drop_duplicates(subset=["SKU"], keep="first")
    return combined.reset_index(drop=True)

def load_content(file):
    if file is None:
        return pd.DataFrame()
    df = _read_file(file)
    if df.empty:
        return pd.DataFrame()
    df = _normalise_cols(df)
    
    # Map SKU / EAN
    ean_col = next((c for c in df.columns if c.lower() in ["sku as ean", "ean", "sku", "sku_ean"]), None)
    if ean_col:
        df = df.rename(columns={ean_col: "SKU"})
    elif "EAN" in df.columns and "SKU" not in df.columns:
        df = df.rename(columns={"EAN": "SKU"})
        
    # Map Article Number (exact candidates first)
    art_col = None
    for c in ["Article No", "Color_No", "Color_No.1", "ArticleNo", "Article Number"]:
        if c in df.columns:
            art_col = c
            break
    if art_col is None:
        for c in df.columns:
            if "article" in c.lower() or "color" in c.lower():
                art_col = c
                break
    if art_col and art_col != "Article No":
        df = df.rename(columns={art_col: "Article No"})
                
    # Map Color Name
    color_name_col = next((c for c in df.columns if c.lower() in ["color name", "colorname", "color_name", "colour name", "colour_name"]), None)
    if color_name_col:
        df = df.rename(columns={color_name_col: "content_color_name"})
        
    # Map Gender
    gender_col = next((c for c in df.columns if c.lower() in ["gender", "genders", "sex"]), None)
    if gender_col:
        df = df.rename(columns={gender_col: "content_gender"})
        
    # Auto-detect UK Size column
    uk_col = next((c for c in df.columns if "uk" in c.lower() and "size" in c.lower()), 
                  next((c for c in df.columns if "uk" in c.lower()), None))
    if not uk_col:
        # Fallback to general "size" column if present and not already mapped as US or Rus
        uk_col = next((c for c in df.columns if c.lower() == "size"), None)
    df["uk_size"] = df[uk_col].apply(_safe_str) if uk_col else ""
    
    # Auto-detect US Size column
    us_col = next((c for c in df.columns if "us" in c.lower() and "size" in c.lower()), 
                  next((c for c in df.columns if "us" in c.lower()), None))
    df["us_size"] = df[us_col].apply(_safe_str) if us_col else ""
    
    # Auto-detect Russian Size column
    rus_col = next((c for c in df.columns if ("rus" in c.lower() or "russian" in c.lower()) and "size" in c.lower()), 
                   next((c for c in df.columns if "rus" in c.lower() or "russian" in c.lower()), None))
    df["rus_size"] = df[rus_col].apply(_safe_str) if rus_col else ""

    if "SKU" in df.columns:
        df["SKU"] = df["SKU"].apply(_clean_sku)
    if "Article No" in df.columns:
        df["Article No"] = df["Article No"].apply(_safe_str)
        
    return df

# ── zEcom Loader (extracts launch dates, ecom statuses, and RRP Price)
def load_zecom(file, country="PH"):
    if file is None:
        return pd.DataFrame()
    raw = file.read()
    name = file.name.lower()
    file.seek(0)

    article_col_by_country = {
        "PH": ["PIM Article#", "PIM Article #", "Article No", "ArticleNo"],
        "MY": ["Style#", "STYLE#", "style#", "Article No", "PIM Article#"],
        "SG": ["STYLE#", "Style#", "style#", "Article No", "PIM Article#"],
    }
    preferred_article_cols = article_col_by_country.get(country, ["Article No"])
    preferred_rows = [2, 1, 0, 3] if country == "PH" else [3, 2, 1, 0]

    try:
        if name.endswith(".csv"):
            raw_df = pd.read_csv(io.BytesIO(raw), header=None, dtype=str)
        else:
            try:
                import python_calamine
                xl = pd.ExcelFile(io.BytesIO(raw), engine="calamine")
            except ImportError:
                xl = pd.ExcelFile(io.BytesIO(raw))
            
            sheet_names = xl.sheet_names
            target_sheet = sheet_names[0]
            
            country_lower = country.lower().strip()
            country_keywords = {
                "my": ["my", "malaysia"],
                "sg": ["sg", "singapore"],
                "ph": ["ph", "phil", "philippines"]
            }
            keywords = country_keywords.get(country_lower, [country_lower])
            
            # 1. Try exact match first (case-insensitive)
            matched_sheet = None
            for s_name in sheet_names:
                s_name_lower = s_name.lower().strip()
                if s_name_lower in keywords:
                    matched_sheet = s_name
                    break
            
            # 2. Try word boundary match (e.g. "SG tracker" or "Lazada SG")
            if not matched_sheet:
                for s_name in sheet_names:
                    s_name_lower = s_name.lower().strip()
                    cleaned_s_name = re.sub(r'[^a-z0-9]', ' ', s_name_lower)
                    for kw in keywords:
                        if re.search(r'\b' + re.escape(kw) + r'\b', cleaned_s_name):
                            matched_sheet = s_name
                            break
                    if matched_sheet:
                        break
            
            # 3. Try substring match as fallback
            if not matched_sheet:
                for s_name in sheet_names:
                    s_name_lower = s_name.lower().strip()
                    if any(kw in s_name_lower for kw in keywords):
                        matched_sheet = s_name
                        break
            
            if matched_sheet:
                target_sheet = matched_sheet
                
            raw_df = xl.parse(target_sheet, header=None, dtype=str)
    except Exception:
        return pd.DataFrame()

    if raw_df.empty:
        return pd.DataFrame()

    # Set metadata attributes for logging
    if not hasattr(raw_df, "attrs"):
        raw_df.attrs = {}
    raw_df.attrs["selected_sheet"] = target_sheet
    raw_df.attrs["sheet_names"] = sheet_names if 'sheet_names' in locals() else [name]
    raw_df.attrs["passed_country"] = country

    header_idx = None
    for r_idx in preferred_rows:
        if r_idx < len(raw_df):
            row_vals = [_safe_str(x) for x in raw_df.iloc[r_idx]]
            row_lower = [v.lower() for v in row_vals]
            expected  = [c.lower() for c in preferred_article_cols]
            if any(e in row_lower for e in expected) or any("article" in c or "pim" in c or "style" in c for c in row_lower):
                header_idx = r_idx
                break

    if header_idx is None:
        for r_idx in range(min(6, len(raw_df))):
            row_vals = [_safe_str(x) for x in raw_df.iloc[r_idx]]
            row_lower = [v.lower() for v in row_vals]
            expected  = [c.lower() for c in preferred_article_cols]
            if any(e in row_lower for e in expected) or any("article" in c or "pim" in c or "style" in c for c in row_lower):
                header_idx = r_idx
                break

    if header_idx is None:
        header_idx = preferred_rows[0] if preferred_rows[0] < len(raw_df) else 0

    df = raw_df.iloc[header_idx + 1:].copy()
    df.columns = [_safe_str(x) for x in raw_df.iloc[header_idx]]
    df = df.loc[:, ~df.columns.duplicated()].copy()
    df = df.reset_index(drop=True)
    
    first_col = df.columns[0]
    df = df[df[first_col].apply(_safe_str) != first_col].copy()
    df = df.reset_index(drop=True)

    article_col = None
    for c in preferred_article_cols:
        if c in df.columns:
            article_col = c
            break
    if article_col is None:
        for c in df.columns:
            if "style" in c.lower() or "article" in c.lower() or "pim" in c.lower():
                article_col = c
                break
    if article_col and article_col != "Article No":
        df = df.rename(columns={article_col: "Article No"})

    if "Article No" in df.columns:
        df = df[df["Article No"].apply(_safe_str) != ""].copy()
        df = df.reset_index(drop=True)

    # Auto-detect RRP Price column
    rrp_col = next((c for c in df.columns if "rrp" in c.lower() or ("retail" in c.lower() and "price" in c.lower())), None)
    if rrp_col:
        df["rrp_price"] = df[rrp_col].apply(_safe_str)
    else:
        df["rrp_price"] = ""

    launch_col = None
    for c in ["Launch Dates", "Launch Date", "LaunchDate", "Launch"]:
        if c in df.columns:
            launch_col = c
            break
    if launch_col is None:
        for c in df.columns:
            if "launch" in c.lower():
                launch_col = c
                break
    if launch_col and launch_col != "Launch Date":
        df = df.rename(columns={launch_col: "Launch Date"})

    today = pd.Timestamp.today().normalize()
    if "Launch Date" in df.columns:
        df["Launch Date"] = pd.to_datetime(df["Launch Date"], errors="coerce")
        df["Future Launch"] = df["Launch Date"].apply(
            lambda d: True if pd.notna(d) and d > today else False
        )
    else:
        df["Future Launch"] = False

    mp_keywords = {
        "lazada":  "Ecom_Lazada",
        "shopee":  "Ecom_Shopee",
        "zalora":  "Ecom_Zalora",
        "tiktok":  "Ecom_TikTok",
    }
    def _clean_string(s):
        if not s:
            return ""
        return re.sub(r'[^a-z0-9]', '', str(s).lower())

    for mp_key, ecom_name in mp_keywords.items():
        target_col = None
        mp_key_clean = _clean_string(mp_key)
        country_clean = _clean_string(country)
        
        # First try: platform name + country name
        for col in df.columns:
            if col in ("Article No", "Launch Date", "Future Launch", "rrp_price"):
                continue
            col_clean = _clean_string(col)
            if mp_key_clean in col_clean and country_clean in col_clean:
                target_col = col
                break
        # Second try: platform name only
        if not target_col:
            for col in df.columns:
                if col in ("Article No", "Launch Date", "Future Launch", "rrp_price"):
                    continue
                col_clean = _clean_string(col)
                if mp_key_clean in col_clean:
                    target_col = col
                    break
        if target_col:
            df[ecom_name] = df.apply(
                lambda row, c=target_col: _ecom_status_from_val(
                    row[c], row["Future Launch"]
                ),
                axis=1,
            )
            
    return df

# ── Auto column mapping functions ─────────────────────────────────────────────

def auto_map_columns(columns: list) -> dict:
    mapping = {}
    normalized_cols = {col.strip().lower(): col for col in columns}
    
    for canonical, synonyms in COLUMN_SYNONYMS.items():
        found = False
        for syn in synonyms:
            if syn in normalized_cols:
                mapping[canonical] = normalized_cols[syn]
                found = True
                break
        
        if not found:
            for col_raw in columns:
                col_lower = col_raw.strip().lower()
                for syn in synonyms:
                    if syn in col_lower or col_lower in syn:
                        mapping[canonical] = col_raw
                        found = True
                        break
                if found:
                    break
                    
        if not found:
            mapping[canonical] = None
            
    return mapping

def _clean_target_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
        
    def is_helper_value(val):
        s = _safe_str(val).strip().lower()
        if s in ["mandatory", "optional", "n/a"]:
            return True
        if s.startswith(("select the", "select a", "product name must be", "provide a detailed", "add the url", "add the urls", "please select")):
            return True
        return False

    rows_to_drop = []
    for idx in range(min(5, len(df))):
        row = df.iloc[idx]
        for col in ["product_name", "category", "brand", "price", "quantity"]:
            if col in df.columns and is_helper_value(row[col]):
                rows_to_drop.append(df.index[idx])
                break
                
    if len(rows_to_drop) >= 2:
        next_idx = len(rows_to_drop)
        if next_idx < len(df):
            rows_to_drop.append(df.index[next_idx])
            
    if rows_to_drop:
        df = df.drop(index=rows_to_drop).reset_index(drop=True)
        
    return df

def standardize_dataframe(df: pd.DataFrame, mapping: dict, source_name: str = "Uploaded File") -> pd.DataFrame:
    standard_df = pd.DataFrame()
    if "_excel_row" in df.columns:
        standard_df["_original_row_number"] = df["_excel_row"]
    else:
        standard_df["_original_row_number"] = df.index + 2
        
    standard_df["_source_file"] = [source_name] * len(df)
    
    for canonical, file_col in mapping.items():
        if file_col and file_col in df.columns:
            col_data = df[file_col]
            if isinstance(col_data, pd.DataFrame):
                col_data = col_data.iloc[:, 0]
            standard_df[canonical] = col_data
        else:
            standard_df[canonical] = pd.NA
            
    # Clean helper/example rows
    standard_df = _clean_target_df(standard_df)
    return standard_df

from typing import Tuple

def parse_variation_combo(val: str) -> Tuple[str, str]:
    """
    Splits a variation string by comma and returns (color, size).
    If only one part, checks if it is size-like to return (color, size) correctly.
    """
    if not val or pd.isna(val):
        return "", ""
    parts = [p.strip() for p in str(val).split(",") if p.strip()]
    if len(parts) == 0:
        return "", ""
        
    # We have 1 or more parts. Let's find which part is size-like.
    def is_size_like(p):
        p_clean = p.lower()
        if any(p_clean.startswith(prefix) for prefix in ["uk:", "us:", "int:", "eu:", "uk ", "us ", "int ", "eu "]):
            return True
        if re.fullmatch(r'(?:int:|uk:|us:|eu:)?\s*(?:[xsml]|xxl|xxxl|xxxxl|\d+(?:\.\d+)?)', p_clean):
            return True
        if re.search(r'\b\d+(?:/\d+)?\b', p_clean):
            return True
        if re.search(r'\bw\s*\d+\s*l\s*\d+\b', p_clean):
            return True
        return False
        
    if len(parts) == 1:
        if is_size_like(parts[0]):
            return "", parts[0]
        else:
            return parts[0], ""
            
    part1_size = is_size_like(parts[0])
    part2_size = is_size_like(parts[1])
    
    if part1_size and not part2_size:
        return parts[1], parts[0]
    elif part2_size and not part1_size:
        return parts[0], parts[1]
    else:
        return parts[0], parts[1]

def _clean_live_df_skipping(df: pd.DataFrame, sku_col: str, platform: str) -> pd.DataFrame:
    if df.empty:
        return df
    if sku_col not in df.columns:
        return df
    first_val = _safe_str(df.iloc[0][sku_col])
    if not first_val or any(k in first_val.lower() for k in ["mandatory", "example", "instruction", "select"]):
        if len(df) > 3:
            return df.iloc[3:].reset_index(drop=True)
    return df

def parse_live_lazada(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df_data = _normalise_cols(df.copy())
    
    sku_col = next((c for c in df_data.columns if c.lower() in ["sellersku", "sku", "seller sku"]), None)
    if sku_col:
        df_data = _clean_live_df_skipping(df_data, sku_col, "lazada")
        
    name_col = next((c for c in df_data.columns if c.lower() in ["name", "product name", "product_name"]), None)
    qty_col = next((c for c in df_data.columns if c.lower() in ["quantity", "stock", "qty", "mp stock"]), None)
    price_col = next((c for c in df_data.columns if c.lower() in ["price", "selling price", "mp price"]), None)
    
    var_col = next((c for c in df_data.columns if c.lower() in ["variation", "variations", "variation combo", "variation_combo"]), None)
    color_col = next((c for c in df_data.columns if c.lower() in ["color", "colour", "color name", "color_name"]), None)
    size_col = next((c for c in df_data.columns if c.lower() in ["size", "size_name", "size name"]), None)
    
    img_cols = [c for c in df_data.columns if "image" in c.lower() and not "chart" in c.lower()]
    sc_col = next((c for c in df_data.columns if "size" in c.lower() and "chart" in c.lower()), None)
    
    records = []
    for _, row in df_data.iterrows():
        sku_val = _clean_sku(row.get(sku_col)) if sku_col else ""
        if not sku_val:
            continue
            
        name_val = _safe_str(row.get(name_col)) if name_col else ""
        qty_val = _safe_str(row.get(qty_col)) if qty_col else "0"
        price_val = _safe_str(row.get(price_col)) if price_col else "0.0"
        
        # Variation parsing (combo or separate)
        if var_col and not is_empty(row.get(var_col)):
            var_val = _safe_str(row.get(var_col))
            color_val, size_val = parse_variation_combo(var_val)
        else:
            color_val = _safe_str(row.get(color_col)) if color_col else ""
            size_val = _safe_str(row.get(size_col)) if size_col else ""
            
        imgs = [str(row[c]).strip() for c in img_cols if pd.notna(row.get(c)) and str(row[c]).strip() not in ("", "nan", "None")]
        imgs_str = ",".join(imgs)
        sc_val = _safe_str(row.get(sc_col)) if sc_col else ""
        
        records.append({
            "sku": sku_val,
            "product_name": name_val,
            "color_name": color_val,
            "size": size_val,
            "price": price_val,
            "quantity": qty_val,
            "images": imgs_str,
            "size_chart": sc_val,
            "ecommerce_status": "Active"
        })
    return pd.DataFrame(records)

def parse_live_shopee(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df_data = _normalise_cols(df.copy())
    
    sku_col = next((c for c in df_data.columns if c.lower() in ["sku", "variation sku", "seller sku"]), None)
    if sku_col:
        df_data = _clean_live_df_skipping(df_data, sku_col, "shopee")
        
    parent_col = next((c for c in df_data.columns if c.lower() in ["parent sku", "parentsku", "parent_sku"]), None)
    name_col = next((c for c in df_data.columns if c.lower() in ["product name", "name", "product_name"]), None)
    price_col = next((c for c in df_data.columns if c.lower() in ["price", "selling price", "mp price"]), None)
    stock_col = next((c for c in df_data.columns if c.lower() in ["stock", "quantity", "qty", "mp stock"]), None)
    
    var_col = next((c for c in df_data.columns if c.lower() in ["variation name", "variation", "variation_name"]), None)
    color_col = next((c for c in df_data.columns if c.lower() in ["color", "colour", "color name", "color_name"]), None)
    size_col = next((c for c in df_data.columns if c.lower() in ["size", "size_name", "size name"]), None)
    
    img_cols = [c for c in df_data.columns if any(k in c.lower() for k in ["cover image", "item image"]) and not "chart" in c.lower()]
    sc_col = next((c for c in df_data.columns if "size chart" in c.lower()), None)
    
    records = []
    for _, row in df_data.iterrows():
        sku_val = _clean_sku(row.get(sku_col)) if sku_col else ""
        parent_val = _clean_sku(row.get(parent_col)) if parent_col else ""
        if not sku_val and parent_val:
            sku_val = parent_val
            
        if not sku_val:
            continue
            
        name_val = _safe_str(row.get(name_col)) if name_col else ""
        price_val = _safe_str(row.get(price_col)) if price_col else "0.0"
        stock_val = _safe_str(row.get(stock_col)) if stock_col else "0"
        
        # Variation parsing (combo or separate)
        if var_col and not is_empty(row.get(var_col)):
            var_val = _safe_str(row.get(var_col))
            color_val, size_val = parse_variation_combo(var_val)
        else:
            color_val = _safe_str(row.get(color_col)) if color_col else ""
            size_val = _safe_str(row.get(size_col)) if size_col else ""
            
        imgs = [str(row[c]).strip() for c in img_cols if pd.notna(row.get(c)) and str(row[c]).strip() not in ("", "nan", "None")]
        imgs_str = ",".join(imgs)
        sc_val = _safe_str(row.get(sc_col)) if sc_col else ""
        
        records.append({
            "sku": sku_val,
            "product_name": name_val,
            "color_name": color_val,
            "size": size_val,
            "price": price_val,
            "quantity": stock_val,
            "images": imgs_str,
            "size_chart": sc_val,
            "ecommerce_status": "Active"
        })
    return pd.DataFrame(records)

def parse_live_tiktok(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df_data = _normalise_cols(df.copy())
    
    sku_col = next((c for c in df_data.columns if c.lower() in ["seller sku", "sku", "sellersku"]), None)
    if sku_col:
        df_data = _clean_live_df_skipping(df_data, sku_col, "tiktok")
        
    name_col = next((c for c in df_data.columns if c.lower() in ["product name", "name", "product_name"]), None)
    price_col = next((c for c in df_data.columns if "retail price" in c.lower() or c.lower() == "price"), None)
    qty_col = next((c for c in df_data.columns if c.lower() in ["quantity", "stock", "qty"]), None)
    
    var_col = next((c for c in df_data.columns if c.lower() in ["variation option", "variation", "variation_option"]), None)
    color_col = next((c for c in df_data.columns if c.lower() in ["primary variation value (option)", "color", "colour"]), None)
    size_col = next((c for c in df_data.columns if c.lower() in ["secondary variation value (option)", "size"]), None)
    
    img_cols = [c for c in df_data.columns if any(k in c.lower() for k in ["main image", "image"]) and not "chart" in c.lower()]
    sc_col = next((c for c in df_data.columns if "size chart" in c.lower()), None)
    
    records = []
    for _, row in df_data.iterrows():
        sku_val = _clean_sku(row.get(sku_col)) if sku_col else ""
        if not sku_val:
            continue
            
        name_val = _safe_str(row.get(name_col)) if name_col else ""
        price_val = _safe_str(row.get(price_col)) if price_col else "0.0"
        qty_val = _safe_str(row.get(qty_col)) if qty_col else "0"
        
        # Variation parsing (combo or separate)
        if var_col and not is_empty(row.get(var_col)):
            var_val = _safe_str(row.get(var_col))
            color_val, size_val = parse_variation_combo(var_val)
        else:
            color_val = _safe_str(row.get(color_col)) if color_col else ""
            size_val = _safe_str(row.get(size_col)) if size_col else ""
            
        imgs = [str(row[c]).strip() for c in img_cols if pd.notna(row.get(c)) and str(row[c]).strip() not in ("", "nan", "None")]
        imgs_str = ",".join(imgs)
        sc_val = _safe_str(row.get(sc_col)) if sc_col else ""
        
        records.append({
            "sku": sku_val,
            "product_name": name_val,
            "color_name": color_val,
            "size": size_val,
            "price": price_val,
            "quantity": qty_val,
            "images": imgs_str,
            "size_chart": sc_val,
            "ecommerce_status": "Active"
        })
    return pd.DataFrame(records)


def process_live_files(uploaded_files, channel: str) -> pd.DataFrame:
    import zipfile
    platform = channel.split()[0].lower()
    
    all_dfs = []
    for file in uploaded_files:
        name = file.name.lower()
        if name.endswith(".zip"):
            raw = file.read()
            file.seek(0)
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                for entry in sorted(zf.namelist()):
                    if entry.lower().endswith((".xlsx", ".xls", ".csv")):
                        with zf.open(entry) as f:
                            data = f.read()
                            if entry.lower().endswith(".csv"):
                                h_row = 2 if platform in ["tiktok", "shopee"] else 0
                                df = pd.read_csv(io.BytesIO(data), header=h_row, dtype=str)
                            else:
                                h_row = 2 if platform in ["tiktok", "shopee"] else 0
                                try:
                                    import python_calamine
                                    df = pd.read_excel(io.BytesIO(data), header=h_row, dtype=str, engine="calamine")
                                except ImportError:
                                    df = pd.read_excel(io.BytesIO(data), header=h_row, dtype=str)
                            if not df.empty:
                                all_dfs.append(df)
        else:
            raw = file.read()
            file.seek(0)
            h_row = 2 if platform in ["tiktok", "shopee"] else 0
            try:
                if name.endswith(".csv"):
                    df = pd.read_csv(io.BytesIO(raw), header=h_row, dtype=str)
                else:
                    try:
                        import python_calamine
                        df = pd.read_excel(io.BytesIO(raw), header=h_row, dtype=str, engine="calamine")
                    except ImportError:
                        df = pd.read_excel(io.BytesIO(raw), header=h_row, dtype=str)
                if not df.empty:
                    all_dfs.append(df)
            except Exception:
                continue
                
    if not all_dfs:
        return pd.DataFrame()
        
    platform_parsed_dfs = []
    for df in all_dfs:
        if platform == "lazada":
            parsed = parse_live_lazada(df)
        elif platform == "shopee":
            parsed = parse_live_shopee(df)
        elif platform == "tiktok":
            parsed = parse_live_tiktok(df)
        else:
            parsed = df
        if not parsed.empty:
            platform_parsed_dfs.append(parsed)
            
    if not platform_parsed_dfs:
        return pd.DataFrame()
        
    combined = pd.concat(platform_parsed_dfs, ignore_index=True)
    
    # Merge rows by SKU by selecting first non-empty value for each column
    def merge_rows(group):
        merged = {}
        for col in group.columns:
            non_empty = group[col].dropna().astype(str).str.strip()
            non_empty = non_empty[~non_empty.isin(["", "nan", "None"])]
            if len(non_empty) > 0:
                merged[col] = non_empty.iloc[0]
            else:
                merged[col] = ""
        return pd.Series(merged)
        
    consolidated = combined.groupby("sku", as_index=False).apply(merge_rows)
    return consolidated

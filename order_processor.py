# VERSION: v1 - Order Processor & SLA Validator
import pandas as pd
import numpy as np
import io
import re
import urllib.request
import urllib.error

def get_google_sheet_download_url(url):
    pattern = r"/spreadsheets/d/([a-zA-Z0-9-_]+)"
    match = re.search(pattern, url)
    if match:
        spreadsheet_id = match.group(1)
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=xlsx"
    return None

def download_google_sheet(url):
    download_url = get_google_sheet_download_url(url)
    if not download_url:
        download_url = url
    try:
        req = urllib.request.Request(
            download_url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req) as response:
            data = response.read()
        return io.BytesIO(data)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ValueError(
                "Failed to download Google Sheet: Access Denied (HTTP 401/403 Unauthorized). "
                "Please ensure that the sharing settings of your Google Sheet are set to "
                "'Anyone with the link can view' or 'Anyone with the link can edit' (restricted sheets require auth, which is not supported)."
            )
        raise ValueError(f"Failed to download Google Sheet: HTTP Error {e.code} - {e.reason}")
    except Exception as e:
        raise ValueError(f"Failed to download Google Sheet from URL: {str(e)}")

def _clean_str(val):
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    return str(val).strip()

def _clean_order_id(val):
    # Strip any decimal part like .0 from order IDs
    s = _clean_str(val)
    if s.endswith(".0"):
        s = s[:-2]
    return s

def _find_column(df, candidates):
    """Find a column in df that matches any of the candidate names case-insensitively and ignoring underscores/spaces."""
    cols = list(df.columns)
    for cand in candidates:
        cand_norm = cand.lower().replace(" ", "").replace("_", "").replace("-", "")
        for col in cols:
            col_norm = str(col).lower().replace(" ", "").replace("_", "").replace("-", "")
            if col_norm == cand_norm:
                return col
    return None

def load_file_safely(file):
    """Load uploaded file object (CSV or Excel) into a DataFrame. Scans sheets if Excel."""
    if file is None:
        return pd.DataFrame()
    
    try:
        file.seek(0)
    except Exception:
        pass
        
    name = file.name.lower()
    
    try:
        if name.endswith(".csv"):
            try:
                file.seek(0)
                df = pd.read_csv(file, dtype=str)
                if not df.empty:
                    return df.dropna(how="all").reset_index(drop=True)
            except Exception:
                pass
            
            # Fallback to reading bytes
            file.seek(0)
            raw = file.read()
            df = pd.read_csv(io.BytesIO(raw), dtype=str)
            return df.dropna(how="all").reset_index(drop=True)
        else:
            # Excel - Scan all sheets to find the first non-empty one
            try:
                file.seek(0)
                xl = pd.ExcelFile(file)
            except Exception:
                file.seek(0)
                raw = file.read()
                xl = pd.ExcelFile(io.BytesIO(raw))
                
            for sheet in xl.sheet_names:
                try:
                    df = xl.parse(sheet, dtype=str)
                    if df is not None and not df.empty:
                        df_clean = df.dropna(how="all").reset_index(drop=True)
                        if not df_clean.empty:
                            return df_clean
                except Exception:
                    continue
            
            # Fallback: if all sheets are empty, return the first sheet
            if xl.sheet_names:
                return xl.parse(xl.sheet_names[0], dtype=str)
            return pd.DataFrame()
    except Exception as e:
        raise ValueError(f"Failed to read file {file.name}: {str(e)}")

def process_and_validate_orders(pending_file, tc_file, oms_file, contacts_file=None, marketplace_files=None):
    """
    Process Pending Order Report, TC Report, and OMS Report.
    Returns:
      dict: {
         "enriched_pending_df": DataFrame,
         "discrepancies_df": DataFrame,
         "summary": dict,
         "seller_groups": dict { seller_name: DataFrame }
      }
    """
    # ── 1. Load DataFrames ────────────────────────────────────────────────────
    if pending_file:
        if isinstance(pending_file, str) and (pending_file.startswith("http://") or pending_file.startswith("https://")):
            pending_file = download_google_sheet(pending_file)
        df_pending = load_file_safely(pending_file)
    else:
        df_pending = pd.DataFrame()
    df_tc = load_file_safely(tc_file)
    df_oms = load_file_safely(oms_file)
    df_contacts = load_file_safely(contacts_file) if contacts_file is not None else pd.DataFrame()

    if df_pending.empty:
        raise ValueError("Pending Order Report is empty or could not be loaded.")
    if df_tc.empty:
        raise ValueError("TC Report is empty or could not be loaded.")
    if df_oms.empty:
        raise ValueError("OMS Report is empty or could not be loaded.")

    # ── 2. Standardize Columns ───────────────────────────────────────────────
    # Pending Order columns
    pend_id_col = _find_column(df_pending, ["Order ID", "Order No", "Order Number", "Order_No", "Order_ID"])
    pend_sla_col = _find_column(df_pending, ["SLA", "SLA Date", "SLA_Date", "Ship By Date", "ship_by_date"])
    pend_store_col = _find_column(df_pending, ["Store Name", "Store", "Seller", "Seller Name", "Marketplace", "Shop Name", "Shop"])
    
    # TC Report columns
    tc_id_col = _find_column(df_tc, ["Order ID", "Order No", "Order Number", "Order_No", "Order_ID"])
    tc_status_col = _find_column(df_tc, ["TC Status", "Order Status", "Status", "TC_Status"])
    tc_sla_col = _find_column(df_tc, ["SLA", "SLA Date", "SLA_Date", "Ship By Date", "ship_by_date"])
    
    # OMS Report columns
    oms_id_col = _find_column(df_oms, ["Order ID", "Order No", "Order Number", "Order_No", "Order_ID"])
    oms_status_col = _find_column(df_oms, ["OMS Status", "Order Status", "Status", "OMS_Status"])
    oms_pay_status_col = _find_column(df_oms, ["Payment Status", "Payment_Status", "PaymentStatus", "Payment"])
    oms_pay_method_col = _find_column(df_oms, ["Payment Method", "Payment_Method", "PaymentMethod", "Payment Type"])

    # Raise error if critical columns are missing
    if not pend_id_col:
        raise KeyError(f"Could not find 'Order ID' column in Pending Order Report. Available: {list(df_pending.columns)}")
    if not tc_id_col:
        raise KeyError(f"Could not find 'Order ID' column in TC Report. Available: {list(df_tc.columns)}")
    if not oms_id_col:
        raise KeyError(f"Could not find 'Order ID' column in OMS Report. Available: {list(df_oms.columns)}")

    # Clean Order IDs to ensure matches
    df_pending[pend_id_col] = df_pending[pend_id_col].apply(_clean_order_id)
    df_tc[tc_id_col] = df_tc[tc_id_col].apply(_clean_order_id)
    df_oms[oms_id_col] = df_oms[oms_id_col].apply(_clean_order_id)

    # ── 3. SLA Enrichment ────────────────────────────────────────────────────
    # Build TC SLA lookup map
    tc_sla_map = {}
    if tc_sla_col:
        tc_sla_map = df_tc.set_index(tc_id_col)[tc_sla_col].dropna().to_dict()

    enriched_rows = []
    enriched_sla_count = 0
    blank_sla_not_found = 0

    # Ensure SLA column exists in pending
    target_sla_col = pend_sla_col if pend_sla_col else "SLA"
    if target_sla_col not in df_pending.columns:
        df_pending[target_sla_col] = ""

    # Ensure Store Name exists in pending
    target_store_col = pend_store_col if pend_store_col else "Store Name"
    if target_store_col not in df_pending.columns:
        df_pending[target_store_col] = "Default Store"

    df_pending["SLA Source"] = "Pending Report"

    for idx, row in df_pending.iterrows():
        order_id = row[pend_id_col]
        sla_val = _clean_str(row[target_sla_col])
        
        if not sla_val: # Blank SLA
            tc_sla_val = _clean_str(tc_sla_map.get(order_id, ""))
            if tc_sla_val:
                df_pending.at[idx, target_sla_col] = tc_sla_val
                df_pending.at[idx, "SLA Source"] = "Enriched from TC"
                enriched_sla_count += 1
            else:
                df_pending.at[idx, "SLA Source"] = "Missing (Not in TC)"
                blank_sla_not_found += 1

    # ── 4. OMS vs TC Validations ─────────────────────────────────────────────
    # Create indexed lookups for validations
    tc_lookup = {}
    for _, row in df_tc.iterrows():
        oid = row[tc_id_col]
        tc_lookup[oid] = {
            "Status": _clean_str(row[tc_status_col]) if tc_status_col else "",
            "Row": row.to_dict()
        }

    oms_lookup = {}
    for _, row in df_oms.iterrows():
        oid = row[oms_id_col]
        oms_lookup[oid] = {
            "Status": _clean_str(row[oms_status_col]) if oms_status_col else "",
            "Payment Status": _clean_str(row[oms_pay_status_col]) if oms_pay_status_col else "",
            "Payment Method": _clean_str(row[oms_pay_method_col]) if oms_pay_method_col else "",
            "Row": row.to_dict()
        }

    # All unique order IDs across TC and OMS
    all_order_ids = set(tc_lookup.keys()) | set(oms_lookup.keys())
    discrepancies = []

    for oid in all_order_ids:
        in_tc = oid in tc_lookup
        in_oms = oid in oms_lookup
        
        tc_status = tc_lookup[oid]["Status"] if in_tc else ""
        oms_status = oms_lookup[oid]["Status"] if in_oms else ""
        oms_pay_status = oms_lookup[oid]["Payment Status"] if in_oms else ""
        oms_pay_method = oms_lookup[oid]["Payment Method"] if in_oms else ""

        # Check Payment method: is it COD?
        is_cod = any(term in oms_pay_method.lower() for term in ["cod", "cash on delivery", "cashondelivery"]) if in_oms else False
        is_pay_pending = False

        # Let's also look for payment status and payment method in TC if not in OMS
        tc_pay_status_col = _find_column(df_tc, ["Payment Status", "Payment_Status", "PaymentStatus", "Payment"])
        tc_pay_method_col = _find_column(df_tc, ["Payment Method", "Payment_Method", "PaymentMethod", "Payment Type"])
        
        if in_tc:
            tc_pay_status = _clean_str(tc_lookup[oid]["Row"].get(tc_pay_status_col, "")) if tc_pay_status_col else ""
            tc_pay_method = _clean_str(tc_lookup[oid]["Row"].get(tc_pay_method_col, "")) if tc_pay_method_col else ""
            
            # If we don't have it from OMS, use TC's values
            if not oms_pay_status:
                oms_pay_status = tc_pay_status
            if not oms_pay_method:
                oms_pay_method = tc_pay_method
                is_cod = any(term in oms_pay_method.lower() for term in ["cod", "cash on delivery", "cashondelivery"])

        # ── Rule 3: Payment Pending check ──────────────────────────────
        if in_tc and tc_status.lower() == "new" and oms_pay_status.lower() == "pending" and not is_cod:
            is_pay_pending = True
            
            if not in_oms:
                discrepancies.append({
                    "Order ID": oid,
                    "Validation Result": "Payment Pending (Hold)",
                    "TC Status": tc_status,
                    "OMS Status": "Not in OMS",
                    "Payment Status": oms_pay_status,
                    "Payment Method": oms_pay_method if oms_pay_method else "Non-COD",
                    "Details": "Expected hold: TC status is New, Payment Status is Pending, and Payment Method is not COD."
                })
                continue
            else:
                discrepancies.append({
                    "Order ID": oid,
                    "Validation Result": "Payment Pending Push Discrepancy",
                    "TC Status": tc_status,
                    "OMS Status": oms_status,
                    "Payment Status": oms_pay_status,
                    "Payment Method": oms_pay_method,
                    "Details": "Order pushed to OMS despite TC being New, Payment Status Pending, and Method not COD."
                })

        # ── Pushed Status Validation (Missing order check) ──────────────
        if in_tc and not in_oms and not is_pay_pending:
            discrepancies.append({
                "Order ID": oid,
                "Validation Result": "Missing in OMS",
                "TC Status": tc_status,
                "OMS Status": "Missing",
                "Payment Status": oms_pay_status,
                "Payment Method": oms_pay_method,
                "Details": "Order exists in TC but was not successfully pushed to OMS."
            })
            continue

        if in_oms and not in_tc:
            discrepancies.append({
                "Order ID": oid,
                "Validation Result": "Missing in TC",
                "TC Status": "Missing",
                "OMS Status": oms_status,
                "Payment Status": oms_pay_status,
                "Payment Method": oms_pay_method,
                "Details": "Order exists in OMS but does not exist in TC."
            })
            continue

        # ── Rule 1: Cancelled status check ──────────────────────────────
        is_tc_cancelled = (tc_status.lower() == "cancelled")
        is_oms_cancelled = (oms_status.lower() == "cancelled")
        
        if is_tc_cancelled != is_oms_cancelled:
            discrepancies.append({
                "Order ID": oid,
                "Validation Result": "Cancelled Sync Mismatch",
                "TC Status": tc_status,
                "OMS Status": oms_status,
                "Payment Status": oms_pay_status,
                "Payment Method": oms_pay_method,
                "Details": f"Cancellation mismatch: TC is {tc_status}, OMS is {oms_status}."
            })

        # ── Rule 2: Packed status check ─────────────────────────────────
        if oms_status.lower() == "packed" and tc_status.lower() == "new":
            discrepancies.append({
                "Order ID": oid,
                "Validation Result": "OMS Packed but TC New",
                "TC Status": tc_status,
                "OMS Status": oms_status,
                "Payment Status": oms_pay_status,
                "Payment Method": oms_pay_method,
                "Details": "Discrepancy: OMS status is Packed, but TC status is New (must be Accepted, Picked, or Ready to Ship)."
            })

    df_discrepancies = pd.DataFrame(discrepancies) if discrepancies else pd.DataFrame(columns=[
        "Order ID", "Validation Result", "TC Status", "OMS Status", "Payment Status", "Payment Method", "Details"
    ])

    # ── 5. Seller Contact Map & Grouping ─────────────────────────────────────
    email_map = {}
    if not df_contacts.empty:
        c_store = _find_column(df_contacts, ["Store Name", "Store", "Seller", "Shop Name", "Shop"])
        c_email = _find_column(df_contacts, ["Seller Email", "Email", "SellerEmail", "Email Address"])
        if c_store and c_email:
            for _, row in df_contacts.iterrows():
                store_key = _clean_str(row[c_store]).lower()
                email_val = _clean_str(row[c_email])
                if store_key and email_val:
                    email_map[store_key] = email_val

    # Group enriched pending orders by Seller
    seller_groups = {}
    stores = df_pending[target_store_col].unique()

    for store in stores:
        store_clean = _clean_str(store)
        store_key = store_clean.lower()
        
        store_df = df_pending[df_pending[target_store_col] == store].copy()
        
        mapped_email = email_map.get(store_key, "")
        store_df["Seller Email"] = mapped_email
        
        seller_groups[store_clean] = {
            "df": store_df,
            "email": mapped_email
        }

    # Summary metrics
    summary = {
        "total_pending_orders": len(df_pending),
        "enriched_sla_count": enriched_sla_count,
        "blank_sla_not_found": blank_sla_not_found,
        "total_discrepancies": len(df_discrepancies),
        "cancelled_mismatches": int((df_discrepancies["Validation Result"] == "Cancelled Sync Mismatch").sum()),
        "packed_mismatches": int((df_discrepancies["Validation Result"] == "OMS Packed but TC New").sum()),
        "payment_pending_holds": int((df_discrepancies["Validation Result"] == "Payment Pending (Hold)").sum()),
        "missing_in_oms": int((df_discrepancies["Validation Result"] == "Missing in OMS").sum()),
        "total_sellers": len(seller_groups)
    }

    # ── 6. Marketplace order validation (Channel-wise vs TC) ──────────────────
    missing_mp_orders = []
    mp_summaries = []
    
    # Get set of all cleaned TC order IDs
    tc_order_ids = set()
    if not df_tc.empty and tc_id_col:
        tc_order_ids = set(df_tc[tc_id_col].dropna().apply(_clean_order_id))
        
    if marketplace_files:
        for channel_name, m_file in marketplace_files.items():
            if m_file is None:
                continue
            try:
                df_m = load_file_safely(m_file)
            except Exception:
                continue
                
            if df_m.empty:
                continue
                
            # Determine platform to know which column candidates to use
            platform = channel_name.split()[0] # Lazada, Shopee, Zalora, TikTok
            
            if platform == "Lazada":
                candidates = ["orderNumber", "order_number", "order number"]
            elif platform == "Zalora":
                candidates = ["Order Number", "order number", "order_number", "orderNumber"]
            elif platform == "Shopee":
                candidates = ["Order ID", "order_id", "order id", "OrderID"]
            elif platform == "TikTok":
                candidates = ["Order ID", "order_id", "order id", "OrderID"]
            else:
                candidates = ["Order ID", "Order Number", "order_number", "orderNumber", "order_id"]
                
            id_col = _find_column(df_m, candidates)
            if not id_col:
                fallback_candidates = ["Order ID", "Order Number", "Order No", "OrderNo", "OrderID", "OrderNumber"]
                id_col = _find_column(df_m, fallback_candidates)
                if not id_col:
                    continue
                    
            # Normalize order IDs in the marketplace dataframe
            df_m = df_m.copy()
            df_m[id_col] = df_m[id_col].apply(_clean_order_id)
            
            # Extract other context columns if they exist
            sku_col = _find_column(df_m, ["Seller SKU", "SKU", "SellerSku", "item_sku", "item sku"])
            status_col = _find_column(df_m, ["Status", "Order Status", "orderStatus", "item_status", "status"])
            date_col = _find_column(df_m, ["Order Date", "Created At", "date", "created_at", "create_time", "create time"])
            price_col = _find_column(df_m, ["Price", "Amount", "payment_amount", "item_price", "price", "amount"])
            
            # Find unique order IDs in this marketplace file
            unique_order_ids = df_m[id_col].dropna().unique()
            total_orders = len(unique_order_ids)
            
            channel_missing_count = 0
            
            for m_oid in unique_order_ids:
                if not m_oid:
                    continue
                if m_oid not in tc_order_ids:
                    channel_missing_count += 1
                    
                    # Extract aggregated values for this missing order
                    order_rows = df_m[df_m[id_col] == m_oid]
                    
                    sku_val = "N/A"
                    if sku_col:
                        skus = order_rows[sku_col].dropna().unique()
                        skus = [s for s in skus if s.strip()]
                        sku_val = ", ".join(skus) if skus else "N/A"
                        
                    status_val = "N/A"
                    if status_col:
                        statuses = order_rows[status_col].dropna().unique()
                        statuses = [s for s in statuses if s.strip()]
                        status_val = ", ".join(statuses) if statuses else "N/A"
                        
                    date_val = "N/A"
                    if date_col:
                        date_val = _clean_str(order_rows.iloc[0][date_col])
                        
                    price_val = "N/A"
                    if price_col:
                        try:
                            prices = order_rows[price_col].dropna().astype(str).str.replace(",", "").astype(float)
                            price_val = f"{prices.sum():.2f}"
                        except Exception:
                            prices = order_rows[price_col].dropna().unique()
                            price_val = ", ".join([str(p) for p in prices])
                            
                    missing_mp_orders.append({
                        "Channel": channel_name,
                        "Marketplace Order ID": m_oid,
                        "Seller SKU": sku_val,
                        "Marketplace Status": status_val,
                        "Order Date": date_val,
                        "Price": price_val
                    })
                    
            matched_count = total_orders - channel_missing_count
            match_rate = (matched_count / total_orders * 100) if total_orders > 0 else 100.0
            
            mp_summaries.append({
                "Channel": channel_name,
                "Total Uploaded Orders": total_orders,
                "Matched in TC": matched_count,
                "Missing in TC": channel_missing_count,
                "Match Rate (%)": f"{match_rate:.2f}%"
            })
            
    df_missing_mp = pd.DataFrame(missing_mp_orders) if missing_mp_orders else pd.DataFrame(columns=[
        "Channel", "Marketplace Order ID", "Seller SKU", "Marketplace Status", "Order Date", "Price"
    ])
    df_mp_summary = pd.DataFrame(mp_summaries) if mp_summaries else pd.DataFrame(columns=[
        "Channel", "Total Uploaded Orders", "Matched in TC", "Missing in TC", "Match Rate (%)"
    ])

    summary["total_missing_mp_orders"] = len(df_missing_mp)

    return {
        "enriched_pending_df": df_pending,
        "discrepancies_df": df_discrepancies,
        "summary": summary,
        "seller_groups": seller_groups,
        "pending_order_id_col": target_sla_col,
        "missing_mp_df": df_missing_mp,
        "mp_summary_df": df_mp_summary
    }

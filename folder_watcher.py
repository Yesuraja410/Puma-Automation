import os
import sys
import time
import shutil
import re
import glob
import json
import traceback
import winsound
from datetime import datetime
import pandas as pd

# Import backend modules from current folder
from file_loaders import load_all_files
from validators import run_sku_validation, run_pid_validation, save_df_to_excel_fast
from order_processor import process_and_validate_orders

# Import Listing QC modules
from listing_qc_validator.utils.file_loaders import (
    load_file_to_df as lqc_load_file_to_df, 
    load_google_sheet as lqc_load_google_sheet, 
    auto_map_columns as lqc_auto_map_columns, 
    standardize_dataframe as lqc_standardize_dataframe,
    CANONICAL_LABELS as LQC_CANONICAL_LABELS,
    load_content as lqc_load_content,
    load_zecom as lqc_load_zecom,
    load_excel_all_sheets as lqc_load_excel_all_sheets
)
from listing_qc_validator.utils.validators import (
    validate_dataframe as lqc_validate_dataframe, 
    ALLOWED_GENDERS as LQC_ALLOWED_GENDERS,
    ALLOWED_STATUSES as LQC_ALLOWED_STATUSES
)
from listing_qc_validator.utils.report_generator import (
    generate_qc_excel_report as lqc_generate_qc_excel_report
)

# Root directory configuration
ROOT_DIR = r"C:\Users\Yesuraja\Desktop\PUMA_Automation"
INPUT_DIR = os.path.join(ROOT_DIR, "1_Input_Files")
OUTPUT_DIR = os.path.join(ROOT_DIR, "2_Output_Reports")
ARCHIVE_DIR = os.path.join(ROOT_DIR, "Archive")
LOG_FILE = os.path.join(ROOT_DIR, "watcher_log.txt")

def log_message(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}\n"
    print(log_line.strip())
    try:
        with open(LOG_FILE, "a") as f:
            f.write(log_line)
    except Exception:
        pass

def alert_sound(alert_type="success"):
    try:
        if alert_type == "success":
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        elif alert_type == "error":
            winsound.MessageBeep(winsound.MB_ICONHAND)
        else:
            winsound.MessageBeep(winsound.MB_OK)
    except Exception:
        pass

# File-like wrapper to load local file paths
class LocalFileWrapper:
    def __init__(self, filepath):
        self.filepath = filepath
        self.name = os.path.basename(filepath)
        self.file_obj = open(filepath, 'rb')
    def read(self, size=-1):
        return self.file_obj.read(size)
    def seek(self, offset):
        self.file_obj.seek(offset)
    def close(self):
        self.file_obj.close()

def wait_for_files_to_stabilize(filepaths, wait_time=2, check_interval=1):
    """Ensures files are fully written (e.g. copied from another folder) before processing."""
    log_message("Checking if input files are fully copied...")
    while True:
        sizes_before = [os.path.getsize(f) for f in filepaths if os.path.exists(f)]
        time.sleep(wait_time)
        sizes_after = [os.path.getsize(f) for f in filepaths if os.path.exists(f)]
        if sizes_before == sizes_after:
            log_message("Files are stable and ready for processing.")
            break
        log_message("Files are still being written. Waiting...")
        time.sleep(check_interval)

def archive_files(filepaths, subfolder_name, status="success"):
    """Moves raw input files to Archive folder or Failed folder."""
    target_dir = os.path.join(ARCHIVE_DIR, subfolder_name)
    if status == "failed":
        target_dir = os.path.join(ROOT_DIR, "Failed_Files", subfolder_name)
    os.makedirs(target_dir, exist_ok=True)
    
    today_folder = os.path.join(target_dir, datetime.now().strftime("%Y-%m-%d_%H%M%S"))
    os.makedirs(today_folder, exist_ok=True)
    
    for f in filepaths:
        if os.path.exists(f):
            dest = os.path.join(today_folder, os.path.basename(f))
            try:
                shutil.move(f, dest)
                log_message(f"Moved input file to archive: {os.path.basename(f)}")
            except Exception as e:
                log_message(f"Error archiving file {f}: {e}")

def detect_country(filenames, default="PH"):
    """Detects country based on filenames."""
    for f in filenames:
        f_upper = f.upper()
        if "SG" in f_upper or "_SG_" in f_upper:
            return "SG"
        if "MY" in f_upper or "_MY_" in f_upper:
            return "MY"
        if "PH" in f_upper or "_PH_" in f_upper:
            return "PH"
    return default

# ── TASK 1: Status & Stock Validation ─────────────────────────────────────────
def process_status_validation(folder_path):
    files = [os.path.join(folder_path, f) for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
    if not files:
        return
        
    log_message("=" * 60)
    log_message(f"Processing Status & Stock Validation in {folder_path}...")
    wait_for_files_to_stabilize(files)
    
    country = detect_country([os.path.basename(f) for f in files])
    log_message(f"Detected country: {country}")
    
    # Identify files
    vars_map = {
        "lazada_file": None,
        "shopee_stock_file": None,
        "shopee_status_file": None,
        "zalora_stock_file": None,
        "zalora_status_file": None,
        "content_file": None,
        "tc_inv_file": None,
        "zecom_file": None,
        "all_file": None,
        "exclusion_file": None
    }
    
    for f in files:
        fname = os.path.basename(f).lower()
        if "lazada" in fname and fname.endswith((".xlsx", ".xls")):
            vars_map["lazada_file"] = f
        elif ("shopee" in fname and "stock" in fname) or "sales_info" in fname or "sales info" in fname:
            vars_map["shopee_stock_file"] = f
        elif ("shopee" in fname and "status" in fname) or "basic_info" in fname or "basic info" in fname:
            vars_map["shopee_status_file"] = f
        elif "zalora" in fname and "stock" in fname:
            vars_map["zalora_stock_file"] = f
        elif "zalora" in fname and "status" in fname:
            vars_map["zalora_status_file"] = f
        elif "content" in fname:
            vars_map["content_file"] = f
        elif "tc" in fname or "shopee-ph" in fname or "shopee-sg" in fname or "shopee-my" in fname:
            vars_map["tc_inv_file"] = f
        elif "zecom" in fname or "tracking" in fname or "ecom" in fname:
            vars_map["zecom_file"] = f
        elif "all" in fname:
            vars_map["all_file"] = f
        elif "exclusion" in fname or "exclusio" in fname or "excl" in fname:
            vars_map["exclusion_file"] = f

    # Open wrappers and check for missing files
    has_marketplace = False
    if vars_map["lazada_file"]:
        has_marketplace = True
    if vars_map["shopee_stock_file"] and vars_map["shopee_status_file"]:
        has_marketplace = True
    if vars_map["zalora_stock_file"]:
        has_marketplace = True

    if not has_marketplace:
        log_message("[WARNING] No active marketplace files detected! The generated report will be empty.")
        log_message(" -> Shopee requires BOTH stock (containing 'sales_info' or 'shopee stock') and status (containing 'basic_info' or 'shopee status') files.")
        log_message(" -> Lazada requires a file containing 'lazada'.")
        log_message(" -> Zalora requires a file containing 'zalora' and 'stock'.")

    wrappers = {}
    for key, path in vars_map.items():
        if path:
            wrappers[key] = LocalFileWrapper(path)
            log_message(f"Mapped {key} -> {os.path.basename(path)}")
        else:
            wrappers[key] = None
            
    try:
        log_message("Parsing raw files...")
        data = load_all_files(
            country=country,
            lazada_file=wrappers["lazada_file"],
            shopee_stock_file=wrappers["shopee_stock_file"],
            shopee_status_file=wrappers["shopee_status_file"],
            zalora_stock_file=wrappers["zalora_stock_file"],
            zalora_status_file=wrappers["zalora_status_file"],
            tiktok_active_file=None,
            tiktok_inactive_file=None,
            content_file=wrappers["content_file"],
            tc_inv_file=wrappers["tc_inv_file"],
            zecom_file=wrappers["zecom_file"],
            all_file=wrappers["all_file"],
            exclusion_file=wrappers["exclusion_file"],
        )
        log_message("Parsing raw files complete.")
        # Close file handlers early so they are not locked during archiving
        for k, w in wrappers.items():
            if w is not None:
                w.close()
                wrappers[k] = None
        
        log_message("Executing matching rule checks...")
        sk = run_sku_validation(data, country)
        pi = run_pid_validation(data, country)
        
        sheets = {}
        if not sk.empty: sheets["SKU Level Validation"] = sk
        if not pi.empty: sheets["PID Level Validation"] = pi
        
        # Output directory setup
        out_sub = os.path.join(OUTPUT_DIR, "Status_Validation")
        os.makedirs(out_sub, exist_ok=True)
        
        today = datetime.today().strftime("%Y-%m-%d")
        fname = f"Status_Validation_Report_{country}_{today}_{datetime.now().strftime('%H%M%S')}.xlsx"
        fpath = os.path.join(out_sub, fname)
        
        log_message("Writing Excel report...")
        save_df_to_excel_fast(sheets, fpath)
                    
        log_message(f"Report generated: {fpath}")
        alert_sound("success")
        archive_files(files, "Status_Validation", "success")
        
    except Exception as e:
        log_message(f"Error processing status validation: {e}")
        traceback.print_exc()
        alert_sound("error")
        archive_files(files, "Status_Validation", "failed")
        
    finally:
        for w in wrappers.values():
            if w:
                w.close()

# ── TASK 2: QC Cross-Check ────────────────────────────────────────────────────
def process_qc_cross_check(folder_path):
    files = [os.path.join(folder_path, f) for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
    if not files:
        return
        
    log_message("=" * 60)
    log_message(f"Processing QC Cross-Check in {folder_path}...")
    wait_for_files_to_stabilize(files)
    
    country = detect_country([os.path.basename(f) for f in files])
    
    # Identify working sheet vs raw files
    working_file = None
    raw_files = []
    
    for f in files:
        fname = os.path.basename(f).lower()
        if "working" in fname or "audit" in fname or "qc_report" in fname or "validation_report" in fname:
            working_file = f
        else:
            raw_files.append(f)
            
    if not working_file:
        log_message("Error: Team Working Sheet comparison sheet not found. Skip.")
        return
        
    vars_map = {
        "lazada_file": None,
        "shopee_stock_file": None,
        "shopee_status_file": None,
        "zalora_stock_file": None,
        "zalora_status_file": None,
        "content_file": None,
        "tc_inv_file": None,
        "zecom_file": None,
        "all_file": None,
        "exclusion_file": None
    }
    
    for f in raw_files:
        fname = os.path.basename(f).lower()
        if "lazada" in fname and fname.endswith((".xlsx", ".xls")):
            vars_map["lazada_file"] = f
        elif "shopee" in fname and "stock" in fname:
            vars_map["shopee_stock_file"] = f
        elif "shopee" in fname and "status" in fname:
            vars_map["shopee_status_file"] = f
        elif "zalora" in fname and "stock" in fname:
            vars_map["zalora_stock_file"] = f
        elif "zalora" in fname and "status" in fname:
            vars_map["zalora_status_file"] = f
        elif "content" in fname:
            vars_map["content_file"] = f
        elif "tc" in fname or "shopee-ph" in fname or "shopee-sg" in fname or "shopee-my" in fname:
            vars_map["tc_inv_file"] = f
        elif "zecom" in fname or "tracking" in fname or "ecom" in fname:
            vars_map["zecom_file"] = f
        elif "all" in fname:
            vars_map["all_file"] = f
        elif "exclusion" in fname:
            vars_map["exclusion_file"] = f

    wrappers = {}
    for key, path in vars_map.items():
        if path:
            wrappers[key] = LocalFileWrapper(path)
            log_message(f"Mapped reference {key} -> {os.path.basename(path)}")
        else:
            wrappers[key] = None
            
    try:
        log_message("Loading reference sheets...")
        data = load_all_files(
            country=country,
            lazada_file=wrappers["lazada_file"],
            shopee_stock_file=wrappers["shopee_stock_file"],
            shopee_status_file=wrappers["shopee_status_file"],
            zalora_stock_file=wrappers["zalora_stock_file"],
            zalora_status_file=wrappers["zalora_status_file"],
            tiktok_active_file=None,
            tiktok_inactive_file=None,
            content_file=wrappers["content_file"],
            tc_inv_file=wrappers["tc_inv_file"],
            zecom_file=wrappers["zecom_file"],
            all_file=wrappers["all_file"],
            exclusion_file=wrappers["exclusion_file"],
        )
        # Close file handlers early so they are not locked during archiving
        for k, w in wrappers.items():
            if w is not None:
                w.close()
                wrappers[k] = None
        
        log_message("Reading uploaded working sheet...")
        xls = pd.ExcelFile(working_file)
        sheet_names = xls.sheet_names
        
        sku_sheet_name = None
        pid_sheet_name = None
        for name in sheet_names:
            name_lower = name.lower().strip()
            if "sku" in name_lower or "lazada" in name_lower or "zalora" in name_lower:
                sku_sheet_name = name
            elif "pid" in name_lower or "shopee" in name_lower or "tiktok" in name_lower:
                pid_sheet_name = name
                
        has_sku = sku_sheet_name is not None
        has_pid = pid_sheet_name is not None
        
        if not has_sku and not has_pid:
            raise ValueError("Working sheet does not contain recognized SKU or PID sheet names.")
            
        def standardize_columns(df):
            mapping = {
                "sellersku": "Seller SKU",
                "seller sku": "Seller SKU",
                "ecom (yes/no)": "e-com (Yes/No)",
                "e-com (yes/no)": "e-com (Yes/No)",
                "ecom(yes/no)": "e-com (Yes/No)",
                "graas status": "TC Status",
                "tc status": "TC Status",
                "final status (t/f)": "Final Check",
                "final check": "Final Check",
                "final status": "Final Status",
                "stock check": "Stock Check",
                "max setup": "Max Setup",
                "update 0": "Update 0",
            }
            new_cols = {}
            for col in df.columns:
                norm_col = str(col).strip().lower()
                if norm_col in mapping:
                    new_cols[col] = mapping[norm_col]
                else:
                    cleaned_col = norm_col.replace(" ", "").replace("-", "").replace("_", "")
                    matched = False
                    for k, v in mapping.items():
                        cleaned_k = k.replace(" ", "").replace("-", "").replace("_", "")
                        if cleaned_col == cleaned_k:
                            new_cols[col] = v
                            matched = True
                            break
                    if not matched:
                        new_cols[col] = col
            return df.rename(columns=new_cols)

        def prepare_working_df(working_df, correct_df, sheet_name, country):
            working_df = standardize_columns(working_df)
            if "Marketplace" not in working_df.columns:
                if "Seller SKU" in working_df.columns and not correct_df.empty and "Seller SKU" in correct_df.columns:
                    sku_to_mp = dict(zip(correct_df["Seller SKU"], correct_df["Marketplace"]))
                    working_df["Marketplace"] = working_df["Seller SKU"].map(sku_to_mp)
                else:
                    working_df["Marketplace"] = None
                fallback_mp = "Unknown"
                sheet_lower = sheet_name.lower()
                if "lazada" in sheet_lower:
                    fallback_mp = f"Lazada {country}"
                elif "zalora" in sheet_lower:
                    fallback_mp = f"Zalora {country}"
                elif "shopee" in sheet_lower:
                    fallback_mp = f"Shopee {country}"
                elif "tiktok" in sheet_lower:
                    fallback_mp = "TikTok MY"
                working_df["Marketplace"] = working_df["Marketplace"].fillna(fallback_mp)
            return working_df

        def values_match_fast(val1, val2):
            if val1 is val2: return True
            is_nan1 = (val1 is None or val1 != val1 or val1 == "nan" or val1 == "NaN")
            is_nan2 = (val2 is None or val2 != val2 or val2 == "nan" or val2 == "NaN")
            if is_nan1 and is_nan2: return True
            if is_nan1 or is_nan2: return False
            s1 = str(val1).strip()
            s2 = str(val2).strip()
            if s1 == s2: return True
            if s1.lower() == s2.lower(): return True
            try:
                f1 = float(s1.replace(",", ""))
                f2 = float(s2.replace(",", ""))
                if abs(f1 - f2) < 1e-5: return True
            except ValueError:
                pass
            return False

        def perform_qc_comparison(working_df, correct_df, key_cols, compare_cols):
            working_df = working_df.copy()
            correct_df = correct_df.copy()
            for col in key_cols:
                if col not in working_df.columns or col not in correct_df.columns:
                    return None, f"Missing key column '{col}'"
            for col in key_cols:
                working_df[col] = working_df[col].astype(str).str.strip()
                correct_df[col] = correct_df[col].astype(str).str.strip()
            working_df["_merge_key"] = working_df[key_cols].agg("||".join, axis=1)
            correct_df["_merge_key"] = correct_df[key_cols].agg("||".join, axis=1)
            working_df = working_df.drop_duplicates(subset=["_merge_key"])
            correct_df = correct_df.drop_duplicates(subset=["_merge_key"])
            working_keys = set(working_df["_merge_key"])
            correct_keys = set(correct_df["_merge_key"])
            missing_in_working = correct_df[~correct_df["_merge_key"].isin(working_keys)].copy()
            extra_in_working = working_df[~working_df["_merge_key"].isin(correct_keys)].copy()
            common_keys = working_keys.intersection(correct_keys)
            w_indexed = working_df.set_index("_merge_key")
            c_indexed = correct_df.set_index("_merge_key")
            w_dict = w_indexed.to_dict(orient="index")
            c_dict = c_indexed.to_dict(orient="index")
            mismatches = []
            cols_to_compare = [c for c in compare_cols if c in working_df.columns and c in correct_df.columns]
            for key in common_keys:
                w_row = w_dict[key]
                c_row = c_dict[key]
                row_diff = {}
                for col in cols_to_compare:
                    w_val = w_row[col]
                    c_val = c_row[col]
                    if not values_match_fast(w_val, c_val):
                        row_diff[col] = (w_val, c_val)
                if row_diff:
                    disp_vals = {col: w_row[col] for col in key_cols}
                    mismatches.append({**disp_vals, "diffs": row_diff})
            return {"mismatches": mismatches, "missing_in_working": missing_in_working, "extra_in_working": extra_in_working, "total_checked": len(common_keys)}, None

        qc_sheets = {}
        
        if has_sku:
            log_message("Performing SKU Validation comparison...")
            correct_sku = run_sku_validation(data, country)
            working_sku = pd.read_excel(working_file, sheet_name=sku_sheet_name)
            working_sku = prepare_working_df(working_sku, correct_sku, sku_sheet_name, country)
            
            if "SellerSku" in correct_sku.columns:
                correct_sku = correct_sku.rename(columns={"SellerSku": "Seller SKU"})
            
            sku_cols = ["TC SKU", "Article No", "MP Status", "TC Status", "e-com (Yes/No)", "Launch Date", "Exclusion", "ECOM Status", "MP Stock", "TC Stock", "Reserved Stock", "Max 0", "Final Status", "Comments", "Final Check", "Stock Check", "Remarks", "Max Setup", "Update 0"]
            sku_res, err = perform_qc_comparison(working_sku, correct_sku, ["Marketplace", "Seller SKU"], sku_cols)
            
            if err:
                log_message(f"SKU Comparison Error: {err}")
            else:
                m_rows = []
                for m in sku_res["mismatches"]:
                    for col, (w_val, c_val) in m["diffs"].items():
                        m_rows.append({"Marketplace": m["Marketplace"], "Seller SKU": m["Seller SKU"], "Field Name": col, "Team Value (Working)": w_val, "Expected Value (Computed)": c_val})
                sku_mismatch_df = pd.DataFrame(m_rows)
                sku_missing_df = sku_res["missing_in_working"][["Marketplace", "Seller SKU", "Final Status"]].copy() if not sku_res["missing_in_working"].empty else pd.DataFrame()
                sku_extra_df = sku_res["extra_in_working"][["Marketplace", "Seller SKU", "Final Status"]].copy() if not sku_res["extra_in_working"].empty else pd.DataFrame()
                
                qc_sheets["SKU Value Mismatches"] = sku_mismatch_df
                qc_sheets["SKU Missing Rows"] = sku_missing_df
                qc_sheets["SKU Extra Rows"] = sku_extra_df
                log_message(f" -> Found {len(sku_res['mismatches'])} SKU mismatches.")
                
        if has_pid:
            log_message("Performing PID Validation comparison...")
            correct_pid = run_pid_validation(data, country)
            working_pid = pd.read_excel(working_file, sheet_name=pid_sheet_name)
            working_pid = prepare_working_df(working_pid, correct_pid, pid_sheet_name, country)
            
            if "SellerSku" in correct_pid.columns:
                correct_pid = correct_pid.rename(columns={"SellerSku": "Seller SKU"})
            if "SellerSku" in working_pid.columns:
                working_pid = working_pid.rename(columns={"SellerSku": "Seller SKU"})
                
            pid_cols = ["TC SKU", "Article No", "MP Status", "TC Status", "e-com (Yes/No)", "Launch Date", "Exclusion", "ECOM Status", "MP Stock", "TC Stock", "Reserved Stock", "Max 0", "Final Status", "Comments", "Final Check", "Stock Check", "Remarks", "Max Setup", "Update 0"]
            pid_res, err = perform_qc_comparison(working_pid, correct_pid, ["Marketplace", "Product ID", "Seller SKU"], pid_cols)
            
            if err:
                log_message(f"PID Comparison Error: {err}")
            else:
                m_rows = []
                for m in pid_res["mismatches"]:
                    for col, (w_val, c_val) in m["diffs"].items():
                        m_rows.append({"Marketplace": m["Marketplace"], "Product ID": m["Product ID"], "Seller SKU": m["Seller SKU"], "Field Name": col, "Team Value (Working)": w_val, "Expected Value (Computed)": c_val})
                pid_mismatch_df = pd.DataFrame(m_rows)
                pid_missing_df = pid_res["missing_in_working"][["Marketplace", "Product ID", "Seller SKU", "Final Status"]].copy() if not pid_res["missing_in_working"].empty else pd.DataFrame()
                pid_extra_df = pid_res["extra_in_working"][["Marketplace", "Product ID", "Seller SKU", "Final Status"]].copy() if not pid_res["extra_in_working"].empty else pd.DataFrame()
                
                qc_sheets["PID Value Mismatches"] = pid_mismatch_df
                qc_sheets["PID Missing Rows"] = pid_missing_df
                qc_sheets["PID Extra Rows"] = pid_extra_df
                log_message(f" -> Found {len(pid_res['mismatches'])} PID mismatches.")
                
        # Write Report
        out_sub = os.path.join(OUTPUT_DIR, "QC_CrossCheck")
        os.makedirs(out_sub, exist_ok=True)
        
        fname = f"QC_Audit_Report_{country}_{datetime.today().strftime('%Y-%m-%d_%H%M%S')}.xlsx"
        fpath = os.path.join(out_sub, fname)
        
        log_message("Saving QC audit report...")
        with pd.ExcelWriter(fpath, engine="xlsxwriter") as writer:
            for sheet_name, df_sheet in qc_sheets.items():
                df_sheet.to_excel(writer, sheet_name=sheet_name, index=False)
                
        log_message(f"QC Audit completed successfully! Saved to: {fpath}")
        alert_sound("success")
        archive_files(files, "QC_CrossCheck", "success")
        
    except Exception as e:
        log_message(f"Error processing QC cross check: {e}")
        traceback.print_exc()
        alert_sound("error")
        archive_files(files, "QC_CrossCheck", "failed")
        
    finally:
        for w in wrappers.values():
            if w:
                w.close()

# ── TASK 3: Order & OMS Validation ────────────────────────────────────────────
def process_order_validation(folder_path):
    files = [os.path.join(folder_path, f) for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
    if not files:
        return
        
    log_message("=" * 60)
    log_message(f"Processing Order & OMS Validation in {folder_path}...")
    wait_for_files_to_stabilize(files)
    
    pending_path = None
    tc_path = None
    oms_path = None
    contacts_path = None
    
    mp_paths = {
        "Lazada SG": None, "Lazada MY": None, "Lazada PH": None,
        "Shopee SG": None, "Shopee MY": None, "Shopee PH": None,
        "Zalora SG": None, "Zalora MY": None, "Zalora PH": None,
        "TikTok MY": None
    }
    
    for f in files:
        fname = os.path.basename(f).lower()
        if "pending" in fname:
            pending_path = f
        elif "tc" in fname and "order" in fname:
            tc_path = f
        elif "oms" in fname:
            oms_path = f
        elif "contact" in fname or "seller" in fname:
            contacts_path = f
        else:
            # Map optional marketplace files
            for mp_key in mp_paths.keys():
                mp_lower = mp_key.lower()
                channel = mp_lower.split()[0]
                country = mp_lower.split()[1]
                if channel in fname and country in fname and "order" in fname:
                    mp_paths[mp_key] = f
                    log_message(f"Mapped specific orders: {mp_key} -> {os.path.basename(f)}")

    if not pending_path or not tc_path or not oms_path:
        log_message("Error: Required Pending, TC, and OMS order files must all be dropped. Skip.")
        return
        
    def safe_load(fpath):
        if not fpath or not os.path.exists(fpath): return None
        return pd.read_excel(fpath)
        
    try:
        log_message("Loading order sheets...")
        order_pending = safe_load(pending_path)
        order_tc = safe_load(tc_path)
        order_oms = safe_load(oms_path)
        seller_contacts = safe_load(contacts_path)
        
        marketplace_files = {}
        for key, path in mp_paths.items():
            if path:
                marketplace_files[key] = safe_load(path)
            else:
                marketplace_files[key] = None
                
        log_message("Executing SLA calculations and OMS validation rules...")
        res = process_and_validate_orders(
            order_pending=order_pending,
            order_tc=order_tc,
            order_oms=order_oms,
            seller_contacts=seller_contacts,
            marketplace_files=marketplace_files
        )
        
        out_sub = os.path.join(OUTPUT_DIR, "Order_Validation")
        os.makedirs(out_sub, exist_ok=True)
        
        today = datetime.today().strftime("%Y-%m-%d")
        fname = f"Order_OMS_Validation_Report_{today}_{datetime.now().strftime('%H%M%S')}.xlsx"
        fpath = os.path.join(out_sub, fname)
        
        with pd.ExcelWriter(fpath, engine="xlsxwriter") as writer:
            res["enriched_pending_df"].to_excel(writer, sheet_name="Enriched Pending Orders", index=False)
            res["discrepancies_df"].to_excel(writer, sheet_name="SLA & OMS Discrepancies", index=False)
            if not res["missing_mp_df"].empty:
                res["missing_mp_df"].to_excel(writer, sheet_name="Missing Marketplace Details", index=False)
            if not res["mp_summary_df"].empty:
                res["mp_summary_df"].to_excel(writer, sheet_name="Marketplace SLA Summary", index=False)
                
        summary = res["summary"]
        log_message("Order validation completed successfully!")
        log_message(f" -> Delayed SLAs: {summary['sla_discrepancies']}, OMS Status mismatches: {summary['oms_status_mismatches']}")
        log_message(f"Saved to: {fpath}")
        
        alert_sound("success")
        archive_files(files, "Order_Validation", "success")
        
    except Exception as e:
        log_message(f"Error processing orders: {e}")
        traceback.print_exc()
        alert_sound("error")
        archive_files(files, "Order_Validation", "failed")

# ── TASK 4: Listing QC Validation ─────────────────────────────────────────────
def process_listing_qc(folder_path):
    files = [os.path.join(folder_path, f) for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
    if not files:
        return
        
    log_message("=" * 60)
    log_message(f"Processing Listing QC Auditor in {folder_path}...")
    wait_for_files_to_stabilize(files)
    
    # Check if config files or settings exist
    config_file = os.path.join(folder_path, "settings.json")
    gsheet_file = os.path.join(folder_path, "gsheet_urls.txt")
    
    # Defaults
    lqc_country = detect_country([os.path.basename(f) for f in files])
    lqc_channel = "Lazada"
    lqc_qc_stage = "Internal QC"
    lqc_check_live_images = True
    
    # Load config file if it exists
    if os.path.exists(config_file):
        try:
            with open(config_file, "r") as f:
                cfg = json.load(f)
                lqc_country = cfg.get("country", lqc_country)
                lqc_channel = cfg.get("channel", lqc_channel)
                lqc_qc_stage = cfg.get("qc_stage", lqc_qc_stage)
                lqc_check_live_images = cfg.get("check_live_images", lqc_check_live_images)
                log_message(f"Loaded config: Stage={lqc_qc_stage}, Channel={lqc_channel}, Country={lqc_country}")
        except Exception as e:
            log_message(f"Error reading settings.json: {e}")

    content_path = None
    zecom_path = None
    target_paths = []
    
    for f in files:
        fname = os.path.basename(f).lower()
        if fname == "settings.json" or fname == "gsheet_urls.txt":
            continue
        if "content" in fname:
            content_path = f
        elif "zecom" in fname or "tracking" in fname:
            zecom_path = f
        else:
            target_paths.append(f)
            
    if not content_path or not zecom_path:
        log_message("Error: Reference Content File and zeCom Tracking File are required in folder. Skip.")
        return
        
    # Read Google Sheets from gsheet_urls.txt if present
    gsheet_urls = []
    if os.path.exists(gsheet_file):
        try:
            with open(gsheet_file, "r") as f:
                gsheet_urls = [line.strip() for line in f if line.strip()]
                log_message(f"Read {len(gsheet_urls)} Google Sheet URLs from gsheet_urls.txt")
        except Exception as e:
            log_message(f"Error reading gsheet_urls.txt: {e}")

    if not target_paths and not gsheet_urls:
        log_message("Error: Target catalog listing sheet or Google Sheet links must be provided. Skip.")
        return
        
    try:
        log_message("Loading references...")
        content_df = lqc_load_content(content_path)
        zecom_df = lqc_load_zecom(zecom_path, lqc_country)
        
        # Load targets
        upload_dfs = {}
        for tp in target_paths:
            log_message(f"Loading local target: {os.path.basename(tp)}")
            if tp.lower().endswith((".xlsx", ".xls")):
                sheets_dict = lqc_load_excel_all_sheets(tp, channel=lqc_channel)
                for s_name, df in sheets_dict.items():
                    upload_dfs[f"{os.path.basename(tp)} - {s_name}"] = df
            else:
                df = lqc_load_file_to_df(tp, channel=lqc_channel)
                upload_dfs[os.path.basename(tp)] = df
                
        for i, url in enumerate(gsheet_urls):
            log_message(f"Downloading Google Sheet link #{i+1}...")
            df = lqc_load_google_sheet(url, channel=lqc_channel)
            id_match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
            display_name = f"Google Sheet ({id_match.group(1)[:8]}...)" if id_match else f"Google Sheet #{i+1}"
            upload_dfs[display_name] = df
            
        # Standardize and map columns
        all_headers = []
        for fn, df in upload_dfs.items():
            all_headers.extend(df.columns.tolist())
        all_headers = sorted(list(set(all_headers)))
        
        auto_maps = lqc_auto_map_columns(all_headers)
        manual_mapping = {}
        for canonical in LQC_CANONICAL_LABELS.keys():
            if lqc_qc_stage == "Internal QC" and canonical in ["images", "size_chart"]:
                continue
            manual_mapping[canonical] = auto_maps.get(canonical)
            
        all_standardized = []
        for fn, df in upload_dfs.items():
            std_df = lqc_standardize_dataframe(df, manual_mapping, source_name=fn)
            all_standardized.append(std_df)
        combined_df = pd.concat(all_standardized, ignore_index=True)
        
        log_message("Executing catalog checks...")
        exc_df, val_df, logs = lqc_validate_dataframe(
            combined_df, 
            qc_stage=lqc_qc_stage,
            channel=lqc_channel,
            content_df=content_df,
            zecom_df=zecom_df,
            check_live_images=lqc_check_live_images,
            allowed_genders=LQC_ALLOWED_GENDERS,
            allowed_statuses=LQC_ALLOWED_STATUSES
        )
        
        # Save Report
        out_sub = os.path.join(OUTPUT_DIR, "Listing_QC")
        os.makedirs(out_sub, exist_ok=True)
        
        excel_data = lqc_generate_qc_excel_report(val_df, exc_df, lqc_qc_stage)
        fname = f"Listing_QC_Report_{lqc_qc_stage}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        fpath = os.path.join(out_sub, fname)
        
        with open(fpath, "wb") as f:
            f.write(excel_data)
            
        log_message(f"Listing QC Audit finished! saved to: {fpath}")
        alert_sound("success")
        archive_files(files, "Listing_QC", "success")
        
    except Exception as e:
        log_message(f"Error processing listing QC: {e}")
        traceback.print_exc()
        alert_sound("error")
        archive_files(files, "Listing_QC", "failed")

# ── Main Watcher Loop ─────────────────────────────────────────────────────────
def main():
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    
    subfolders = ["Status_Validation", "QC_CrossCheck", "Order_Validation", "Listing_QC"]
    for sub in subfolders:
        os.makedirs(os.path.join(INPUT_DIR, sub), exist_ok=True)
        os.makedirs(os.path.join(OUTPUT_DIR, sub), exist_ok=True)
        os.makedirs(os.path.join(ARCHIVE_DIR, sub), exist_ok=True)
        
    log_message("=" * 60)
    log_message("PUMA Automation Background Folder Watcher Started.")
    log_message(f"Monitoring folder: {INPUT_DIR}")
    log_message("Press Ctrl+C inside command prompt to exit.")
    log_message("=" * 60)
    
    # Sound confirmation on start
    alert_sound("start")
    
    while True:
        try:
            process_status_validation(os.path.join(INPUT_DIR, "Status_Validation"))
            process_qc_cross_check(os.path.join(INPUT_DIR, "QC_CrossCheck"))
            process_order_validation(os.path.join(INPUT_DIR, "Order_Validation"))
            process_listing_qc(os.path.join(INPUT_DIR, "Listing_QC"))
        except KeyboardInterrupt:
            log_message("Watcher manually stopped. Goodbye!")
            sys.exit(0)
        except Exception as e:
            log_message(f"Error in watcher loop: {e}")
            
        time.sleep(5)

if __name__ == "__main__":
    main()

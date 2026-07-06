import sys
import os
import io
import gc
import base64
from datetime import datetime

# Ensure project root is in path for imports on Vercel
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd

# Core imports
from file_loaders import load_all_files
from validators import run_sku_validation, run_pid_validation, save_df_to_excel_fast
from order_processor import process_and_validate_orders
from email_sender import test_smtp_connection, send_seller_report_email

# Listing QC imports
from listing_qc_validator.utils.file_loaders import (
    load_file_to_df as lqc_load_file_to_df, 
    load_google_sheet as lqc_load_google_sheet, 
    standardize_dataframe as lqc_standardize_dataframe,
    load_content as lqc_load_content,
    load_zecom as lqc_load_zecom,
    load_excel_all_sheets as lqc_load_excel_all_sheets,
    process_live_files as lqc_process_live_files
)
from listing_qc_validator.utils.validators import (
    validate_dataframe as lqc_validate_dataframe, 
    compare_source_and_live as lqc_compare_source_and_live,
    ALLOWED_GENDERS as LQC_ALLOWED_GENDERS,
    ALLOWED_STATUSES as LQC_ALLOWED_STATUSES
)
from listing_qc_validator.utils.report_generator import (
    generate_qc_excel_report as lqc_generate_qc_excel_report,
    generate_comparison_excel_report as lqc_generate_comparison_excel_report
)

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
public_dir = os.path.join(project_root, "public")

app = Flask(__name__, static_folder=public_dir, static_url_path="")
CORS(app)

@app.route("/")
def index():
    return app.send_static_file("index.html")

# Wrapper class to make Flask FileStorage object compatible with _read_file
class FileWrapper:
    def __init__(self, file_storage):
        self.file_storage = file_storage
        self.name = file_storage.filename
    def read(self, *args, **kwargs):
        return self.file_storage.read(*args, **kwargs)
    def seek(self, *args, **kwargs):
        return self.file_storage.seek(*args, **kwargs)
    def tell(self, *args, **kwargs):
        return self.file_storage.tell(*args, **kwargs)


def _make_filename(data, country):
    channel_map = {
        "lazada": "Lazada",
        "shopee": "Shopee",
        "zalora": "Zalora",
        "tiktok": "TikTok",
    }
    channels = []
    for key, label in channel_map.items():
        df = data.get(key, pd.DataFrame())
        if df is not None and not df.empty:
            channels.append(label)
    today = datetime.today().strftime("%Y-%m-%d")
    if channels:
        return "_".join(channels) + "_" + country + "_Status_Validation_Report_" + today + ".xlsx"
    return "Status_Validation_Report_" + country + "_" + today + ".xlsx"


def _write_report_in_memory(sheets):
    """Write Excel report to bytes buffer and return base64 string."""
    excel_buffer = io.BytesIO()
    save_df_to_excel_fast(sheets, excel_buffer)
    excel_buffer.seek(0)
    return base64.b64encode(excel_buffer.read()).decode("utf-8")


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "message": "Backend server is running locally"}), 200


@app.route("/api/status-validation", methods=["POST"])
def status_validation():
    try:
        country = request.form.get("country", "SG")
        
        # Wrap uploaded files
        def get_file(key):
            f = request.files.get(key)
            return FileWrapper(f) if f and f.filename else None

        data = load_all_files(
            country=country,
            lazada_file=get_file("laz"),
            shopee_stock_file=get_file("sh_stk"),
            shopee_status_file=get_file("sh_sts"),
            zalora_stock_file=get_file("zal_stk"),
            zalora_status_file=get_file("zal_sts"),
            tiktok_active_file=get_file("tt_act"),
            tiktok_inactive_file=get_file("tt_ina"),
            content_file=get_file("cnt"),
            tc_inv_file=get_file("tc"),
            zecom_file=get_file("zec"),
            all_file=get_file("alf"),
            exclusion_file=get_file("excl")
        )

        sk = run_sku_validation(data, country)
        pi = run_pid_validation(data, country)

        cols = [
            "Marketplace", "Seller SKU", "TC SKU", "Article No", "MP Status",
            "TC Status", "e-com (Yes/No)", "Launch Date", "Exclusion", "ECOM Status",
            "MP Stock", "TC Stock", "Reserved Stock", "Max 0"
        ]
        sr_parts = []
        if not sk.empty:
            sr_parts.append(sk[cols])
        if not pi.empty:
            pi_cols = [c if c != "Seller SKU" else "SellerSku" for c in cols]
            temp_pi = pi[pi_cols].rename(columns={"SellerSku": "Seller SKU"})
            sr_parts.append(temp_pi)
        sr = pd.concat(sr_parts, ignore_index=True) if sr_parts else pd.DataFrame()

        fname = _make_filename(data, country)

        # Build excel sheets
        sheets = {}
        if not sk.empty:
            sheets["SKU Level Validation"] = sk
        if not pi.empty:
            sheets["PID Level Validation"] = pi

        if not sheets:
            return jsonify({"success": False, "message": "No data generated. Check your input files."}), 400

        report_b64 = _write_report_in_memory(sheets)

        # Prepare metrics
        metrics = {
            "total_rows": len(sr),
            "active_count": int((sr["Final Status"] == "Active").sum()) if "Final Status" in sr.columns else 0,
            "inactive_count": int((sr["Final Status"] == "Inactive").sum()) if "Final Status" in sr.columns else 0,
            "true_checks": int((sr["Final Check"] == "True").sum()) if "Final Check" in sr.columns else 0
        }

        # Send preview first 500 rows
        preview_data = sr.head(500).to_dict(orient="records")

        # Clean up
        del data, sk, pi, sr, sheets
        gc.collect()

        return jsonify({
            "success": True,
            "metrics": metrics,
            "report_name": fname,
            "report_base64": report_b64,
            "preview": preview_data
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/status-validation-qc", methods=["POST"])
def status_validation_qc():
    try:
        country = request.form.get("country", "SG")
        
        def get_file(key):
            f = request.files.get(key)
            return FileWrapper(f) if f and f.filename else None

        working_file = get_file("qc_working_file")
        if not working_file:
            return jsonify({"success": False, "message": "Missing Team Working Sheet file"}), 400

        # Load raw reference files
        data = load_all_files(
            country=country,
            lazada_file=get_file("laz"),
            shopee_stock_file=get_file("sh_stk"),
            shopee_status_file=get_file("sh_sts"),
            zalora_stock_file=get_file("zal_stk"),
            zalora_status_file=get_file("zal_sts"),
            tiktok_active_file=get_file("tt_act"),
            tiktok_inactive_file=get_file("tt_ina"),
            content_file=get_file("cnt"),
            tc_inv_file=get_file("tc"),
            zecom_file=get_file("zec"),
            all_file=get_file("alf"),
            exclusion_file=get_file("excl")
        )

        # Open the uploaded working sheet to inspect sheets
        excel_buffer = io.BytesIO(working_file.read())
        working_file.seek(0)
        xls = pd.ExcelFile(excel_buffer)
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
            return jsonify({"success": False, "message": f"The uploaded file does not contain SKU or PID sheets. Sheets found: {', '.join(sheet_names)}"}), 400

        # Helpers
        def standardize_columns(df):
            mapping = {
                "sellersku": "Seller SKU",
                "seller sku": "Seller SKU",
                "ecom (yes/no)": "e-com (Yes/No)",
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

        def prepare_working_df(working_df, correct_df, sheet_name):
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
            if val1 is val2:
                return True
            is_nan1 = (val1 is None or val1 != val1 or val1 == "nan" or val1 == "NaN")
            is_nan2 = (val2 is None or val2 != val2 or val2 == "nan" or val2 == "NaN")
            if is_nan1 and is_nan2:
                return True
            if is_nan1 or is_nan2:
                return False
            s1 = str(val1).strip()
            s2 = str(val2).strip()
            if s1 == s2:
                return True
            if s1.lower() == s2.lower():
                return True
            try:
                f1 = float(s1.replace(",", ""))
                f2 = float(s2.replace(",", ""))
                if abs(f1 - f2) < 1e-5:
                    return True
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
            return {
                "mismatches": mismatches,
                "missing_in_working": missing_in_working,
                "extra_in_working": extra_in_working,
                "total_checked": len(common_keys)
            }, None

        qc_sheets = {}
        summary_metrics = {
            "total_rows_checked": 0,
            "mismatches_count": 0,
            "missing_rows_count": 0,
            "extra_rows_count": 0
        }

        # SKU audit
        if has_sku:
            correct_sku = run_sku_validation(data, country)
            working_sku = pd.read_excel(xls, sheet_name=sku_sheet_name)
            working_sku = prepare_working_df(working_sku, correct_sku, sku_sheet_name)
            
            if "SellerSku" in correct_sku.columns:
                correct_sku = correct_sku.rename(columns={"SellerSku": "Seller SKU"})
            
            sku_cols = ["TC SKU", "Article No", "MP Status", "TC Status", "e-com (Yes/No)", "Launch Date", "Exclusion", "ECOM Status", "MP Stock", "TC Stock", "Reserved Stock", "Max 0", "Final Status", "Comments", "Final Check", "Stock Check", "Remarks", "Max Setup", "Update 0"]
            sku_res, err = perform_qc_comparison(working_sku, correct_sku, ["Marketplace", "Seller SKU"], sku_cols)
            
            if err:
                return jsonify({"success": False, "error": f"SKU Audit error: {err}"}), 400
            
            m_rows = []
            for m in sku_res["mismatches"]:
                for col, (w_val, c_val) in m["diffs"].items():
                    m_rows.append({
                        "Marketplace": m["Marketplace"],
                        "Seller SKU": m["Seller SKU"],
                        "Field Name": col,
                        "Team Value (Working)": str(w_val),
                        "Expected Value (Computed)": str(c_val)
                    })
            sku_mismatch_df = pd.DataFrame(m_rows) if m_rows else pd.DataFrame(columns=["Marketplace", "Seller SKU", "Field Name", "Team Value (Working)", "Expected Value (Computed)"])
            sku_missing_df = sku_res["missing_in_working"][["Marketplace", "Seller SKU", "Final Status"]].copy() if not sku_res["missing_in_working"].empty else pd.DataFrame(columns=["Marketplace", "Seller SKU", "Final Status"])
            sku_extra_df = sku_res["extra_in_working"][["Marketplace", "Seller SKU", "Final Status"]].copy() if not sku_res["extra_in_working"].empty else pd.DataFrame(columns=["Marketplace", "Seller SKU", "Final Status"])
            
            qc_sheets["SKU Value Mismatches"] = sku_mismatch_df
            qc_sheets["SKU Missing Rows"] = sku_missing_df
            qc_sheets["SKU Extra Rows"] = sku_extra_df

            summary_metrics["total_rows_checked"] += sku_res["total_checked"]
            summary_metrics["mismatches_count"] += len(sku_res["mismatches"])
            summary_metrics["missing_rows_count"] += len(sku_missing_df)
            summary_metrics["extra_rows_count"] += len(sku_extra_df)

        # PID audit
        if has_pid:
            correct_pid = run_pid_validation(data, country)
            working_pid = pd.read_excel(xls, sheet_name=pid_sheet_name)
            working_pid = prepare_working_df(working_pid, correct_pid, pid_sheet_name)
            
            if "SellerSku" in correct_pid.columns:
                correct_pid = correct_pid.rename(columns={"SellerSku": "Seller SKU"})
            
            pid_cols = ["TC SKU", "Product ID", "Article No", "MP Status", "TC Status", "e-com (Yes/No)", "Launch Date", "Exclusion", "ECOM Status", "Final Status", "Comments", "Final Check", "Dual Status", "Consolidated SUM QTY", "MP Stock", "TC Stock", "Reserved Stock", "Max 0", "Stock Check", "Remarks", "Max Setup", "Update 0"]
            pid_res, err = perform_qc_comparison(working_pid, correct_pid, ["Marketplace", "Seller SKU"], pid_cols)
            
            if err:
                return jsonify({"success": False, "error": f"PID Audit error: {err}"}), 400
                
            m_rows = []
            for m in pid_res["mismatches"]:
                for col, (w_val, c_val) in m["diffs"].items():
                    m_rows.append({
                        "Marketplace": m["Marketplace"],
                        "Seller SKU": m["Seller SKU"],
                        "Field Name": col,
                        "Team Value (Working)": str(w_val),
                        "Expected Value (Computed)": str(c_val)
                    })
            pid_mismatch_df = pd.DataFrame(m_rows) if m_rows else pd.DataFrame(columns=["Marketplace", "Seller SKU", "Field Name", "Team Value (Working)", "Expected Value (Computed)"])
            pid_missing_df = pid_res["missing_in_working"][["Marketplace", "Seller SKU", "Final Status"]].copy() if not pid_res["missing_in_working"].empty else pd.DataFrame(columns=["Marketplace", "Seller SKU", "Final Status"])
            pid_extra_df = pid_res["extra_in_working"][["Marketplace", "Seller SKU", "Final Status"]].copy() if not pid_res["extra_in_working"].empty else pd.DataFrame(columns=["Marketplace", "Seller SKU", "Final Status"])

            qc_sheets["PID Value Mismatches"] = pid_mismatch_df
            qc_sheets["PID Missing Rows"] = pid_missing_df
            qc_sheets["PID Extra Rows"] = pid_extra_df

            summary_metrics["total_rows_checked"] += pid_res["total_checked"]
            summary_metrics["mismatches_count"] += len(pid_res["mismatches"])
            summary_metrics["missing_rows_count"] += len(pid_missing_df)
            summary_metrics["extra_rows_count"] += len(pid_extra_df)

        today = datetime.today().strftime("%Y-%m-%d")
        qc_fname = f"QC_Audit_Report_{country}_{today}.xlsx"
        report_b64 = _write_report_in_memory(qc_sheets)

        return jsonify({
            "success": True,
            "metrics": summary_metrics,
            "report_name": qc_fname,
            "report_base64": report_b64
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/order-validation", methods=["POST"])
def order_validation():
    try:
        pending_source = request.form.get("pending_source", "Upload File")
        gsheet_url = request.form.get("gsheet_url", "")
        
        def get_file(key):
            f = request.files.get(key)
            return FileWrapper(f) if f and f.filename else None

        order_tc = get_file("order_tc")
        order_oms = get_file("order_oms")
        seller_contacts = get_file("seller_contacts")

        if pending_source == "Upload File":
            order_pending = get_file("order_pending")
        else:
            order_pending = gsheet_url if gsheet_url.strip() else None

        if not order_tc or not order_oms:
            return jsonify({"success": False, "message": "Missing TC Report or OMS Report"}), 400

        res = process_and_validate_orders(order_pending, order_tc, order_oms, seller_contacts)

        enriched_df = res["enriched_pending_df"]
        disc_df = res["discrepancies_df"]
        summary = res["summary"]
        seller_groups = res["seller_groups"]

        # Save Excel report in memory
        sheets = {
            "Status Report": enriched_df if not enriched_df.empty else pd.DataFrame([{"Message": "No pending orders."}]),
            "Discrepancies": disc_df if not disc_df.empty else pd.DataFrame([{"Message": "No discrepancies found."}])
        }
        
        today = datetime.today().strftime("%Y-%m-%d")
        fname = f"Order_Validation_Report_{today}.xlsx"
        report_b64 = _write_report_in_memory(sheets)

        # Serialize seller groups for the frontend to store statelessly
        seller_groups_json = {}
        for s_name, s_info in seller_groups.items():
            seller_groups_json[s_name] = {
                "email": s_info["email"],
                "data": s_info["df"].to_dict(orient="records") if not s_info["df"].empty else []
            }

        return jsonify({
            "success": True,
            "metrics": summary,
            "discrepancies_preview": disc_df.head(500).to_dict(orient="records"),
            "discrepancies_all": disc_df.to_dict(orient="records"),
            "report_name": fname,
            "report_base64": report_b64,
            "seller_groups": seller_groups_json
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/send-email", methods=["POST"])
def send_email():
    try:
        req_data = request.json
        smtp_config = req_data.get("smtp_config")
        seller_name = req_data.get("seller_name")
        recipient_email = req_data.get("recipient_email")
        seller_data = req_data.get("seller_data", [])
        discrepancies_data = req_data.get("discrepancies_data", [])

        seller_df = pd.DataFrame(seller_data)
        disc_df = pd.DataFrame(discrepancies_data) if discrepancies_data else None

        ok, msg = send_seller_report_email(smtp_config, seller_name, recipient_email, seller_df, disc_df)
        
        if ok:
            return jsonify({"success": True, "message": f"Email successfully sent to {seller_name}!"})
        else:
            return jsonify({"success": False, "message": msg})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/test-smtp", methods=["POST"])
def test_smtp():
    try:
        smtp_config = request.json
        host = smtp_config.get("host")
        port = smtp_config.get("port")
        user = smtp_config.get("user")
        password = smtp_config.get("password")
        use_tls = smtp_config.get("use_tls", True)

        ok, msg = test_smtp_connection(host, port, user, password, use_tls)
        return jsonify({"success": ok, "message": msg})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/listing-qc", methods=["POST"])
def listing_qc():
    try:
        channel = request.form.get("channel", "Shopee PH")
        qc_stage = request.form.get("qc_stage", "Internal QC")
        check_live_images = request.form.get("check_live_images") == "true"
        
        allowed_genders_str = request.form.get("allowed_genders", "")
        allowed_genders = [g.strip().lower() for g in allowed_genders_str.split(",") if g.strip()] if allowed_genders_str else list(LQC_ALLOWED_GENDERS)
        
        allowed_statuses_str = request.form.get("allowed_statuses", "")
        allowed_statuses = [s.strip().lower() for s in allowed_statuses_str.split(",") if s.strip()] if allowed_statuses_str else list(LQC_ALLOWED_STATUSES)

        def get_file(key):
            f = request.files.get(key)
            return FileWrapper(f) if f and f.filename else None

        content_file = get_file("content")
        zecom_file = get_file("zecom")
        
        country = channel.split()[-1]
        
        # Load references
        content_df = lqc_load_content(content_file)
        zecom_df = lqc_load_zecom(zecom_file, country)

        # Collect target files
        upload_dfs = {}
        for key, f in request.files.items():
            if key.startswith("target_"):
                wrapper = FileWrapper(f)
                if wrapper.name.lower().endswith((".xlsx", ".xls")):
                    sheets_dict = lqc_load_excel_all_sheets(wrapper, channel=channel)
                    for s_name, df in sheets_dict.items():
                        upload_dfs[f"{wrapper.name} - {s_name}"] = df
                else:
                    df = lqc_load_file_to_df(wrapper, channel=channel)
                    upload_dfs[wrapper.name] = df

        if not upload_dfs:
            return jsonify({"success": False, "message": "No target listing sheets uploaded."}), 400

        # Handle manual mapping empty for now
        manual_mapping = {}
        all_standardized = []
        for fn, df in upload_dfs.items():
            std_df = lqc_standardize_dataframe(df, manual_mapping, source_name=fn)
            all_standardized.append(std_df)
        combined_df = pd.concat(all_standardized, ignore_index=True)

        exc_df, val_df, logs = lqc_validate_dataframe(
            combined_df, 
            qc_stage=qc_stage,
            channel=channel,
            content_df=content_df,
            zecom_df=zecom_df,
            check_live_images=check_live_images,
            allowed_genders=allowed_genders,
            allowed_statuses=allowed_statuses
        )

        excel_data = lqc_generate_qc_excel_report(val_df, exc_df, qc_stage)
        report_b64 = base64.b64encode(excel_data).decode("utf-8")
        fname = f"Listing_QC_Report_{qc_stage}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        # Construct checklist stats
        child_df = val_df[val_df["sku"].fillna("").astype(str).str.strip().str.match(r'^\d{13}$')]
        no_status_count = int(sum(child_df["Zeocm Status"] != "Yes")) if "Zeocm Status" in child_df.columns else 0
        
        launch_excs = exc_df[exc_df["Field"] == "Launch Date"] if not exc_df.empty else pd.DataFrame()
        launch_rows = int(launch_excs.groupby(["Source File", "Row Number"]).ngroups) if not launch_excs.empty else 0
        
        gender_excs = exc_df[
            (exc_df["Field"] == "Gender") | 
            ((exc_df["Field"] == "Product Name") & exc_df["Message"].str.contains("gender", case=False, na=False))
        ] if not exc_df.empty else pd.DataFrame()
        gender_rows = int(gender_excs.groupby(["Source File", "Row Number"]).ngroups) if not gender_excs.empty else 0
        
        color_excs = exc_df[exc_df["Field"] == "Color Name"] if not exc_df.empty else pd.DataFrame()
        color_rows = int(color_excs.groupby(["Source File", "Row Number"]).ngroups) if not color_excs.empty else 0
        
        size_excs = exc_df[exc_df["Field"] == "Size"] if not exc_df.empty else pd.DataFrame()
        size_rows = int(size_excs.groupby(["Source File", "Row Number"]).ngroups) if not size_excs.empty else 0
        
        price_excs = exc_df[exc_df["Field"] == "Price"] if not exc_df.empty else pd.DataFrame()
        price_rows = int(price_excs.groupby(["Source File", "Row Number"]).ngroups) if not price_excs.empty else 0
        
        qty_excs = exc_df[exc_df["Field"] == "Quantity"] if not exc_df.empty else pd.DataFrame()
        qty_rows = int(qty_excs.groupby(["Source File", "Row Number"]).ngroups) if not qty_excs.empty else 0

        # Preview columns mapping
        target_headers = {
            "sku": "Seller SKU",
            "article_number": "Article No",
            "Zeocm Status": "Zeocm Status",
            "launch_date": "Launch Date",
            "gender": "Gender",
            "product_name": "Product Name",
            "Gender Check": "Gender Check",
            "color_name": "Color Name",
            "ref_color_name": "Reference Color Name",
            "Color Check": "Color Check",
            "size": "Size",
            "ref_size": "Reference Size",
            "Size Check": "Size Check",
            "price": "RRP",
            "ref_rrp": "Reference RRP",
            "RRP Check": "RRP Check",
            "quantity": "Quantity"
        }
        preview_df = val_df.copy()
        for col in target_headers.keys():
            if col not in preview_df.columns:
                preview_df[col] = ""
        ordered_cols = list(target_headers.keys())
        preview_df = preview_df[ordered_cols].rename(columns=target_headers)

        return jsonify({
            "success": True,
            "metrics": {
                "total_records": len(val_df),
                "total_skus": val_df["sku"].nunique() if "sku" in val_df.columns else 0,
                "total_articles": val_df["article_number"].nunique() if "article_number" in val_df.columns else 0,
                "total_exceptions": len(exc_df) if not exc_df.empty else 0
            },
            "checklist": {
                "zecom_status_mismatches": no_status_count,
                "future_launch_dates": launch_rows,
                "gender_mismatches": gender_rows,
                "color_mismatches": color_rows,
                "size_mismatches": size_rows,
                "price_mismatches": price_rows,
                "nonzero_quantities": qty_rows
            },
            "preview": preview_df.head(500).to_dict(orient="records"),
            "val_df_json": val_df.to_dict(orient="records"), # For live sync input
            "report_name": fname,
            "report_base64": report_b64
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/listing-qc-compare", methods=["POST"])
def listing_qc_compare():
    try:
        channel = request.form.get("channel", "Shopee PH")
        req_json = request.json or {}
        val_df_data = req_json.get("val_df") # Sent from client
        
        # Read live files
        live_files = []
        for key, f in request.files.items():
            if key.startswith("live_"):
                live_files.append(FileWrapper(f))
                
        if not live_files:
            return jsonify({"success": False, "message": "No live files uploaded."}), 400
            
        consolidated_live = lqc_process_live_files(live_files, channel)
        if consolidated_live.empty:
            return jsonify({"success": False, "message": "Could not parse any valid listing data from the live files."}), 400

        standardized_source = pd.DataFrame(val_df_data)
        
        comp_df, comp_metrics = lqc_compare_source_and_live(
            standardized_source,
            consolidated_live,
            match_column="sku"
        )

        comp_excel_data = lqc_generate_comparison_excel_report(comp_df, comp_metrics)
        report_b64 = base64.b64encode(comp_excel_data).decode("utf-8")
        fname = f"Live_Listing_Sync_Audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        mismatches = comp_df[comp_df["Match Status"] != "Passed"]

        return jsonify({
            "success": True,
            "metrics": comp_metrics,
            "mismatches": mismatches.head(500).to_dict(orient="records"),
            "report_name": fname,
            "report_base64": report_b64
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# WSGI main entry wrapper
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

import io
import datetime
import pandas as pd
from typing import Dict, Tuple

def generate_qc_excel_report(val_df: pd.DataFrame, exc_df: pd.DataFrame, qc_stage: str) -> bytes:
    """
    Generates a beautifully formatted Excel report for validation results.
    Includes:
      - Sheet 1: Executive Dashboard (Summary metrics & Metadata)
      - Sheet 2: Detailed Exceptions (List of all Errors and Warnings)
      - Sheet 3: Validated Dataset (Full user data with validation flags)
    Returns:
      Bytes content of the generated Excel workbook.
    """
    output = io.BytesIO()
    
    # Pre-process tables for export (drop internal underscore columns from display sheets, except tracking)
    # On Sheet 3 (Validated Data), we want to make it look clean: rename tracking columns to user-friendly names
    clean_val_df = val_df.copy()
    
    # Ensure all target columns exist in clean_val_df
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
    
    for col in target_headers.keys():
        if col not in clean_val_df.columns:
            clean_val_df[col] = ""
            
    # Keep only the target columns in the exact order
    ordered_cols = list(target_headers.keys())
    clean_val_df = clean_val_df[ordered_cols]
    
    # Rename columns to the requested headers
    clean_val_df = clean_val_df.rename(columns=target_headers)

    # Calculate metrics for the dashboard
    total_records = len(val_df)
    passed_count = sum(val_df["_qc_status"] == "Passed")
    warning_count = sum(val_df["_qc_status"] == "Warning")
    failed_count = sum(val_df["_qc_status"] == "Failed")
    pass_rate = (passed_count / total_records * 100) if total_records > 0 else 0.0
    
    summary_data = {
        "Metric": [
            "Total Records Validated",
            "Passed (No Errors/Warnings)",
            "Warnings Flagged",
            "Failed (Critical Errors)",
            "Pass Rate"
        ],
        "Count / Value": [
            total_records,
            passed_count,
            warning_count,
            failed_count,
            f"{pass_rate:.2f}%"
        ]
    }
    summary_df = pd.DataFrame(summary_data)
    
    # Metadata info
    metadata_data = {
        "Configuration Details": [
            "Validation Run Date",
            "QC Verification Stage",
            "Target Files Processed",
            "Status"
        ],
        "Value": [
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            qc_stage,
            ", ".join(val_df["_source_file"].unique()),
            "Complete"
        ]
    }
    metadata_df = pd.DataFrame(metadata_data)

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        workbook = writer.book
        
        # ── Color Palettes & Formats ──────────────────────────────────────────
        # Fonts: Segoe UI, Arial
        header_fmt = workbook.add_format({
            'bold': True,
            'font_name': 'Segoe UI',
            'font_color': '#ffffff',
            'bg_color': '#1e3a8a', # Dark navy
            'border': 1,
            'border_color': '#d1d5db',
            'align': 'left',
            'valign': 'vcenter'
        })
        
        title_fmt = workbook.add_format({
            'bold': True,
            'font_name': 'Segoe UI',
            'font_size': 16,
            'font_color': '#1e3a8a'
        })
        
        subtitle_fmt = workbook.add_format({
            'italic': True,
            'font_name': 'Segoe UI',
            'font_size': 10,
            'font_color': '#4b5563'
        })
        
        standard_fmt = workbook.add_format({
            'font_name': 'Segoe UI',
            'font_size': 10,
            'border': 1,
            'border_color': '#e5e7eb',
            'align': 'left'
        })
        
        # Color codes for cells
        red_fill = workbook.add_format({
            'font_name': 'Segoe UI',
            'font_size': 10,
            'bg_color': '#fee2e2', # Light red
            'font_color': '#991b1b', # Dark red
            'border': 1,
            'border_color': '#fca5a5'
        })
        
        yellow_fill = workbook.add_format({
            'font_name': 'Segoe UI',
            'font_size': 10,
            'bg_color': '#fef3c7', # Light yellow
            'font_color': '#92400e', # Dark gold
            'border': 1,
            'border_color': '#fde047'
        })
        
        green_fill = workbook.add_format({
            'font_name': 'Segoe UI',
            'font_size': 10,
            'bg_color': '#d1fae5', # Light green
            'font_color': '#065f46', # Dark green
            'border': 1,
            'border_color': '#6ee7b7'
        })

        # ── Sheet 1: Validated Data ───────────────────────────────────────────
        clean_val_df.to_excel(writer, sheet_name="Validated Data", startrow=3, index=False)
        ws_val = writer.sheets["Validated Data"]
        ws_val.write("A1", "STANDARDIZED & VALIDATED DATASET", title_fmt)
        ws_val.write("A2", "Full product rows with appended QC audit markers.", subtitle_fmt)
        
        # Headers
        ws_val.write_row("A4", clean_val_df.columns, header_fmt)
        
        # Populate and style validated data
        for r in range(len(clean_val_df)):
            row_idx = 4 + r
            status = val_df.iloc[r]["_qc_status"] # QC Status from original val_df
            
            if status == "Passed":
                row_format = green_fill
            elif status == "Warning":
                row_format = yellow_fill
            else:
                row_format = red_fill
                
            for c in range(len(clean_val_df.columns)):
                val = clean_val_df.iloc[r, c]
                ws_val.write(row_idx, c, str(val) if not pd.isna(val) else "", row_format)
                
        # Auto-adjust column widths
        for col_num, col_name in enumerate(clean_val_df.columns):
            col_lens = clean_val_df[col_name].apply(lambda x: len(str(x)) if pd.notna(x) else 0)
            max_val_len = col_lens.max() if not col_lens.empty else 0
            if pd.isna(max_val_len):
                max_val_len = 0
            max_len = max(int(max_val_len), len(col_name)) + 3
            ws_val.set_column(col_num, col_num, min(max(max_len, 10), 40))
            
        ws_val.autofilter(3, 0, len(clean_val_df) + 3, len(clean_val_df.columns) - 1)
        ws_val.hide_gridlines(2)

    return output.getvalue()


def generate_comparison_excel_report(comp_df: pd.DataFrame, summary_metrics: Dict) -> bytes:
    """
    Generates a formatted Excel report highlighting discrepancies between source data and live store listings.
    Includes:
      - Sheet 1: Audit Summary (Summary metrics)
      - Sheet 2: Discrepancy details
    """
    output = io.BytesIO()
    
    # Prepare summary df
    summary_data = {
        "Audit Checkpoint": list(summary_metrics.keys()),
        "Count of Records": list(summary_metrics.values())
    }
    summary_df = pd.DataFrame(summary_data)

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        workbook = writer.book
        
        # Formats
        header_fmt = workbook.add_format({
            'bold': True,
            'font_name': 'Segoe UI',
            'font_color': '#ffffff',
            'bg_color': '#0f172a', # Charcoal
            'border': 1,
            'border_color': '#d1d5db',
            'align': 'left',
            'valign': 'vcenter'
        })
        
        title_fmt = workbook.add_format({
            'bold': True,
            'font_name': 'Segoe UI',
            'font_size': 15,
            'font_color': '#0f172a'
        })
        
        subtitle_fmt = workbook.add_format({
            'italic': True,
            'font_name': 'Segoe UI',
            'font_size': 10,
            'font_color': '#6b7280'
        })
        
        standard_fmt = workbook.add_format({
            'font_name': 'Segoe UI',
            'font_size': 10,
            'border': 1,
            'border_color': '#e5e7eb',
            'align': 'left'
        })
        
        red_fill = workbook.add_format({
            'font_name': 'Segoe UI',
            'font_size': 10,
            'bg_color': '#fee2e2',
            'font_color': '#991b1b',
            'border': 1,
            'border_color': '#fca5a5'
        })
        
        yellow_fill = workbook.add_format({
            'font_name': 'Segoe UI',
            'font_size': 10,
            'bg_color': '#fef3c7',
            'font_color': '#92400e',
            'border': 1,
            'border_color': '#fde047'
        })
        
        green_fill = workbook.add_format({
            'font_name': 'Segoe UI',
            'font_size': 10,
            'bg_color': '#d1fae5',
            'font_color': '#065f46',
            'border': 1,
            'border_color': '#6ee7b7'
        })

        even_row_fmt = workbook.add_format({
            'font_name': 'Segoe UI',
            'font_size': 10,
            'border': 1,
            'border_color': '#e5e7eb',
            'bg_color': '#ffffff',
            'align': 'left'
        })
        
        odd_row_fmt = workbook.add_format({
            'font_name': 'Segoe UI',
            'font_size': 10,
            'border': 1,
            'border_color': '#e5e7eb',
            'bg_color': '#f8fafc',
            'align': 'left'
        })

        # ── Sheet 1: Summary ──────────────────────────────────────────────────
        summary_df.to_excel(writer, sheet_name="Audit Summary", startrow=4, index=False)
        ws_sum = writer.sheets["Audit Summary"]
        ws_sum.write("A1", "LIVE LISTING COMPARISON AUDIT SUMMARY", title_fmt)
        ws_sum.write("A2", f"Comparison Run Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", subtitle_fmt)
        
        ws_sum.set_column("A:A", 35)
        ws_sum.set_column("B:B", 25)
        
        ws_sum.write_row("A5", summary_df.columns, header_fmt)
        
        for r in range(len(summary_df)):
            row_idx = 5 + r
            ws_sum.write(row_idx, 0, summary_df.iloc[r, 0], standard_fmt)
            val = summary_df.iloc[r, 1]
            
            if r == 1: # Fully matched
                ws_sum.write(row_idx, 1, val, green_fill)
            elif r == 2: # Mismatches
                ws_sum.write(row_idx, 1, val, red_fill)
            elif r in [3, 4]: # Missing or extra
                ws_sum.write(row_idx, 1, val, yellow_fill)
            else:
                ws_sum.write(row_idx, 1, val, standard_fmt)
                
        ws_sum.hide_gridlines(2)

        # ── Sheet 2: Discrepancy Details ──────────────────────────────────────
        comp_df.to_excel(writer, sheet_name="Discrepancy Details", startrow=3, index=False)
        ws_det = writer.sheets["Discrepancy Details"]
        ws_det.write("A1", "DETAILED DISCREPANCY COMPARISON", title_fmt)
        ws_det.write("A2", "Complete list of mismatches and listing discrepancies between source master and store listings.", subtitle_fmt)
        
        ws_det.write_row("A4", comp_df.columns, header_fmt)
        
        for r in range(len(comp_df)):
            row_idx = 4 + r
            base_format = even_row_fmt if r % 2 == 0 else odd_row_fmt
            status = str(comp_df.iloc[r, 7]) if pd.notna(comp_df.iloc[r, 7]) else "" # Match Status is now at index 7
            
            for c in range(len(comp_df.columns)):
                val = comp_df.iloc[r, c]
                val_str = str(val) if pd.notna(val) else ""
                
                # Default style: alternating rows
                cell_format = base_format
                
                # Check for Match Status cell override
                if c == 7:
                    if "Passed" in val_str:
                        cell_format = green_fill
                    elif "Mismatch" in val_str or "Failed" in val_str:
                        cell_format = red_fill
                    elif "Warning" in val_str:
                        cell_format = yellow_fill
                
                # Check for Audit Checks cells override (indices 9 to 16)
                elif c >= 9 and c <= 16:
                    if val_str in ["OK", "Yes", "Passed"]:
                        cell_format = green_fill
                    elif val_str in ["Mismatch", "Error", "Failed"]:
                        cell_format = red_fill
                    elif val_str in ["Warning"]:
                        cell_format = yellow_fill
                        
                ws_det.write(row_idx, c, val_str, cell_format)
                
        for col_num, col_name in enumerate(comp_df.columns):
            col_lens = comp_df[col_name].apply(lambda x: len(str(x)) if pd.notna(x) else 0)
            max_val_len = col_lens.max() if not col_lens.empty else 0
            if pd.isna(max_val_len):
                max_val_len = 0
            max_len = max(int(max_val_len), len(col_name)) + 3
            ws_det.set_column(col_num, col_num, min(max(max_len, 10), 45))
            
        ws_det.autofilter(3, 0, len(comp_df) + 3, len(comp_df.columns) - 1)
        ws_det.hide_gridlines(2)

    return output.getvalue()
